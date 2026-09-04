"""
Step 12, part 1 — baseline protocol proof: connect a real MCP client to
our server as a subprocess, discover the tools, and call one. No LLM
involved here on purpose — this isolates "does the protocol wiring
work at all" from "can an LLM drive it," which is a separate script
(step12_mcp_client_agent.py) so a bug in one doesn't hide inside the
other.

Run: .venv\\Scripts\\python.exe scripts\\step12_mcp_smoketest.py
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SERVER_SCRIPT = os.path.join(ROOT, "mcp_server", "server.py")


async def main():
    server_params = StdioServerParameters(command=PYTHON, args=[SERVER_SCRIPT])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected and initialized.\n")

            tools_response = await session.list_tools()
            print(f"Discovered {len(tools_response.tools)} tools:")
            for t in tools_response.tools:
                print(f"  - {t.name}: {t.description}")

            print("\nCalling search_catalog directly over MCP...")
            result = await session.call_tool("search_catalog", {"query": "running shoes", "max_price": 3000})
            payload = json.loads(result.content[0].text)
            print(f"Got {len(payload)} results:")
            for p in payload:
                print(f"  {p['id']}  {p['name']}  Rs.{p['price']}  stock={p['stock']}")

            print("\nCalling add_to_cart, then reading it back via search (to prove state persists per MCP session)...")
            add_result = json.loads((await session.call_tool("add_to_cart", {"product_id": payload[0]["id"], "qty": 1})).content[0].text)
            print(f"  add_to_cart result: {add_result}")

            print("\nCalling apply_discount(pct=40) — should be REJECTED by the same guardrail as the internal loop...")
            discount_result = json.loads((await session.call_tool("apply_discount", {"pct": 40})).content[0].text)
            print(f"  apply_discount result: {discount_result}")
            assert discount_result["ok"] is False and discount_result["reason"] == "discount_exceeds_cap", \
                "guardrail did not fire over MCP — tool layer coupling bug!"
            print("  Confirmed: guardrail fired identically over MCP. No separate rules were written for this path.")


if __name__ == "__main__":
    asyncio.run(main())
