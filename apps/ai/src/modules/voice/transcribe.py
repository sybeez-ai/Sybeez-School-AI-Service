"""Speech-to-text for the dictate mic. Gemini, not Qwen ASR.

qwen3-asr-flash returns 403 for the production DashScope key. Chat stays on
qwen3.8-flash. Audio bytes and API keys are never logged.
"""

from __future__ import annotations

import base64
import json
import logging
import re

import httpx

from src.core.config import get_settings
from src.core.exceptions import AppError, UpstreamError
from src.modules.usage.tokens import TokenUsage

logger = logging.getLogger("sybeez.ai.voice.transcribe")

_TRANSCRIBE_PROMPT = (
    'Transcribe the speech in this audio. Reply with only a JSON object '
    '{"text": "<words spoken>", "language": "<short code>"}. '
    "language is the language being spoken, a short code such as en, hi, ta, te, ml, kn, bn, mr, gu, pa, or ur. "
    "If there is no speech, set text to an empty string and language to en."
)

_LANGUAGE_NAMES = {
    "english": "en",
    "hindi": "hi",
    "tamil": "ta",
    "telugu": "te",
    "malayalam": "ml",
    "kannada": "kn",
    "bengali": "bn",
    "marathi": "mr",
    "gujarati": "gu",
    "punjabi": "pa",
    "urdu": "ur",
}

_SCRIPTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\u0B80-\u0BFF]"), "ta"),
    (re.compile(r"[\u0C00-\u0C7F]"), "te"),
    (re.compile(r"[\u0C80-\u0CFF]"), "kn"),
    (re.compile(r"[\u0D00-\u0D7F]"), "ml"),
    (re.compile(r"[\u0980-\u09FF]"), "bn"),
    (re.compile(r"[\u0A80-\u0AFF]"), "gu"),
    (re.compile(r"[\u0A00-\u0A7F]"), "pa"),
    (re.compile(r"[\u0900-\u097F]"), "hi"),
    (re.compile(r"[\u0600-\u06FF]"), "ur"),
)


def detect_language(text: str) -> str:
    for pattern, code in _SCRIPTS:
        if pattern.search(text or ""):
            return code
    return "en"


def language_code(value: str, text: str) -> str:
    raw = (value or "").strip().lower().replace("_", "-")
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    if re.fullmatch(r"[a-z]{2,3}", raw):
        return raw
    if raw in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[raw]
    return detect_language(text)


def audio_mime(value: str | None) -> str:
    raw = (value or "audio/webm").split(";", 1)[0].strip().lower()
    if raw in {"video/webm", "application/octet-stream", ""}:
        return "audio/webm"
    if raw.startswith("audio/"):
        return raw
    return "audio/webm"


def parse_transcript(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "text" in data:
            spoken = str(data.get("text") or "").strip()
            return spoken, language_code(str(data.get("language") or ""), spoken)
    spoken = text
    return spoken, detect_language(spoken)


VOICE_CREDIT_MESSAGE = (
    "Voice credit needed. Gemini prepaid credits are depleted. "
    "Top up the AI Studio project at https://ai.studio/projects, then try again."
)


async def transcribe_audio(audio: bytes, mime: str | None) -> tuple[str, str, TokenUsage]:
    """Gemini file transcription. The Qwen ASR model is not called."""
    if not audio:
        raise AppError("Audio is empty", code="empty_audio", status_code=400)
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AppError(VOICE_CREDIT_MESSAGE, code="gemini_credits_depleted", status_code=402)
    return await _gemini(settings, audio, audio_mime(mime))


async def _gemini(settings, audio: bytes, mime: str) -> tuple[str, str, TokenUsage]:
    from src.modules.usage.tokens import usage_from_provider

    model = settings.gemini_transcribe_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": _TRANSCRIBE_PROMPT},
                    {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode("ascii")}},
                ]
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(url, json=body, headers={"x-goog-api-key": settings.gemini_api_key})
    except httpx.HTTPError as exc:
        logger.warning("gemini transcription failed: %s", type(exc).__name__)
        raise UpstreamError("Could not transcribe the audio") from None
    if response.status_code == 402:
        logger.warning("gemini transcription rejected: status=402")
        raise AppError(VOICE_CREDIT_MESSAGE, code="gemini_credits_depleted", status_code=402)
    if response.status_code >= 400:
        logger.warning("gemini transcription rejected: status=%s", response.status_code)
        raise UpstreamError("Could not transcribe the audio")
    try:
        payload = response.json()
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("gemini transcription response was not usable")
        raise UpstreamError("Could not transcribe the audio") from None
    text, language = parse_transcript(str(raw))
    # Live models do not accept generateContent uploads. The HTTP call stays on
    # gemini_transcribe_model. The stored row is Gemini 3.8 Live, which is the
    # only Gemini column on the AI page, and the counts are the response's usageMetadata.
    usage = usage_from_provider(
        payload,
        prompt=_TRANSCRIBE_PROMPT,
        reply=text,
        model=settings.gemini_live_model,
        provider="gemini",
    )
    return text, language, usage

