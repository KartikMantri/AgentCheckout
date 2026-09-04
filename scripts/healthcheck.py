"""
Pings every provider in config.PROVIDERS with one bare "fast" model call.
Run this before you build anything else, and again on the morning you
record the demo video — providers deprecate models without warning.

Usage: python scripts/healthcheck.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from openai import OpenAI

from config import PROVIDERS

load_dotenv()


def check(name: str, cfg: dict) -> None:
    key = os.getenv(cfg["key_env"])
    if not key:
        print(f"  [SKIP]  {name:<10} — {cfg['key_env']} not set in .env")
        return

    client = OpenAI(base_url=cfg["base_url"], api_key=key)
    model = cfg["models"]["fast"]
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly one word: alive"}],
            max_tokens=120,
        )
        elapsed = (time.time() - start) * 1000
        text = resp.choices[0].message.content.strip()
        print(f"  [OK]    {name:<10} model={model:<24} {elapsed:.0f}ms  reply={text!r}")
    except Exception as exc:
        elapsed = (time.time() - start) * 1000
        print(f"  [FAIL]  {name:<10} model={model:<24} {elapsed:.0f}ms  {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print("AgentCheckout — provider healthcheck\n")
    for provider_name, provider_cfg in PROVIDERS.items():
        check(provider_name, provider_cfg)
    print("\nAll three should say [OK] before you move on.")
