"""
Every business limit in the project lives in this file, as a pure
decision: given the proposed action and the current state, allowed or
not. No LLM import here, ever — that's not a style preference, it's
the entire trust boundary. If a rule can be argued with, it doesn't
belong in this file.

The actual numbers (10%, ₹5,000, ...) live in config.py, not here —
this file only knows how to compare against them.
"""

import config
from domain.cart import discount_count
from domain.catalog import get_by_id
from guardrails.verdict import Verdict


def check_stock(product_id: str, qty: int) -> Verdict:
    """GR4 — stock check before cart add, always."""
    product = get_by_id(product_id)
    if product is None:
        return Verdict(False, "product_not_found", detail={"product_id": product_id})
    if qty > product["stock"]:
        return Verdict(False, "insufficient_stock", detail={"requested": qty, "available": product["stock"]})
    return Verdict(True)


def check_discount(cart_id: str, pct: float) -> Verdict:
    """GR1 (max auto-approved discount) + GR3 (one discount per order)."""
    if discount_count(cart_id) >= config.MAX_DISCOUNTS_PER_ORDER:
        return Verdict(False, "discount_already_applied", detail={"limit": config.MAX_DISCOUNTS_PER_ORDER})

    if pct > config.MAX_AUTO_DISCOUNT_PCT:
        return Verdict(
            False, "discount_exceeds_cap",
            escalation_required=True,
            detail={"cap": config.MAX_AUTO_DISCOUNT_PCT, "requested": pct},
        )

    return Verdict(True)


def check_order_value(total: int) -> Verdict:
    """GR2 — max auto-approved order value. Wired in when create_order/
    capture_payment land in Step 9; written now because it has no
    dependency on anything not built yet."""
    if total > config.MAX_AUTO_ORDER_VALUE:
        return Verdict(
            False, "order_value_exceeds_cap",
            escalation_required=True,
            detail={"cap": config.MAX_AUTO_ORDER_VALUE, "total": total},
        )
    return Verdict(True)


def check_refund_eligibility(order_status: str) -> Verdict:
    """GR5 — refund without a matching paid order is a hard reject."""
    if order_status != "paid":
        return Verdict(False, "no_matching_paid_order", detail={"order_status": order_status})
    return Verdict(True)


def check_capture_eligibility(order_status: str) -> Verdict:
    """GR6 — payment capture on an unconfirmed order is a hard reject.
    'paid' is allowed through here on purpose: a repeat capture on an
    already-paid order is a legitimate idempotent replay (FR9), handled
    downstream in domain.orders — this guardrail's job is catching an
    order that was never validly created, not blocking a repeat call."""
    if order_status not in ("created", "paid"):
        return Verdict(False, "order_not_confirmed", detail={"order_status": order_status})
    return Verdict(True)
