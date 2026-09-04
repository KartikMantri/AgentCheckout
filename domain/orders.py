"""
Orders freeze a cart's total at creation. Payments are captured against
a frozen order and idempotent by construction — a second capture for
an order that already has a payment row returns that row instead of
calling the gateway again (FR9).

Two ways a payment gets finalized, converging on the same DB writes
(_finalize_payment): capture_payment_raw() is the agent-callable path
(mock gateway, or a real one once you've built full S2S — not done
here) and verify_and_capture_payment() is the human-completes-a-real-
Razorpay-Checkout-widget path. Same invariants either way: idempotent,
stock only moves once payment is genuinely confirmed.
"""

import uuid
from datetime import datetime, timezone

from domain.cart import get_cart
from domain.catalog import decrement_stock
from domain.db import connect


def init_order_tables() -> None:
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            cart_id TEXT NOT NULL,
            total INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            razorpay_order_id TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            order_id TEXT PRIMARY KEY,
            razorpay_payment_id TEXT,
            status TEXT NOT NULL,
            amount INTEGER NOT NULL,
            captured_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_order_raw(cart_id: str) -> dict:
    """No guardrail check here — the registry already ran GR2 before
    calling this. Once written, this order's total never changes again,
    even if the catalog price or the cart itself changes later."""
    from domain.payments import GATEWAY

    cart = get_cart(cart_id)
    order_id = "ORDER-" + uuid.uuid4().hex[:8]
    razorpay_order_id = GATEWAY.create_order(cart["total"] * 100, receipt=order_id)  # paise

    conn = connect()
    conn.execute(
        "INSERT INTO orders (id, cart_id, total, status, razorpay_order_id, created_at) VALUES (?, ?, ?, 'created', ?, ?)",
        (order_id, cart_id, cart["total"], razorpay_order_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "order": get_order(order_id)}


def create_pending_approval(cart_id: str) -> dict:
    """A cart that was blocked by GR2 (order-value cap) gets frozen here
    as a real record — a snapshot of the total at the moment it was
    blocked, independent of whatever happens to the live cart
    afterward. This is what makes 'escalated to a human' mean something
    concrete instead of just a rejection message: there's now an actual
    row a real merchant operator can review, approve, or reject."""
    cart = get_cart(cart_id)
    order_id = "PENDING-" + uuid.uuid4().hex[:8]
    conn = connect()
    conn.execute(
        "INSERT INTO orders (id, cart_id, total, status, razorpay_order_id, created_at) VALUES (?, ?, ?, 'pending_approval', NULL, ?)",
        (order_id, cart_id, cart["total"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return get_order(order_id)


def list_pending_approvals() -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status = 'pending_approval' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_pending_order(order_id: str) -> dict:
    """The actual completion of GR2's escalation path. A human (the
    merchant operator, via /admin) reviewed the frozen total and
    decided it's fine — only now does a real Razorpay order get
    created, since there was no point creating one for every blocked
    attempt regardless of whether a human ever approves it."""
    order = get_order(order_id)
    if order is None or order["status"] != "pending_approval":
        return {"ok": False, "reason": "not_pending"}

    from domain.payments import GATEWAY

    razorpay_order_id = GATEWAY.create_order(order["total"] * 100, receipt=order_id)
    conn = connect()
    conn.execute(
        "UPDATE orders SET status = 'created', razorpay_order_id = ? WHERE id = ?",
        (razorpay_order_id, order_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "order": get_order(order_id)}


def reject_pending_order(order_id: str) -> dict:
    order = get_order(order_id)
    if order is None or order["status"] != "pending_approval":
        return {"ok": False, "reason": "not_pending"}

    conn = connect()
    conn.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "order": get_order(order_id)}


def get_order(order_id: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_payment(order_id: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _finalize_payment(order: dict, result: dict) -> dict:
    """Shared by both capture paths: write the payment row, mark the
    order paid, and only now move stock — the one place a sale is
    genuinely final, not at add-to-cart or create_order."""
    conn = connect()
    conn.execute(
        "INSERT INTO payments (order_id, razorpay_payment_id, status, amount, captured_at) VALUES (?, ?, ?, ?, ?)",
        (order["id"], result["razorpay_payment_id"], result["status"], result["amount"], result["captured_at"]),
    )
    conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order["id"],))
    conn.commit()
    conn.close()

    cart = get_cart(order["cart_id"])
    for item in cart["items"]:
        decrement_stock(item["product_id"], item["qty"])

    return {"ok": True, "payment": result, "idempotent_replay": False}


def capture_payment_raw(order_id: str) -> dict:
    """Agent-callable path. Idempotent: a repeat call for an already-paid
    order returns the original payment instead of charging again.

    In live mode this deliberately does NOT charge anything — there is
    no payment credential to charge. It's a real, structured rejection
    telling the model a human needs to complete Razorpay's Checkout
    widget once (surfaced in the web storefront), not a crash and not
    a silent mock charge that would misrepresent what happened."""
    existing = get_payment(order_id)
    if existing is not None:
        return {"ok": True, "payment": existing, "idempotent_replay": True}

    from domain.payments import GATEWAY, is_live

    order = get_order(order_id)
    if order is None:
        return {"ok": False, "reason": "order_not_found", "detail": {"order_id": order_id}}

    if is_live():
        import config
        return {
            "ok": False,
            "reason": "human_checkout_required",
            "detail": "Real Razorpay credentials are configured — I can't charge a "
                      "payment method that was never provided. Share the payment_link "
                      "below with the customer so they can complete the real Checkout "
                      "widget themselves — that's the only way this order can become paid.",
            "payment_link": f"{config.PUBLIC_BASE_URL}/pay/{order_id}",
        }

    result = GATEWAY.capture(order_id, order["total"])
    return _finalize_payment(order, result)


def verify_and_capture_payment(order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> dict:
    """The human-completed-a-real-checkout-widget path. Never trusts the
    browser's callback blindly — verifies the signature against OUR
    stored razorpay_order_id (never one supplied by the client) before
    doing anything else. A failed signature is rejected outright, not
    retried, not silently accepted."""
    existing = get_payment(order_id)
    if existing is not None:
        return {"ok": True, "payment": existing, "idempotent_replay": True}

    order = get_order(order_id)
    if order is None:
        return {"ok": False, "reason": "order_not_found"}

    from domain.payments import GATEWAY, is_live

    if not is_live():
        return {"ok": False, "reason": "gateway_not_live", "detail": "Real Razorpay credentials aren't configured."}

    try:
        result = GATEWAY.verify_and_capture(
            order["razorpay_order_id"], razorpay_payment_id, razorpay_signature, order["total"] * 100
        )
    except Exception as exc:
        return {"ok": False, "reason": "signature_verification_failed", "detail": str(exc)}

    return _finalize_payment(order, result)
