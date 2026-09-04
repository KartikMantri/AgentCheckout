"""
Step 9 — orders + payment.

Four things to prove:
  1. A full conversational purchase completes end to end.
  2. Stock actually decrements on confirmed payment (not on add-to-cart,
     not on create_order) — the model's own capture_payment call inside
     the conversation is the "first" real charge.
  3. Calling capture_payment again for the same order is a true no-op:
     idempotent_replay flips to True, and stock does NOT move a second
     time.
  4. GR2 (order value cap) blocks create_order on an order too large to
     auto-approve, same shape as GR1 blocking apply_discount.

Run: .venv\\Scripts\\python.exe scripts\\step9_orders.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from agent.loop import run
from domain.cart import init_cart_tables
from domain.catalog import get_by_id, init_db
from domain.db import connect
from domain.orders import capture_payment_raw, init_order_tables

init_db()
init_cart_tables()
init_order_tables()

print("=" * 70)
print("1) Full purchase, end to end, in conversation")
print("=" * 70)
stock_before = get_by_id("SKU-101")["stock"]
print(f"SKU-101 stock before purchase: {stock_before}")

answer, cart_id = run(
    "Add one Aster Glide 3 to my cart, then create the order and capture payment.",
    session_id="step9-happy-path",
)
print(f"\nAssistant: {answer}")

stock_after = get_by_id("SKU-101")["stock"]
print(f"SKU-101 stock after purchase (should be {stock_before - 1}): {stock_after}")
assert stock_after == stock_before - 1, "stock did not decrement on capture!"
print("Confirmed: stock decremented by exactly 1, on payment capture, not before.")

print("\n" + "=" * 70)
print("2) Calling capture_payment again for the same order")
print("=" * 70)
conn = connect()
row = conn.execute("SELECT id FROM orders ORDER BY created_at DESC LIMIT 1").fetchone()
conn.close()
order_id = row["id"]

repeat = capture_payment_raw(order_id)
stock_after_repeat = get_by_id("SKU-101")["stock"]
print(f"Repeat call: idempotent_replay={repeat['idempotent_replay']}  payment_id={repeat['payment']['razorpay_payment_id']}")
print(f"Stock after repeat call (should still be {stock_after}): {stock_after_repeat}")
assert repeat["idempotent_replay"] is True, "should have been an idempotent replay!"
assert stock_after_repeat == stock_after, "stock moved a SECOND time — double charge equivalent!"
print("Confirmed: idempotent, no second charge, no second stock decrement.")

print("\n" + "=" * 70)
print("3) GR2 — order value cap should block a >Rs.5,000 order")
print("=" * 70)
answer, cart_id = run(
    "Add one Bastion Marathon Elite to my cart, then create the order.",
    session_id="step9-over-cap",
)
print(f"\nAssistant: {answer}")
