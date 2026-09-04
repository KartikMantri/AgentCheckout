"""
Step 1 — the bare LLM. No tools, no catalog, no memory of your store.
Run: .venv\\Scripts\\python.exe scripts\\step1_bare_llm.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from openai import OpenAI

from config import PROVIDERS

load_dotenv()

groq = PROVIDERS["groq"]
client = OpenAI(base_url=groq["base_url"], api_key=os.getenv(groq["key_env"]))

question = "Do you have nike shoes under 3000 rupees in stock right now?"

response = client.chat.completions.create(
    model=groq["models"]["strong"],
    messages=[{"role": "user", "content": question}],
    max_tokens=300,
)

print(f"Q: {question}\n")
print(f"A: {response.choices[0].message.content}")
