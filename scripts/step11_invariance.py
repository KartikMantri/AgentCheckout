"""
Step 11 — M7 (provider-invariance) and M8 (failover survival), for real.

M7: force S9-S12 (the adversarial discount attempts) through each
provider individually, one at a time, and compare verdicts. This is
the empirical version of "safety doesn't depend on model quality."

M8: run all 12 scenarios with Groq's key intentionally broken, and see
how many still complete correctly via Gemini alone.

Run: .venv\\Scripts\\python.exe scripts\\step11_invariance.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import config
from domain.cart import init_cart_tables
from domain.catalog import init_db
from domain.orders import init_order_tables
from tests.scenarios import SCENARIOS, run_scenarios

init_db()
init_cart_tables()
init_order_tables()

ADVERSARIAL_IDS = {s["id"] for s in SCENARIOS if s["category"] == "adversarial"}


def run_forced_through(provider_name: str) -> list[dict]:
    original = copy.deepcopy(config.CHAINS)
    for task_type in config.CHAINS:
        config.CHAINS[task_type] = [(provider_name, "strong")]
    try:
        results = run_scenarios(verbose=False)
    finally:
        config.CHAINS.clear()
        config.CHAINS.update(original)
    return [r for r in results if r["id"] in ADVERSARIAL_IDS]


print("=" * 70)
print("M7 — provider invariance: S9-S12 forced through each provider")
print("=" * 70)

by_provider = {}
for provider in ("groq", "gemini"):
    print(f"\n--- forced through {provider} only ---")
    results = run_forced_through(provider)
    by_provider[provider] = {r["id"]: r for r in results}
    for r in results:
        print(f"  {r['id']}: passed={r['passed']}  escalated={r['escalated']}  answer={r['final_answer']!r}")

print("\nCross-provider verdict comparison:")
all_match = True
for sid in sorted(ADVERSARIAL_IDS):
    passed_by_provider = {p: by_provider[p][sid]["passed"] for p in by_provider}
    match = len(set(passed_by_provider.values())) == 1
    all_match = all_match and match
    print(f"  {sid}: {passed_by_provider}  {'MATCH' if match else 'MISMATCH'}")

print(f"\nM7 result: {'100% identical guardrail verdicts across both providers' if all_match else 'MISMATCH FOUND — see above, do not claim M7 until resolved'}")

print("\n" + "=" * 70)
print("M8 — failover survival: all 12 scenarios with Groq forced down")
print("=" * 70)

real_key = os.environ.get("GROQ_API_KEY")
os.environ["GROQ_API_KEY"] = "gsk_intentionally_broken_for_m8"
try:
    m8_results = run_scenarios(verbose=False)
finally:
    os.environ["GROQ_API_KEY"] = real_key

m8_passed = sum(r["passed"] for r in m8_results)
m8_total = len(m8_results)
print(f"\n{m8_passed}/{m8_total} scenarios completed correctly with Groq entirely unavailable "
      f"({m8_passed / m8_total * 100:.0f}%)")
for r in m8_results:
    status = "PASS" if r["passed"] else "FAIL"
    print(f"  [{status}] {r['id']} ({r['category']})")
