"""
Step 5 — the router. Same request, forced through each provider, then
a forced Groq failure to prove the router recovers mid-conversation
without the loop knowing anything happened.

Run: .venv\\Scripts\\python.exe scripts\\step5_router.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from agent.router import call
from config import CHAINS

question = [{"role": "user", "content": "Say hello in exactly five words."}]


def log(**kw):
    print(f"  [router] {kw}")


print("=== normal call, task_type='routing' (should hit Groq first) ===")
message, provider, meta = call("routing", question, log=log)
print(f"served by: {provider}\nreply: {message.content}\n")

print("=== forcing Groq's key to fail (this process only, .env untouched) ===")
real_groq_key = os.environ.get("GROQ_API_KEY")
os.environ["GROQ_API_KEY"] = "gsk_intentionally_broken_for_step5"

message, provider, meta = call("routing", question, log=log)
print(f"served by: {provider}\nreply: {message.content}")
print("\n^ chain order was groq -> gemini; Groq failed, Gemini answered, nothing crashed.")

os.environ["GROQ_API_KEY"] = real_groq_key
print("\n(restored the real Groq key for the rest of the process)")
