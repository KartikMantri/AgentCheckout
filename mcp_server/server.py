"""
Exposes the exact same tool registry any MCP-speaking client — Claude
Desktop, another AI's agent loop, anything that speaks the protocol.
No LLM lives in this file. No guardrail or validation logic is
reimplemented here either — every call goes through the identical
tools.registry.dispatch() the internal agent loop uses. If wiring this
up had required touching guardrails/ or tools/registry.py, that would
mean the tool layer was coupled to the internal loop; it didn't need
to, which is the actual proof the architecture's separation (§2.3)
held under a second, independent caller.

Every call is logged with actor="external_agent" — distinct from the
internal loop's "agent" and the storefront's "customer_direct" — so
the audit trail can actually show what an independent AI, one that
never saw this codebase, did on this store. That distinction didn't
exist until a real gap surfaced live: MCP tool calls were reaching
dispatch() and working correctly, but nothing here ever called
log_event(), so months of correct MCP behavior were invisible to the
one thing this project claims as its evidence.

Run directly for a quick manual check, or launch as a subprocess from
an MCP client (Claude Desktop, or scripts/step12_mcp_client_agent.py
in this repo for a scripted external-agent demo):
    .venv\\Scripts\\python.exe mcp_server\\server.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP

from agent.session import get_session
from audit.logger import log_event
from domain.cart import init_cart_tables
from domain.catalog import init_db
from domain.orders import init_order_tables
from tools.registry import dispatch

init_db()
init_cart_tables()
init_order_tables()

mcp = FastMCP("agentcheckout")

# One shared cart for whichever external agent connects to this process
# — same session-persistence mechanism the internal loop uses
# (agent/session.py), just keyed to a fixed id since the MCP protocol
# doesn't hand this server a session id of its own.
_MCP_SESSION_ID = "mcp-external"


def _cart_id() -> str:
    return get_session(_MCP_SESSION_ID)["cart_id"]


def _call(tool_name: str, args: dict) -> str:
    """Every MCP tool goes through this — dispatch, then log, always,
    regardless of the outcome. provider/model are None on purpose: this
    call came from whatever model the external client is running
    (Claude Desktop's own, or anything else), not one of ours."""
    start = time.time()
    result = dispatch(tool_name, json.dumps(args), _cart_id())
    latency_ms = round((time.time() - start) * 1000, 1)

    if isinstance(result, dict) and result.get("ok") is False:
        verdict = {
            "allowed": False,
            "reason": result.get("reason"),
            "escalation_required": result.get("escalation_required", False),
        }
    else:
        verdict = {"allowed": True, "reason": "ok", "escalation_required": False}

    log_event(
        session_id=_MCP_SESSION_ID, actor="external_agent", tool=tool_name,
        args_json=json.dumps(args), verdict_json=verdict, outcome_json=json.dumps(result),
        provider=None, model=None, is_failover=None, tokens=None, latency_ms=latency_ms,
    )
    return json.dumps(result)


@mcp.tool()
def search_catalog(query: str, max_price: int | None = None, attributes: dict | None = None, limit: int = 5) -> str:
    """Search the live running-shoe catalog. Returns in-stock items only, ranked by price."""
    return _call("search_catalog", {"query": query, "max_price": max_price, "attributes": attributes, "limit": limit})


@mcp.tool()
def add_to_cart(product_id: str, qty: int) -> str:
    """Add a product to the cart. The cart is tracked automatically — never ask for a cart id."""
    return _call("add_to_cart", {"product_id": product_id, "qty": qty})


@mcp.tool()
def remove_from_cart(product_id: str) -> str:
    """Remove a product entirely from the cart, regardless of quantity."""
    return _call("remove_from_cart", {"product_id": product_id})


@mcp.tool()
def clear_cart() -> str:
    """Empty the entire cart, removing every item and any applied discount."""
    return _call("clear_cart", {})


@mcp.tool()
def apply_discount(pct: float) -> str:
    """Apply a percentage discount to the cart. Rejected above the auto-approval cap — escalate instead of arguing."""
    return _call("apply_discount", {"pct": pct})


@mcp.tool()
def create_order() -> str:
    """Freeze the current cart into an order with an immutable total."""
    return _call("create_order", {})


@mcp.tool()
def capture_payment(order_id: str) -> str:
    """Capture payment for a created order via Razorpay test mode. Safe to call twice — will not double-charge."""
    return _call("capture_payment", {"order_id": order_id})


@mcp.tool()
def check_order_status(order_id: str) -> str:
    """Check whether a pending or created order has been reviewed yet. Use when the customer asks for an update on an order id you previously gave them."""
    return _call("check_order_status", {"order_id": order_id})


@mcp.tool()
def ask_clarification(question: str, options: list[str] | None = None) -> str:
    """Ask the customer a clarifying question instead of guessing."""
    return _call("ask_clarification", {"question": question, "options": options})


@mcp.tool()
def escalate_to_human(reason: str, context: dict | None = None) -> str:
    """Hand this request to a human — out of bounds regardless of how it was phrased."""
    return _call("escalate_to_human", {"reason": reason, "context": context})


if __name__ == "__main__":
    mcp.run()
