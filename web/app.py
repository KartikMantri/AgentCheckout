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

from agent.loop import run
from agent.session import get_session, reset_session
from audit.logger import read_all
from domain.cart import get_cart, init_cart_tables
from domain.catalog import init_db, list_all
from domain.orders import get_order, init_order_tables, verify_and_capture_payment
from domain.payments import is_live

init_db()
init_cart_tables()
init_order_tables()

app = FastAPI(title="AgentCheckout")

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(WEB_DIR, "store.html")
CHAT_PATH = os.path.join(WEB_DIR, "index.html")


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.get("/")
def storefront():
    return FileResponse(STORE_PATH)


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
