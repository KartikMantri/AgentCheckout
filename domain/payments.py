"""
Payment gateway. Falls back to a mock automatically when RAZORPAY_KEY_ID/
RAZORPAY_KEY_SECRET aren't set — same pattern as the LLM router degrading
when a provider key is missing. Nothing above this file needs to know
which mode it's in; domain/orders.py calls is_live() only to decide
whether to show a real "pay now" step in the UI.

Two structurally different operations here, on purpose (see the README
and notes/build_log.md for why): creating an order needs no human and
stays fully agent-callable. Capturing a REAL payment cannot — some real
payment credential has to be entered once, through Razorpay's own
Checkout widget, before there's anything to verify or capture. That's
not a limitation of this code; no payment gateway on earth lets a
server silently charge a card that was never provided anywhere.
"""

import os
import uuid
from datetime import datetime, timezone


def is_live() -> bool:
    return bool(os.getenv("RAZORPAY_KEY_ID")) and bool(os.getenv("RAZORPAY_KEY_SECRET"))


def _client():
    """
    On some Windows setups, `requests` (which the razorpay SDK uses)
    fails SSL verification against api.razorpay.com even with the
    SDK's own bundled CA file — some local root CA (antivirus/network
    tooling doing TLS inspection) isn't in any certifi-style bundle,
    only in the OS trust store. `truststore` already works reliably
    here for httpx (the LLM calls) via the OS store — this wires the
    SAME approach into requests, but scoped to only this one Session,
    never globally monkey-patching ssl. A global patch (via
    pip-system-certs) was tried and reverted — it broke every other
    SSL connection in the process; see notes/build_log.md.
    """
    import ssl

    import requests
    import truststore
    from razorpay import Client

    session = requests.Session()

    class _TruststoreAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            return super().init_poolmanager(*args, **kwargs)

    session.mount("https://", _TruststoreAdapter())
    return Client(session=session, auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))


class MockGateway:
    def create_order(self, amount: int, receipt: str) -> str:
        return "rzp_mock_" + receipt

    def capture(self, order_id: str, amount: int) -> dict:
        return {
            "razorpay_payment_id": "pay_mock_" + uuid.uuid4().hex[:12],
            "status": "captured",
            "amount": amount,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


class RazorpayGateway:
    """Real test-mode (or live-mode, if you ever point it there) Razorpay."""

    def create_order(self, amount: int, receipt: str) -> str:
        """amount in paise. Pure server-side call — no human needed."""
        order = _client().order.create({"amount": amount, "currency": "INR", "receipt": receipt})
        return order["id"]

    def verify_and_capture(self, razorpay_order_id: str, razorpay_payment_id: str,
                            razorpay_signature: str, amount: int) -> dict:
        """Only callable AFTER a human completed Razorpay's Checkout widget —
        this verifies that really happened before trusting anything, then
        captures if the payment isn't already auto-captured."""
        client = _client()

        # Raises razorpay.errors.SignatureVerificationError on mismatch —
        # caller must not catch-and-ignore this. A failed signature means
        # the callback may be forged; never fulfil on a failed check.
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

        payment = client.payment.fetch(razorpay_payment_id)
        if payment["status"] == "authorized":
            payment = client.payment.capture(razorpay_payment_id, amount, {"currency": "INR"})

        return {
            "razorpay_payment_id": payment["id"],
            "status": payment["status"],
            "amount": amount,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


GATEWAY = RazorpayGateway() if is_live() else MockGateway()
