"""
FastAPI wrapper around the agent loop. Pure plumbing — no guardrail or
tool logic lives here; every request calls agent.loop.run() the exact
same way every script in scripts/ already does. Delete this file and
the agent still works as a plain API, same test as everywhere else.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from agent.loop import run
from agent.session import get_session, reset_session
from audit.logger import log_event, read_all
from domain.cart import clear_cart as clear_cart_raw
from domain.cart import get_cart, init_cart_tables
from domain.cart import remove_item as remove_item_raw
from domain.catalog import init_db, list_all
from domain.orders import create_order_raw, get_order, init_order_tables, verify_and_capture_payment
from domain.payments import is_live

init_db()
init_cart_tables()
init_order_tables()

app = FastAPI(title="AgentCheckout")

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(WEB_DIR, "store.html")
CHAT_PATH = os.path.join(WEB_DIR, "index.html")
PAY_PATH = os.path.join(WEB_DIR, "pay.html")


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.get("/")
def storefront():
    return FileResponse(STORE_PATH)


@app.get("/pay/{order_id}")
def pay_page(order_id: str):
    """Standalone payment page any interface can link to — chat, MCP,
    Claude Desktop, anywhere an LLM can hand back a URL but can't open
    a browser window itself. Same real Razorpay widget, same signature
    verification as everywhere else; order_id in the URL just tells
    the page which order to load via /api/order."""
    return FileResponse(PAY_PATH)


@app.get("/chat")
def chat_console():
    return FileResponse(CHAT_PATH)


@app.get("/api/catalog")
def catalog():
    return list_all()


@app.post("/api/chat")
def chat(req: ChatRequest):
    turn_start = datetime.now(timezone.utc).isoformat()
    try:
        reply, cart_id = run(req.message, session_id=req.session_id, verbose=False)
    except Exception as exc:
        return {
            "reply": f"Something went wrong on the server side: {type(exc).__name__}: {exc}",
            "cart": None,
            "events": [],
            "error": True,
        }

    events = [
        e for e in read_all()
        if e.get("session_id") == req.session_id and e.get("ts", "") >= turn_start
    ]
    return {"reply": reply, "cart": get_cart(cart_id), "events": events, "error": False}


@app.get("/api/cart/{session_id}")
def cart_state(session_id: str):
    session = get_session(session_id)
    return get_cart(session["cart_id"])


@app.post("/api/reset/{session_id}")
def reset(session_id: str):
    reset_session(session_id)
    session = get_session(session_id)
    return get_cart(session["cart_id"])


class RemoveItemRequest(BaseModel):
    product_id: str


@app.post("/api/cart/{session_id}/remove")
def cart_remove(session_id: str, req: RemoveItemRequest):
    """Direct, no-guardrail path — removing your own item has no
    business-limit at stake, so there's no reason to route it through
    the agent loop. Still logged, so the audit trail stays honest about
    who actually did what: 'customer_direct', not 'agent'."""
    session = get_session(session_id)
    result = remove_item_raw(session["cart_id"], req.product_id)
    log_event(
        session_id=session_id, actor="customer_direct", tool="remove_from_cart",
        args_json=req.model_dump_json(), verdict_json={"allowed": True, "reason": "ok", "escalation_required": False},
        outcome_json=str(result), provider=None, model=None, is_failover=None, tokens=None, latency_ms=None,
    )
    return result["cart"]


@app.post("/api/cart/{session_id}/clear")
def cart_clear(session_id: str):
    session = get_session(session_id)
    result = clear_cart_raw(session["cart_id"])
    log_event(
        session_id=session_id, actor="customer_direct", tool="clear_cart",
        args_json="{}", verdict_json={"allowed": True, "reason": "ok", "escalation_required": False},
        outcome_json=str(result), provider=None, model=None, is_failover=None, tokens=None, latency_ms=None,
    )
    return result["cart"]


@app.get("/api/limits")
def limits():
    """Public-safe copy of the auto-approval numbers, so the storefront
    UI can tell a human whether their own action needs the direct
    confirm-checkout path or the normal (guardrail-checked) one."""
    return {
        "max_auto_order_value": config.MAX_AUTO_ORDER_VALUE,
        "max_auto_discount_pct": config.MAX_AUTO_DISCOUNT_PCT,
    }


@app.post("/api/cart/{session_id}/confirm-checkout")
def confirm_checkout(session_id: str):
    """A SEPARATE path from the agent's create_order tool, reachable only
    by a direct UI button click — never by anything an LLM can output,
    no matter how a chat message is phrased. GR2 (the order-value cap)
    exists to stop an AI from autonomously committing to a large spend
    it decided on its own; it does not need to apply here, because a
    human just looked at this exact total on their own screen and
    clicked a real button — that click already IS the human-in-the-loop
    the cap was trying to guarantee. The chat/MCP-driven create_order
    tool is completely unchanged: an AI still can never talk its way
    past GR2. Payment is a separate, still fully-enforced layer either
    way — this only creates the order, it never moves money."""
    session = get_session(session_id)
    cart = get_cart(session["cart_id"])
    if not cart["items"]:
        return {"ok": False, "reason": "cart_empty"}

    result = create_order_raw(session["cart_id"])
    log_event(
        session_id=session_id, actor="customer_direct", tool="create_order",
        args_json="{}",
        verdict_json={"allowed": True, "reason": "human_confirmed_direct_checkout", "escalation_required": False},
        outcome_json=str(result), provider=None, model=None, is_failover=None, tokens=None, latency_ms=None,
    )
    return result


@app.get("/api/razorpay-config")
def razorpay_config():
    """The frontend uses this to decide whether to open a real Razorpay
    Checkout widget or just simulate — never expose the key SECRET here,
    only the key ID, which is meant to be public (it's embedded in every
    Razorpay Checkout page load by design)."""
    return {"mode": "live" if is_live() else "mock", "key_id": os.getenv("RAZORPAY_KEY_ID", "")}


@app.get("/api/order/{order_id}")
def order_state(order_id: str):
    order = get_order(order_id)
    if order is None:
        return {"error": "order_not_found"}
    return order


class VerifyPaymentRequest(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/api/verify-payment")
def verify_payment(req: VerifyPaymentRequest):
    """Called only after a human completed the real Razorpay Checkout
    widget. Verifies the signature server-side before trusting anything
    the browser sent back — see domain/orders.py for why."""
    return verify_and_capture_payment(req.order_id, req.razorpay_payment_id, req.razorpay_signature)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
