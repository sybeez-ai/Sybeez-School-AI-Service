"""Speech on the DashScope account chat already uses.

qwen3-asr-flash on the multimodal endpoint returned 403 for the production key,
and the Gemini prepaid wallet returns 402. Dictate and voice try the
international DashScope shapes and models that key can call, then the China
host. Gemini is not called. Audio bytes and the API key are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from urllib.parse import urlparse

import httpx

from src.core.config import get_settings
from src.core.exceptions import UpstreamError
from src.modules.usage.tokens import TokenUsage, usage_from_provider
from src.modules.voice.transcribe import audio_mime, detect_language, parse_transcript

logger = logging.getLogger("sybeez.ai.voice.qwen")

_ASR_PROMPT = "Transcribe the speech. Reply with only the words spoken."
_INTL = "https://dashscope-intl.aliyuncs.com"
_CN = "https://dashscope.aliyuncs.com"

# name, url, model, shape. The known-403 multimodal qwen3-asr-flash call is last
# on each host so a working model is found first.
ASR_CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    ("intl-chat", f"{_INTL}/compatible-mode/v1/chat/completions", "qwen3-asr-flash", "chat"),
    ("intl-mm", f"{_INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen2-audio-instruct", "mm"),
    ("intl-mm", f"{_INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen-audio-turbo", "mm"),
    ("intl-chat", f"{_INTL}/compatible-mode/v1/chat/completions", "qwen2.5-omni-7b", "chat"),
    ("intl-chat", f"{_INTL}/compatible-mode/v1/chat/completions", "qwen-omni-turbo", "chat"),
    ("intl-mm", f"{_INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-asr-flash", "mm"),
    ("cn-chat", f"{_CN}/compatible-mode/v1/chat/completions", "qwen3-asr-flash", "chat"),
    ("cn-mm", f"{_CN}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-asr-flash", "mm"),
)

TTS_CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    ("intl-speech", f"{_INTL}/compatible-mode/v1/audio/speech", "qwen3-tts-flash", "speech"),
    ("intl-mm", f"{_INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-tts-flash", "tts"),
    ("intl-speech", f"{_INTL}/compatible-mode/v1/audio/speech", "qwen-tts", "speech"),
    ("cn-speech", f"{_CN}/compatible-mode/v1/audio/speech", "qwen3-tts-flash", "speech"),
    ("cn-mm", f"{_CN}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-tts-flash", "tts"),
)

_asr_winner: tuple[str, str, str, str] | None = None
_tts_winner: tuple[str, str, str, str] | None = None


def dashscope_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return _INTL
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_asr_text(payload: dict) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            message = (choice or {}).get("message") if isinstance(choice, dict) else None
            content = (message or {}).get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    str(part.get("text") or "").strip()
                    for part in content
                    if isinstance(part, dict) and str(part.get("text") or "").strip()
                ]
                if parts:
                    return " ".join(parts)
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    nested = output.get("choices") if isinstance(output, dict) else None
    if isinstance(nested, list):
        return parse_asr_text({"choices": nested})
    if isinstance(output, dict):
        for key in ("text", "sentence", "transcript"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
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


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    code = payload.get("code") or payload.get("error")
    if isinstance(code, dict):
        code = code.get("code") or code.get("message")
    return str(code or "")[:80]


async def _wav(audio: bytes, mime: str | None) -> bytes:
    kind = (mime or "").lower()
    if "wav" in kind:
        return audio
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await proc.communicate(audio)
    if proc.returncode != 0 or not out:
        logger.warning("ffmpeg could not prepare audio status=%s", proc.returncode)
        return audio
    return out


def _asr_body(model: str, shape: str, encoded: str) -> dict:
    if shape == "chat":
        return {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
                        {"type": "text", "text": _ASR_PROMPT},
                    ],
                }
            ],
        }
    return {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"audio": f"data:audio/wav;base64,{encoded}"}],
                }
            ]
        },
        "parameters": {"asr_options": {"enable_lid": True}},
    }


def _tts_body(model: str, shape: str, text: str) -> dict:
    if shape == "speech":
        return {"model": model, "input": text, "voice": "Cherry"}
    return {"model": model, "input": {"text": text, "voice": "Cherry", "language_type": "Auto"}}


def _ordered(candidates: tuple[tuple[str, str, str, str], ...], winner: tuple[str, str, str, str] | None):
    if winner is None or winner not in candidates:
        return candidates
    return (winner, *[item for item in candidates if item != winner])


async def _post(client: httpx.AsyncClient, url: str, key: str, body: dict) -> httpx.Response:
    return await client.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
    )


async def transcribe_qwen(audio: bytes, mime: str | None) -> tuple[str, str, TokenUsage]:
    global _asr_winner
    settings = get_settings()
    if not audio or not settings.qwen_chat_api_key:
        raise UpstreamError("Could not transcribe the audio")
    wav = await _wav(audio, audio_mime(mime))
    encoded = base64.b64encode(wav).decode("ascii")
    last_status = 0
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for name, url, model, shape in _ordered(ASR_CANDIDATES, _asr_winner):
                response = await _post(client, url, settings.qwen_chat_api_key, _asr_body(model, shape, encoded))
                last_status = response.status_code
                if response.status_code >= 400:
                    logger.warning(
                        "dashscope asr rejected model=%s shape=%s host=%s status=%s code=%s",
                        model,
                        shape,
                        name,
                        response.status_code,
                        _error_code(response),
                    )
                    if _asr_winner == (name, url, model, shape):
                        _asr_winner = None
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    logger.warning("dashscope asr response was not json model=%s", model)
                    continue
                if not isinstance(payload, dict):
                    continue
                spoken = parse_asr_text(payload)
                if not spoken.strip():
                    logger.warning("dashscope asr returned no words model=%s shape=%s host=%s", model, shape, name)
                    continue
                _asr_winner = (name, url, model, shape)
                text, language = parse_transcript(spoken)
                if language == "en":
                    language = detect_language(text)
                usage = usage_from_provider(
                    payload,
                    prompt=_ASR_PROMPT,
                    reply=text,
                    model=model,
                    provider="qwen",
                )
                return text, language, usage
    except httpx.HTTPError as exc:
        logger.warning("dashscope asr failed: %s", type(exc).__name__)
        raise UpstreamError("Could not transcribe the audio") from None
    logger.warning("dashscope asr unavailable status=%s", last_status)
    raise UpstreamError("Could not transcribe the audio")


async def _fetch_audio(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    host = urlparse(url).netloc
    if not host.endswith("aliyuncs.com") and "dashscope" not in host:
        return None
    fetched = await client.get(url)
    if fetched.status_code >= 400 or not fetched.content:
        return None
    kind = fetched.headers.get("content-type", "audio/mpeg").split(";")[0]
    return fetched.content, kind or "audio/mpeg"


async def synthesize_qwen(text: str) -> tuple[bytes, str] | None:
    global _tts_winner
    settings = get_settings()
    spoken = " ".join((text or "").split())[:600]
    if not spoken or not settings.qwen_chat_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for name, url, model, shape in _ordered(TTS_CANDIDATES, _tts_winner):
                response = await _post(client, url, settings.qwen_chat_api_key, _tts_body(model, shape, spoken))
                if response.status_code >= 400:
                    logger.warning(
                        "dashscope tts rejected model=%s shape=%s host=%s status=%s code=%s",
                        model,
                        shape,
                        name,
                        response.status_code,
                        _error_code(response),
                    )
                    if _tts_winner == (name, url, model, shape):
                        _tts_winner = None
                    continue
                content_type = response.headers.get("content-type", "")
                if "audio" in content_type or "octet-stream" in content_type:
                    if response.content:
                        _tts_winner = (name, url, model, shape)
                        return response.content, content_type.split(";")[0] or "audio/mpeg"
                try:
                    payload = response.json()
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                inline = parse_tts_audio(payload)
                if inline:
                    _tts_winner = (name, url, model, shape)
                    return inline
                audio_url = tts_audio_url(payload)
                if not audio_url:
                    logger.warning("dashscope tts returned no audio model=%s shape=%s", model, shape)
                    continue
                fetched = await _fetch_audio(client, audio_url)
                if fetched:
                    _tts_winner = (name, url, model, shape)
                    return fetched
    except httpx.HTTPError:
        logger.warning("dashscope tts failed")
        return None
    return None
