"""
name -> (schema, guardrail, fn). This is the one place that knows how
to fully process a tool call end to end: parse -> validate -> guardrail
-> execute. The agent loop calls dispatch() and nothing else — it never
touches validation or guardrail logic directly, which is what makes
the "delete the agent layer, the rest still works as an API" test
(§2.3) true.
"""

import json

from domain.cart import add_item, apply_discount_raw, clear_cart, get_cart, remove_item
from domain.catalog import search
from domain.orders import capture_payment_raw, create_order_raw, create_pending_approval, get_order
from guardrails.rules import check_capture_eligibility, check_discount, check_order_value, check_stock
from guardrails.verdict import Verdict
from tools.definitions import (
    ADD_TO_CART,
    APPLY_DISCOUNT,
    ASK_CLARIFICATION,
    CAPTURE_PAYMENT,
    CLEAR_CART,
    CREATE_ORDER,
    ESCALATE_TO_HUMAN,
    REMOVE_FROM_CART,
    SEARCH_CATALOG,
)
from tools.schemas import validate_args


def _guard_add_to_cart(args: dict, cart_id: str):
    return check_stock(args["product_id"], args["qty"])


def _guard_apply_discount(args: dict, cart_id: str):
    return check_discount(cart_id, args["pct"])


def _guard_create_order(args: dict, cart_id: str):
    cart = get_cart(cart_id)
    if not cart["items"]:
        return Verdict(False, "cart_empty", detail={"cart_id": cart_id})
    return check_order_value(cart["total"])


def _guard_capture_payment(args: dict, cart_id: str):
    order = get_order(args["order_id"])
    if order is None:
        return Verdict(False, "order_not_found", detail={"order_id": args["order_id"]})

    eligibility = check_capture_eligibility(order["status"])
    if not eligibility.allowed:
        return eligibility

    return check_order_value(order["total"])


def _escalate_to_human(args: dict, cart_id: str):
    result = {"ok": True, "action": "escalated", **args}
    # An external agent can reach this tool directly — "escalate this" in
    # conversation maps to it more naturally than "call create_order and
    # let it bounce" — so the trackable record can't depend on the caller
    # having gone through create_order first. If the cart's over the cap
    # right now, freeze it here too, same as create_order's own rejection
    # path does.
    cart = get_cart(cart_id)
    if cart["items"] and not check_order_value(cart["total"]).allowed:
        pending = create_pending_approval(cart_id)
        result["pending_order_id"] = pending["id"]
    return result


REGISTRY = {
    "search_catalog": {
        "schema": SEARCH_CATALOG, "guardrail": None,
        "fn": lambda args, cart_id: search(**args), "terminal": False,
    },
    "add_to_cart": {
        "schema": ADD_TO_CART, "guardrail": _guard_add_to_cart,
        "fn": lambda args, cart_id: add_item(cart_id=cart_id, **args), "terminal": False,
    },
    "remove_from_cart": {
        "schema": REMOVE_FROM_CART, "guardrail": None,
        "fn": lambda args, cart_id: remove_item(cart_id=cart_id, **args), "terminal": False,
    },
    "clear_cart": {
        "schema": CLEAR_CART, "guardrail": None,
        "fn": lambda args, cart_id: clear_cart(cart_id), "terminal": False,
    },
    "apply_discount": {
        "schema": APPLY_DISCOUNT, "guardrail": _guard_apply_discount,
        "fn": lambda args, cart_id: apply_discount_raw(cart_id, args["pct"]), "terminal": False,
    },
    "create_order": {
        "schema": CREATE_ORDER, "guardrail": _guard_create_order,
        "fn": lambda args, cart_id: create_order_raw(cart_id), "terminal": False,
    },
    "capture_payment": {
        "schema": CAPTURE_PAYMENT, "guardrail": _guard_capture_payment,
        "fn": lambda args, cart_id: capture_payment_raw(args["order_id"]), "terminal": False,
    },
    "ask_clarification": {
        "schema": ASK_CLARIFICATION, "guardrail": None,
        "fn": lambda args, cart_id: {"ok": True, "action": "clarification_requested", **args}, "terminal": True,
    },
    "escalate_to_human": {
        "schema": ESCALATE_TO_HUMAN, "guardrail": None,
        "fn": _escalate_to_human, "terminal": True,
    },
}

ALL_SCHEMAS = [entry["schema"] for entry in REGISTRY.values()]


def dispatch(tool_name: str, raw_args_json: str, cart_id: str) -> dict:
    """Always returns a structured dict. Never raises for a bad or
    disallowed call — that's the entire point of this function."""
    if tool_name not in REGISTRY:
        return {"ok": False, "reason": "unknown_tool", "detail": tool_name}

    try:
        raw_args = json.loads(raw_args_json)
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "malformed_json", "detail": str(exc)}

    parsed_args, error = validate_args(tool_name, raw_args)
    if error is not None:
        return {"ok": False, "reason": "invalid_arguments", "detail": error}

    entry = REGISTRY[tool_name]

    if entry["guardrail"] is not None:
        verdict = entry["guardrail"](parsed_args, cart_id)
        if not verdict.allowed:
            rejection = {
                "ok": False,
                "reason": verdict.reason,
                "escalation_required": verdict.escalation_required,
                "detail": verdict.detail,
            }
            # The one rejection that gets a real, trackable record: a
            # merchant operator can actually review and approve this one
            # later (/admin) — everything else is just a rejection message.
            if tool_name == "create_order" and verdict.reason == "order_value_exceeds_cap":
                pending = create_pending_approval(cart_id)
                rejection["pending_order_id"] = pending["id"]
            return rejection

    return entry["fn"](parsed_args, cart_id)


def is_terminal(tool_name: str) -> bool:
    entry = REGISTRY.get(tool_name)
    return bool(entry and entry["terminal"])
