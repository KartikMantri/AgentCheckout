"""
Conversation + cart state, keyed by session_id. This is the entire fix
for "the model doesn't remember" — there is no memory mechanism beyond
"we kept the list and send it again." That's the whole trick (§3.5).

In-process dict, gone on restart — fine for a demo. A real deployment
would put this in the same SQLite file everything else lives in.
"""

from agent.prompts import SYSTEM_PROMPT
from domain.cart import create_cart

_SESSIONS: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "cart_id": create_cart(session_id),
        }
    return _SESSIONS[session_id]


def reset_session(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)
