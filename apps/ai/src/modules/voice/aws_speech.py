"""Speech on the School AWS account. No Gemini key and no DashScope voice key.

Dictation and voice use Amazon Transcribe streaming in ap-south-1, with
automatic language identification. Replies are spoken with Amazon Polly neural
Kajal, the bilingual Indian English and Hindi voice. The agent that decides a
tool call stays on the existing Qwen chat path.
"""

from __future__ import annotations

import asyncio
import logging

from src.core.config import get_settings
from src.core.exceptions import UpstreamError

logger = logging.getLogger("sybeez.ai.voice.aws")

# Streaming language identification needs at least two codes. Indian languages
# the console actually hears come first. Nova Sonic is not used: it is not in
# ap-south-1 and it does not cover these languages.
LANGUAGE_OPTIONS = (
    "en-IN",
    "hi-IN",
    "ta-IN",
    "te-IN",
    "ml-IN",
    "kn-IN",
    "bn-IN",
    "gu-IN",
    "mr-IN",
    "en-US",
)

# Kajal is neural and bilingual (en-IN, hi-IN). Polly has no Tamil or Telugu voice.
POLLY_VOICE = "Kajal"
POLLY_ENGINE = "neural"


def voice_region() -> str:
    region = (get_settings().aws_region or "").strip()
    return region or "ap-south-1"


def polly_language(code: str | None) -> str:
    short = (code or "").strip().lower().replace("_", "-")
    if short.startswith("hi"):
        return "hi-IN"
    return "en-IN"


def final_transcript(events: list) -> tuple[str, str]:
    """Join the non-partial alternatives. The language is the last one Transcribe named."""
    parts: list[str] = []
    language = ""
    for event in events:
        transcript = getattr(event, "transcript", None)
        results = getattr(transcript, "results", None) or []
        for result in results:
            if getattr(result, "is_partial", False):
                continue
            named = getattr(result, "language_code", None) or ""
            if named:
                language = str(named)
            alternatives = getattr(result, "alternatives", None) or []
            if not alternatives:
                continue
            spoken = getattr(alternatives[0], "transcript", "") or ""
            if spoken.strip():
                parts.append(spoken.strip())
    return " ".join(parts).strip(), language


async def _ogg_opus(audio: bytes, mime: str | None) -> bytes:
    kind = (mime or "").lower()
    if "ogg" in kind or "opus" in kind:
        return audio
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ar",
        "48000",
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await proc.communicate(audio)
    if proc.returncode != 0 or not out:
        logger.warning("ffmpeg could not prepare audio status=%s", proc.returncode)
        raise UpstreamError("Could not transcribe the audio")
    return out


async def _stream(audio: bytes, languages: tuple[str, ...] | list[str]) -> tuple[str, str]:
    from amazon_transcribe.client import TranscribeStreamingClient

    client = TranscribeStreamingClient(region=voice_region())
    stream = await client.start_stream_transcription(
        language_code=None,
        media_sample_rate_hz=48000,
        media_encoding="ogg-opus",
        identify_language=True,
        language_options=list(languages),
        preferred_language="en-IN",
    )
    chunk = 8 * 1024
    for start in range(0, len(audio), chunk):
        await stream.input_stream.send_audio_event(audio_chunk=audio[start : start + chunk])
    await stream.input_stream.end_stream()
    events = []
    async for event in stream.output_stream:
        events.append(event)
    return final_transcript(events)


async def transcribe_clip(audio: bytes, mime: str | None) -> tuple[str, str]:
    """Return the spoken words and the language code Transcribe chose."""
    if not audio:
        raise UpstreamError("Could not transcribe the audio")
    ogg = await _ogg_opus(audio, mime)
    try:
        return await _stream(ogg, LANGUAGE_OPTIONS)
    except Exception as exc:
        message = str(exc).lower()
        if "language" not in message:
            logger.warning("transcribe failed: %s", type(exc).__name__)
            raise UpstreamError("Could not transcribe the audio") from None
        logger.warning("transcribe rejected a language code; retrying with en-IN and hi-IN")
    try:
        return await _stream(ogg, ("en-IN", "hi-IN"))
    except Exception as exc:
        logger.warning("transcribe failed: %s", type(exc).__name__)
        raise UpstreamError("Could not transcribe the audio") from None


def synthesize_speech(text: str, language: str | None = None) -> tuple[bytes, str] | None:
    """Polly neural MP3. None when the call fails, so the caller can say so."""
    spoken = " ".join((text or "").split())[:600]
    if not spoken:
        return None
    import boto3

    try:
        client = boto3.client("polly", region_name=voice_region())
        response = client.synthesize_speech(
            Text=spoken,
            OutputFormat="mp3",
            VoiceId=POLLY_VOICE,
            Engine=POLLY_ENGINE,
            LanguageCode=polly_language(language),
        )
        audio = response["AudioStream"].read()
    except Exception as exc:
        logger.warning("polly failed: %s", type(exc).__name__)
        return None
    if not audio:
        return None
    return audio, "audio/mpeg"
