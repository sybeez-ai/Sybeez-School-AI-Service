import json
import logging
from collections.abc import AsyncIterator

import httpx

from src.core.config import get_settings
from src.core.exceptions import UpstreamError
from src.providers.base import LLMProvider

logger = logging.getLogger("sybeez.ai.llm")


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


def _extra_body(url: str) -> dict:
    """DashScope models think by default (slow first token); chat/practice want the direct answer."""
    return {"enable_thinking": False} if "dashscope" in url else {}


class CompatibleChatLLM(LLMProvider):
    """OpenAI-compatible chat API (DeepSeek, Qwen, OpenAI) with provider failover."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.candidates = self.settings.chat_candidates() or [
            (self.settings.chat_provider, self.settings.active_chat_api_key,
             self.settings.active_chat_base_url, self.settings.active_chat_model)
        ]
        _, self.api_key, base_url, self.model = self.candidates[0]
        self.base_url = base_url.rstrip("/")

    def _timeout(self) -> httpx.Timeout:
        settings = self.settings
        return httpx.Timeout(settings.llm_timeout_seconds, connect=settings.upstream_timeout_seconds)

    @staticmethod
    def _log_failure(kind: str, provider: str, exc: httpx.HTTPError) -> None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("llm %s failed: %s status=%s provider=%s", kind, type(exc).__name__, status, provider)

    def _targets(self):
        if self.candidates and self.candidates[0][2].rstrip("/") == self.base_url:
            return [(p, k, u.rstrip("/"), m) for p, k, u, m in self.candidates]
        return [("custom", self.api_key, self.base_url, self.model)]

    async def complete(self, *, system: str, user: str) -> str:
        last: httpx.HTTPError | None = None
        for provider, key, url, model in self._targets():
            try:
                return await self._complete(key, url, model, system=system, user=user)
            except httpx.HTTPError as exc:
                # Network/DNS/auth/5xx: try the next provider; all failing is a 502, not a 500.
                self._log_failure("complete", provider, exc)
                last = exc
        raise UpstreamError("Language model request failed") from last

    async def _complete(self, key: str, url: str, model: str, *, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.4,
                    **_extra_body(url),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        last: httpx.HTTPError | None = None
        for provider, key, url, model in self._targets():
            started = False
            try:
                async for delta in self._stream(key, url, model, system=system, user=user):
                    started = True
                    yield delta
                return
            except httpx.HTTPError as exc:
                self._log_failure("stream", provider, exc)
                last = exc
                if started:
                    break
        raise UpstreamError("Language model request failed") from last

    async def _stream(self, key: str, url: str, model: str, *, system: str, user: str) -> AsyncIterator[str]:
        timeout = httpx.Timeout(self.settings.stream_timeout_seconds, connect=self.settings.upstream_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "stream": True,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.4,
                    **_extra_body(url),
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


async def guarded_complete(llm: LLMProvider, *, system: str, user: str) -> str:
    try:
        return await llm.complete(system=system, user=user)
    except UpstreamError:
        raise
    except Exception as exc:
        logger.exception("llm complete failed")
        raise UpstreamError("Language model request failed") from exc
