"""
Step 13 — failure demo: an item goes out of stock mid-conversation.

SKU-112 (Ridge Stability Pro Wide) starts with stock=2, priced under
the order-value cap so a real purchase can complete. Two separate
conversations each buy the last unit; a third tries to buy what's now
sold out and has to recover cleanly — no crash, no stale "yes we have
it," a structured rejection the model can act on.

Run: .venv\\Scripts\\python.exe scripts\\step13_failure_demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from agent.loop import run
from domain.cart import init_cart_tables
from domain.catalog import get_by_id, init_db
from domain.orders import init_order_tables

init_db()
init_cart_tables()
init_order_tables()

SKU = "SKU-112"

print("=" * 70)
print(f"Starting stock for {SKU}: {get_by_id(SKU)['stock']}")
print("=" * 70)

for i in (1, 2):
    print(f"\n--- Customer {i} buys the last-but-{2 - i} unit ---")
    answer, _ = run(
        f"Add one Ridge Stability Pro Wide to my cart, create the order, and capture payment.",
        session_id=f"failure-demo-buyer-{i}",
        verbose=False,
    )
    print(f"Assistant: {answer}")
    print(f"Stock remaining: {get_by_id(SKU)['stock']}")

print("\n" + "=" * 70)
print("--- Customer 3 tries to buy the same shoe, now sold out ---")
print("=" * 70)
answer, _ = run(
    "Add one Ridge Stability Pro Wide to my cart.",
    session_id="failure-demo-buyer-3",
    verbose=True,
)
print(f"\nAssistant: {answer}")
print(f"\nFinal stock: {get_by_id(SKU)['stock']}")
