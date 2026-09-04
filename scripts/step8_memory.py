"""
Step 8 — state, memory, budget. The real test: "add the second one"
only works if the previous turn's search results are still in the
conversation the model sees. Nothing here is new plumbing for that —
it's purely a consequence of session.py persisting `messages` across
calls to run() instead of starting fresh every time.

Run: .venv\\Scripts\\python.exe scripts\\step8_memory.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from agent import budget
from agent.loop import run
from domain.cart import get_cart, init_cart_tables
from domain.catalog import init_db

init_db()
init_cart_tables()

SESSION = "step8-demo"

turns = [
    "Show me flat-foot running shoes under 3000.",
    "Add the second one to my cart.",
    "What's in my cart right now, and what's the total?",
]

for i, prompt in enumerate(turns, 1):
    print(f"\n{'=' * 70}\nTurn {i}: {prompt}\n{'=' * 70}")
    answer, cart_id = run(prompt, session_id=SESSION, verbose=True)
    print(f"\nAssistant: {answer}")

print(f"\n{'=' * 70}\nFinal cart state (fetched directly from the DB, not the model): {get_cart(cart_id)}")

print(f"\n{'=' * 70}\nPer-provider token usage this run:")
for provider in ("groq", "gemini"):
    print(f"  {provider}: {budget.status(provider)}  near_cap={budget.is_near_cap(provider)}")
