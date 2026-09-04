"""
All tunables live here. Nothing in agent/, tools/, or guardrails/ should
ever hardcode a model id, a URL, or a business limit — if you find yourself
typing a number that affects money or a string that names a model anywhere
else, it belongs in this file instead.
"""

# Verified against each provider's live docs on 2026-08-28 — re-check before
# a demo if this file is more than a few days old (providers deprecate fast).
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "models": {
            "fast": "openai/gpt-oss-20b",
            "strong": "openai/gpt-oss-120b",
        },
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "models": {
            "fast": "gemini-3.5-flash-lite",
            "strong": "gemini-3.7-flash",
        },
    },
}

# task_type -> ordered [(provider, model_tier), ...]. The router tries
# each in order; the loop never knows which one actually answered.
CHAINS = {
    "routing":    [("groq", "fast"), ("gemini", "fast")],
    "extraction": [("groq", "strong"), ("gemini", "strong")],
    # judgment was originally Gemini-primary per the PRD's reasoning
    # (strongest available model on the one task where judgment quality
    # matters most). Swapped to Groq-primary after live testing showed
    # gemini-3.7-flash's free tier allows only 20 requests/DAY (not per
    # minute) — nowhere near enough to serve as any task's primary.
    # Gemini stays in the chain as a real fallback; see notes/build_log.md.
    "judgment":   [("groq", "strong"), ("gemini", "strong")],
    "summarise":  [("groq", "fast"), ("gemini", "fast")],
}

# Loop bounds (GR7, GR8) — never hardcode these elsewhere.
MAX_LOOP_ITERATIONS = 8
MAX_VALIDATION_RETRIES = 2

# Business limits (GR1, GR2, GR3) — the entire discount/order-value
# story in the pitch depends on these living here and nowhere else.
MAX_AUTO_DISCOUNT_PCT = 10
MAX_DISCOUNTS_PER_ORDER = 1
MAX_AUTO_ORDER_VALUE = 5000

# Used to build a real, clickable payment link that any LLM interface
# (MCP, Claude Desktop, chat) can hand back to the customer — none of
# them can open a browser window themselves, but a real URL to the
# real Razorpay Checkout is the safe equivalent. Set PUBLIC_BASE_URL
# once this is deployed; defaults to localhost for local dev/demo.
import os as _os
PUBLIC_BASE_URL = _os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")

# History trimming — keep the most recent N conversational turns plus
# the system prompt. Never trim mid-turn (see agent/history.py).
MAX_HISTORY_TURNS = 6

# Per-provider budget tracking. Verified free-tier TPM as of 2026-08-28
# (Groq: 250K TPM for gpt-oss — much higher than the PRD's original
# planning assumption of 6K TPM; re-verify before a demo regardless).
# This is a simplified cumulative counter, not a real per-minute
# window — see agent/budget.py's docstring.
PROVIDER_TOKEN_BUDGET = {
    "groq": 250_000,
    "gemini": 100_000,  # conservative placeholder — Gemini's free-tier window wasn't verified live
}
BUDGET_PREEMPT_THRESHOLD = 0.8
