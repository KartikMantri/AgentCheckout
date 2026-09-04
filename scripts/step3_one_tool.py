"""
Step 3 — one tool, one call. The model asks; we execute; we print the
raw result. No feedback loop yet (that's Step 4) — this script stops
the instant we see what the model requested.

Run: .venv\\Scripts\\python.exe scripts\\step3_one_tool.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from openai import OpenAI

from config import PROVIDERS
from domain.catalog import init_db, search
from tools.definitions import SEARCH_CATALOG

load_dotenv()
init_db()

groq = PROVIDERS["groq"]
client = OpenAI(base_url=groq["base_url"], api_key=os.getenv(groq["key_env"]))

question = "Do you have flat-foot running shoes under 3000 rupees in stock right now?"

response = client.chat.completions.create(
    model=groq["models"]["fast"],
    messages=[{"role": "user", "content": question}],
    tools=[SEARCH_CATALOG],
    max_tokens=300,
)

message = response.choices[0].message
print(f"Q: {question}\n")

if message.tool_calls:
    call = message.tool_calls[0]
    args = json.loads(call.function.arguments)
    print(f"Model requested a tool call instead of answering directly:")
    print(f"  {call.function.name}({args})\n")

    result = search(**args)
    print(f"We executed it against the real catalog. Result:")
    for r in result:
        print(f"  {r['id']}  {r['name']:<28} ₹{r['price']:<6} stock={r['stock']}")
else:
    print(f"Model answered directly, no tool call:\n  {message.content}")
