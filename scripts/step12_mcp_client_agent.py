"""
Step 12, part 2 — an external agent, unscripted at runtime, discovers
this store's tools purely over MCP and completes a purchase from a
natural-language prompt. This script contains ZERO imports from
tools/, guardrails/, or domain/ — everything it knows about the store
comes from session.list_tools() over the wire. That's the actual proof
of "any AI can plug in," not just "our own loop works."

Ideally this runs on a DIFFERENT vendor than whatever serves the
internal-loop demos, to make the heterogeneity visible (§3.8). Forced
onto Groq today only because Gemini's free-tier daily quota (20
requests/day) is already spent from Step 11's testing — see
notes/build_log.md. Swap FORCED_PROVIDER to "gemini" once quota resets
for a truer demo of provider heterogeneity.

Run: .venv\\Scripts\\python.exe scripts\\step12_mcp_client_agent.py "<your prompt>"
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv()

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config
from agent.router import call as router_call

PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SERVER_SCRIPT = os.path.join(ROOT, "mcp_server", "server.py")

FORCED_PROVIDER = "groq"  # see docstring — swap to "gemini" once its daily quota resets
MAX_ITERATIONS = 8

SYSTEM_PROMPT = (
    "You are an external shopping agent with no built-in knowledge of this "
    "store. Everything you know about it comes from the tools available to "
    "you over MCP. Use them to fulfil the customer's request end to end."
)


def mcp_tools_to_openai_schema(mcp_tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema},
        }
        for t in mcp_tools
    ]


async def main(user_prompt: str):
    print(f"External agent prompt (unscripted): {user_prompt!r}\n")
    server_params = StdioServerParameters(command=PYTHON, args=[SERVER_SCRIPT])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_response = await session.list_tools()
            print(f"Discovered {len(tools_response.tools)} tools over MCP: "
                  f"{[t.name for t in tools_response.tools]}\n")
            openai_tools = mcp_tools_to_openai_schema(tools_response.tools)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            original_chain = config.CHAINS["extraction"]
            config.CHAINS["extraction"] = [(FORCED_PROVIDER, "strong")]

            try:
                for iteration in range(1, MAX_ITERATIONS + 1):
                    message, provider, meta = router_call("extraction", messages, tools=openai_tools)

                    if not message.tool_calls:
                        print(f"[turn {iteration}, served by {provider}] final answer:\n{message.content}")
                        return

                    messages.append({
                        "role": "assistant", "content": message.content,
                        "tool_calls": [tc.model_dump() for tc in message.tool_calls],
                    })

                    for tc in message.tool_calls:
                        args = json.loads(tc.function.arguments)
                        print(f"[turn {iteration}, served by {provider}] calling MCP tool: {tc.function.name}({args})")

                        mcp_result = await session.call_tool(tc.function.name, args)
                        result_text = mcp_result.content[0].text if mcp_result.content else "{}"
                        print(f"  -> {result_text}\n")

                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

                print("Hit iteration limit without a final answer.")
            finally:
                config.CHAINS["extraction"] = original_chain


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or (
        "Find me daily-use running shoes under 3000 rupees with flat arch support, "
        "add the cheapest one to my cart, create the order, and capture payment."
    )
    asyncio.run(main(prompt))
