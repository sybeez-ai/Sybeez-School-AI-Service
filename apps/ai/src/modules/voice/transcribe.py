"""Speech-to-text for dictate and voice. DashScope, not the browser and not Gemini.

Audio bytes are never logged.
"""

from __future__ import annotations

import json
import logging
import re

from src.core.exceptions import AppError
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


async def transcribe_audio(audio: bytes, mime: str | None) -> tuple[str, str, TokenUsage]:
    """DashScope first. Amazon Transcribe if that key cannot use a speech model. Gemini is not called."""
    if not audio:
        raise AppError("Audio is empty", code="empty_audio", status_code=400)
    from src.modules.usage.tokens import estimate_usage
    from src.modules.voice.qwen_audio import transcribe_qwen

    try:
        return await transcribe_qwen(audio, mime)
    except UpstreamError:
        logger.warning("dashscope transcription unavailable")
    from src.modules.voice.aws_speech import transcribe_clip

    spoken, named = await transcribe_clip(audio, mime)
    language = language_code(named, spoken)
    return spoken, language, estimate_usage(named or "speech", spoken, model="transcribe", provider="aws")

