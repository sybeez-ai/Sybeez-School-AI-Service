from collections.abc import AsyncIterator
import json

import httpx

from src.core.config import get_settings
from src.providers.base import LLMProvider


class EchoLLM(LLMProvider):
    """Dev fallback when no provider API key is set."""

    async def complete(self, *, system: str, user: str) -> str:
        return (
            "Let's make this simple.\n\n"
            "Based on what your teacher covered, here's a clear explanation.\n\n"
            f"You asked: {user[-400:]}\n\n"
            "The key idea is to connect the terms you already learned in class. "
            "If you want, I can give you a short practice question next."
        )

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        text = await self.complete(system=system, user=user)
        for word in text.split(" "):
            yield word + " "


class CompatibleChatLLM(LLMProvider):
    """OpenAI-compatible chat API (DeepSeek, Qwen, OpenAI)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key = self.settings.active_chat_api_key
        self.base_url = self.settings.active_chat_base_url.rstrip("/")
        self.model = self.settings.active_chat_model

    async def complete(self, *, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "stream": True,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.4,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta


def get_llm() -> LLMProvider:
    settings = get_settings()
    if settings.active_chat_api_key:
        return CompatibleChatLLM()
    return EchoLLM()
