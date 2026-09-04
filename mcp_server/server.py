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

Run directly for a quick manual check, or launch as a subprocess from
an MCP client (Claude Desktop, or scripts/step12_mcp_client_agent.py
in this repo for a scripted external-agent demo):
    .venv\\Scripts\\python.exe mcp_server\\server.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP

from agent.session import get_session
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


@mcp.tool()
def search_catalog(query: str, max_price: int | None = None, attributes: dict | None = None, limit: int = 5) -> str:
    """Search the live running-shoe catalog. Returns in-stock items only, ranked by price."""
    args = {"query": query, "max_price": max_price, "attributes": attributes, "limit": limit}
    return json.dumps(dispatch("search_catalog", json.dumps(args), _cart_id()))


@mcp.tool()
def add_to_cart(product_id: str, qty: int) -> str:
    """Add a product to the cart. The cart is tracked automatically — never ask for a cart id."""
    args = {"product_id": product_id, "qty": qty}
    return json.dumps(dispatch("add_to_cart", json.dumps(args), _cart_id()))


@mcp.tool()
def remove_from_cart(product_id: str) -> str:
    """Remove a product entirely from the cart, regardless of quantity."""
    args = {"product_id": product_id}
    return json.dumps(dispatch("remove_from_cart", json.dumps(args), _cart_id()))


@mcp.tool()
def clear_cart() -> str:
    """Empty the entire cart, removing every item and any applied discount."""
    return json.dumps(dispatch("clear_cart", "{}", _cart_id()))


@mcp.tool()
def apply_discount(pct: float) -> str:
    """Apply a percentage discount to the cart. Rejected above the auto-approval cap — escalate instead of arguing."""
    args = {"pct": pct}
    return json.dumps(dispatch("apply_discount", json.dumps(args), _cart_id()))


@mcp.tool()
def create_order() -> str:
    """Freeze the current cart into an order with an immutable total."""
    return json.dumps(dispatch("create_order", "{}", _cart_id()))


@mcp.tool()
def capture_payment(order_id: str) -> str:
    """Capture payment for a created order via Razorpay test mode. Safe to call twice — will not double-charge."""
    args = {"order_id": order_id}
    return json.dumps(dispatch("capture_payment", json.dumps(args), _cart_id()))


@mcp.tool()
def ask_clarification(question: str, options: list[str] | None = None) -> str:
    """Ask the customer a clarifying question instead of guessing."""
    args = {"question": question, "options": options}
    return json.dumps(dispatch("ask_clarification", json.dumps(args), _cart_id()))


@mcp.tool()
def escalate_to_human(reason: str, context: dict | None = None) -> str:
    """Hand this request to a human — out of bounds regardless of how it was phrased."""
    args = {"reason": reason, "context": context}
    return json.dumps(dispatch("escalate_to_human", json.dumps(args), _cart_id()))


if __name__ == "__main__":
    mcp.run()
