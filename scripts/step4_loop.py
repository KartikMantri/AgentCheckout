"""
Step 4 — the loop. Watch the model chain two tools on its own: search,
then decide which result to add to the cart, with no scripted sequence.

Run: .venv\\Scripts\\python.exe scripts\\step4_loop.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from agent.loop import run
from domain.cart import get_cart, init_cart_tables
from domain.catalog import init_db

load_dotenv()
init_db()
init_cart_tables()

prompt = "Find me flat-foot running shoes under 3000 and add the best one to my cart."

print(f"User: {prompt}\n")
answer, cart_id = run(prompt)

print(f"\nAssistant: {answer}\n")
print(f"Final cart ({cart_id}):")
print(get_cart(cart_id))
