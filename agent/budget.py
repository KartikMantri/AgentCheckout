"""
Per-provider token tracking, in-process. Honest caveat: real provider
limits are per-minute windows; this is a cumulative counter for the
life of the process, which is a simplification, not a real sliding
window. It's still enough to do the thing that actually matters —
route away from a provider that's clearly getting expensive *before*
burning a request to discover a 429, rather than after (§5.2).
"""

from collections import defaultdict

import config

_usage: dict[str, dict] = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0})


def record(provider: str, usage) -> None:
    if usage is None:
        return
    entry = _usage[provider]
    entry["prompt_tokens"] += getattr(usage, "prompt_tokens", 0)
    entry["completion_tokens"] += getattr(usage, "completion_tokens", 0)
    entry["total_tokens"] += getattr(usage, "total_tokens", 0)
    entry["requests"] += 1


def status(provider: str) -> dict:
    return dict(_usage[provider])


def is_near_cap(provider: str) -> bool:
    limit = config.PROVIDER_TOKEN_BUDGET.get(provider)
    if limit is None:
        return False
    return _usage[provider]["total_tokens"] >= limit * config.BUDGET_PREEMPT_THRESHOLD


def reset() -> None:
    _usage.clear()
