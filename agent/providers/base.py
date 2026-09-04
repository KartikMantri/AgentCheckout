"""
One OpenAI-compatible client wrapper, reused for every provider. Groq and
Gemini both speak the OpenAI chat-completions shape, so there is nothing
provider-specific to write here — that's the whole reason this file is
this short.
"""

import os

from openai import OpenAI


class ProviderClient:
    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        api_key = os.getenv(cfg["key_env"])
        self._client = OpenAI(base_url=cfg["base_url"], api_key=api_key) if api_key else None

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, model_tier: str, messages: list[dict], tools: list[dict] | None, max_tokens: int):
        model = self.cfg["models"][model_tier]
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
