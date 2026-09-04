"""
The router: call(task_type, messages, tools) -> (message, provider_name, meta).

This is the only file in the project allowed to know provider names
exist. The agent loop calls this and nothing else — it never sees
"groq" or "gemini" as strings except to log them.

meta carries what the audit trail needs (FR30): which model served the
call, whether it was a failover, latency, and token usage.
"""

import time

from openai import RateLimitError

from agent import budget
from agent.providers.base import ProviderClient
from config import CHAINS, PROVIDERS

BACKOFF_SECONDS = 1.5


class RouterExhausted(Exception):
    """Every provider in the chain failed, was unavailable, or was skipped."""


def call(task_type: str, messages: list[dict], tools: list[dict] | None = None,
         max_tokens: int = 600, log=None):
    chain = CHAINS[task_type]
    last_error = None

    for i, (provider_name, model_tier) in enumerate(chain):
        is_last = i == len(chain) - 1
        if budget.is_near_cap(provider_name) and not is_last:
            # Never pre-emptively skip the LAST remaining option — a real
            # 429 (with a real retry-after) is more honest than declaring
            # RouterExhausted before even trying. Learned the hard way:
            # skipping the last provider on a soft budget guess turned a
            # recoverable situation into a hard failure. See build_log.md.
            if log:
                log(provider=provider_name, task_type=task_type, event="skipped_near_cap",
                    usage=budget.status(provider_name))
            continue

        client = ProviderClient(provider_name, PROVIDERS[provider_name])
        if not client.available:
            if log:
                log(provider=provider_name, task_type=task_type, event="skipped_no_key")
            continue

        start = time.time()
        try:
            response = client.chat(model_tier, messages, tools, max_tokens)
        except RateLimitError:
            if log:
                log(provider=provider_name, task_type=task_type, event="rate_limited_backoff",
                    wait_seconds=BACKOFF_SECONDS)
            time.sleep(BACKOFF_SECONDS)
            try:
                response = client.chat(model_tier, messages, tools, max_tokens)
            except Exception as exc2:
                last_error = exc2
                if log:
                    log(provider=provider_name, task_type=task_type, event="failover",
                        error=f"{type(exc2).__name__}: {exc2}")
                continue
        except Exception as exc:
            last_error = exc
            if log:
                log(provider=provider_name, task_type=task_type, event="failover",
                    error=f"{type(exc).__name__}: {exc}")
            continue

        latency_ms = round((time.time() - start) * 1000, 1)
        usage = getattr(response, "usage", None)
        budget.record(provider_name, usage)

        meta = {
            "provider": provider_name,
            "model": PROVIDERS[provider_name]["models"][model_tier],
            "is_failover": i > 0,
            "latency_ms": latency_ms,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }

        if log:
            log(task_type=task_type, event="served", **meta)
        return response.choices[0].message, provider_name, meta

    raise RouterExhausted(f"All providers exhausted for task_type={task_type!r}: {last_error}")
