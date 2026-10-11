"""Narration audio.

Gemini Live is used when GEMINI_API_KEY is set. Qwen is the fallback when only
QWEN_VOICE_API_KEY is set. Teaching still streams narration text when neither
provider returns audio.
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass

import httpx

from src.core.config import get_settings

logger = logging.getLogger("sybeez.ai.teacher.voice")

_MAX_PCM_BYTES = 2_000_000
_SAMPLE_RATE = 24000


@dataclass(frozen=True)
class VoiceClip:
    provider: str
    mime_type: str
    audio_base64: str
    duration_ms: int
    sample_rate: int

    def as_event(self) -> dict:
        return {
            "provider": self.provider,
            "mime_type": self.mime_type,
            "audio_base64": self.audio_base64,
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
        }


class NullVoice:
    name = "none"

    def available(self) -> bool:
        return False

    async def synthesize(self, text: str) -> VoiceClip | None:
        return None


class GeminiLiveVoice:
    """Short-lived Gemini Live session that speaks one narration."""

    name = "gemini_live"

    def available(self) -> bool:
        return get_settings().has_gemini_live

    async def synthesize(self, text: str) -> VoiceClip | None:
        spoken = " ".join(text.split())[:600]
        if not spoken or not self.available():
            return None
        try:
            pcm = await self._speak(spoken)
        except Exception:
            logger.warning("gemini live synthesis failed")
            return None
        if not pcm:
            return None
        if len(pcm) > _MAX_PCM_BYTES:
            pcm = pcm[:_MAX_PCM_BYTES]
        duration_ms = max(1, int(len(pcm) / (_SAMPLE_RATE * 2) * 1000))
        return VoiceClip(
            provider=self.name,
            mime_type=f"audio/pcm;rate={_SAMPLE_RATE}",
            audio_base64=base64.b64encode(pcm).decode("ascii"),
            duration_ms=duration_ms,
            sample_rate=_SAMPLE_RATE,
        )

    async def _speak(self, text: str) -> bytes:
        import websockets

        settings = get_settings()
        model = settings.gemini_live_model
        if not model.startswith("models/"):
            model = f"models/{model}"
        url = f"{settings.gemini_live_ws_url}?key={settings.gemini_api_key}"
        try:
            async with websockets.connect(url, open_timeout=settings.upstream_timeout_seconds, close_timeout=5) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "setup": {
                                "model": model,
                                "generationConfig": {"responseModalities": ["AUDIO"]},
                            }
                        }
                    )
                )
                return await read_live_audio(ws, text=text, timeout=settings.llm_timeout_seconds)
        except Exception:
            raise RuntimeError("gemini live connection failed") from None


async def read_live_audio(ws, *, text: str, timeout: float) -> bytes:
    raw_setup = await asyncio.wait_for(ws.recv(), timeout)
    setup = json.loads(raw_setup)
    if isinstance(setup, dict) and setup.get("error"):
        raise RuntimeError("gemini live setup failed")
    await ws.send(
        json.dumps(
            {
                "clientContent": {
                    "turns": [
                        {
                            "role": "user",
                            "parts": [{"text": f"Speak this explanation exactly, with no preamble:\n{text}"}],
                        }
                    ],
                    "turnComplete": True,
                }
            }
        )
    )
    chunks: list[bytes] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        incoming = await asyncio.wait_for(ws.recv(), remaining)
        data = json.loads(incoming)
        server = data.get("serverContent") or {}
        for part in (server.get("modelTurn") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            encoded = inline.get("data")
            if encoded:
                chunks.append(base64.b64decode(encoded))
        if server.get("turnComplete") or server.get("turn_complete"):
            break
    return b"".join(chunks)


class QwenVoice:
    """OpenAI-compatible speech endpoint using the existing Qwen voice key."""

    name = "qwen"

    def available(self) -> bool:
        return get_settings().has_qwen_voice

    async def synthesize(self, text: str) -> VoiceClip | None:
        settings = get_settings()
        spoken = " ".join(text.split())[:600]
        if not spoken or not self.available():
            return None
        url = f"{settings.qwen_base_url.rstrip('/')}/audio/speech"
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.qwen_voice_api_key}"},
                    json={"model": settings.qwen_voice_model, "input": spoken, "voice": "alloy"},
                )
        except httpx.HTTPError:
            logger.warning("qwen voice synthesis failed")
            return None
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400 or "audio" not in content_type and "octet-stream" not in content_type:
            return None
        audio = response.content
        if not audio or len(audio) > _MAX_PCM_BYTES:
            return None
        return VoiceClip(
            provider=self.name,
            mime_type=content_type.split(";")[0] or "audio/mpeg",
            audio_base64=base64.b64encode(audio).decode("ascii"),
            duration_ms=max(1, len(spoken.split()) * 380),
            sample_rate=0,
        )


def get_voice():
    settings = get_settings()
    provider = settings.voice_provider.lower()
    if provider == "none":
        return NullVoice()
    if provider in {"auto", "gemini_live"} and settings.has_gemini_live:
        return GeminiLiveVoice()
    if provider in {"auto", "qwen"} and settings.has_qwen_voice:
        return QwenVoice()
    return NullVoice()
