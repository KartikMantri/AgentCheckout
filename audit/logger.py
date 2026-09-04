"""
Append-only JSONL. Never update a line, never delete one — this file
is the evidence, not a cache. One line per tool call: what was asked,
what the verdict was, what happened, which provider/model served it,
tokens, latency.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit_log.jsonl"


def log_event(**fields) -> dict:
    event = {
        "id": "AUD-" + uuid.uuid4().hex[:10],
        "ts": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event


def read_all() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
