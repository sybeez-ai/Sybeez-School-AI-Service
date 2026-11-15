"""Speech on the same DashScope account chat already uses.

Gemini Live bills a separate AI Studio prepaid key (GEMINI_API_KEY). These
calls use QWEN_API_KEY / QWEN_CHAT_API_KEY and do not touch that key.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import httpx

from src.core.config import get_settings
from src.core.exceptions import UpstreamError
from src.modules.usage.tokens import TokenUsage, usage_from_provider
from src.modules.voice.transcribe import audio_mime, parse_transcript

logger = logging.getLogger("sybeez.ai.voice.qwen")

_ASR_PROMPT = "Transcribe the speech. Reply with only the words spoken."


def dashscope_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return "https://dashscope-intl.aliyuncs.com"
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_asr_text(payload: dict) -> str:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    choices = output.get("choices") if isinstance(output, dict) else None
    if isinstance(choices, list):
        for choice in choices:
            message = (choice or {}).get("message") if isinstance(choice, dict) else None
            content = (message or {}).get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and str(part.get("text") or "").strip():
                        parts.append(str(part["text"]).strip())
                if parts:
                    return " ".join(parts)
    if isinstance(payload.get("text"), str):
        return payload["text"].strip()
    return ""


def parse_tts_audio(payload: dict) -> tuple[bytes, str] | None:
    """Bytes already in the JSON body. A remote URL is fetched by the caller."""
    audio = payload.get("audio")
    if isinstance(audio, str) and audio:
        try:
            return base64.b64decode(audio), "audio/mpeg"
        except (ValueError, TypeError):
            return None
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    nested = output.get("audio") if isinstance(output, dict) else None
    if isinstance(nested, dict):
        encoded = nested.get("data") or nested.get("audio")
        if isinstance(encoded, str) and encoded and not encoded.startswith("http"):
            try:
                return base64.b64decode(encoded), str(nested.get("mime_type") or "audio/mpeg")
            except (ValueError, TypeError):
                return None
    return None


def tts_audio_url(payload: dict) -> str | None:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    nested = output.get("audio") if isinstance(output, dict) else None
    if isinstance(nested, dict):
        url = nested.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return url
    url = output.get("audio_url") if isinstance(output, dict) else None
    if isinstance(url, str) and url.startswith("https://"):
        return url
    return None


async def transcribe_qwen(audio: bytes, mime: str | None) -> tuple[str, str, TokenUsage]:
    settings = get_settings()
    if not audio or not settings.qwen_chat_api_key:
        raise UpstreamError("Could not transcribe the audio")
    kind = audio_mime(mime)
    encoded = base64.b64encode(audio).decode("ascii")
    url = f"{dashscope_root(settings.qwen_base_url)}/api/v1/services/aigc/multimodal-generation/generation"
    body = {
        "model": settings.qwen_asr_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"text": _ASR_PROMPT},
                        {"audio": f"data:{kind};base64,{encoded}"},
                    ],
                }
            ]
        },
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.qwen_chat_api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as exc:
        logger.warning("qwen asr failed: %s", type(exc).__name__)
        raise UpstreamError("Could not transcribe the audio") from None
    if response.status_code >= 400:
        logger.warning("qwen asr rejected status=%s", response.status_code)
        raise UpstreamError("Could not transcribe the audio")
    try:
        payload = response.json()
    except ValueError:
        raise UpstreamError("Could not transcribe the audio") from None
    spoken = parse_asr_text(payload if isinstance(payload, dict) else {})
    text, language = parse_transcript(spoken)
    usage = usage_from_provider(
        payload if isinstance(payload, dict) else None,
        prompt=_ASR_PROMPT,
        reply=text,
        model=settings.qwen_asr_model,
        provider="qwen",
    )
    return text, language, usage


async def synthesize_qwen(text: str) -> tuple[bytes, str] | None:
    settings = get_settings()
    spoken = " ".join((text or "").split())[:600]
    if not spoken or not settings.qwen_chat_api_key:
        return None
    url = f"{settings.qwen_base_url.rstrip('/')}/audio/speech"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.qwen_chat_api_key}"},
                json={"model": settings.qwen_tts_model, "input": spoken, "voice": "Cherry"},
            )
    except httpx.HTTPError:
        logger.warning("qwen tts failed")
        return None
    content_type = response.headers.get("content-type", "")
    if response.status_code < 400 and ("audio" in content_type or "octet-stream" in content_type):
        if response.content:
            return response.content, content_type.split(";")[0] or "audio/mpeg"
    if response.status_code >= 400:
        logger.warning("qwen tts rejected status=%s", response.status_code)
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    inline = parse_tts_audio(payload)
    if inline:
        return inline
    audio_url = tts_audio_url(payload)
    if not audio_url:
        return None
    host = urlparse(audio_url).netloc
    if not host.endswith("aliyuncs.com") and "dashscope" not in host:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            fetched = await client.get(audio_url)
    except httpx.HTTPError:
        return None
    if fetched.status_code >= 400 or not fetched.content:
        return None
    kind = fetched.headers.get("content-type", "audio/mpeg").split(";")[0]
    return fetched.content, kind or "audio/mpeg"
