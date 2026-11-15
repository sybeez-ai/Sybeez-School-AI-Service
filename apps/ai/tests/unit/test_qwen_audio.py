"""DashScope speech skips a rejected model and never calls Gemini."""

import json
from types import SimpleNamespace

import httpx
import pytest

from src.modules.voice import qwen_audio


@pytest.mark.asyncio
async def test_asr_uses_the_first_model_that_returns_words(monkeypatch):
    qwen_audio._asr_winner = None
    seen: list[str] = []

    async def passthrough(audio, mime):
        return audio

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model(request)
        seen.append(model)
        assert "generativelanguage" not in request.url.host
        if model == "qwen3-asr-flash":
            return httpx.Response(403, json={"code": "AccessDenied"})
        if model == "qwen2-audio-instruct":
            return httpx.Response(
                200,
                json={"output": {"choices": [{"message": {"content": [{"text": "good morning"}]}}]}},
            )
        return httpx.Response(403, json={"code": "AccessDenied"})

    _patch_client(monkeypatch, handler)
    monkeypatch.setattr(qwen_audio, "_wav", passthrough)
    monkeypatch.setattr(qwen_audio, "get_settings", lambda: _settings())
    text, language, usage = await qwen_audio.transcribe_qwen(b"abc", "audio/webm")
    assert text == "good morning"
    assert language == "en"
    assert usage.provider == "qwen"
    assert usage.model == "qwen2-audio-instruct"
    assert seen[0] == "qwen3-asr-flash"
    assert "qwen2-audio-instruct" in seen
    assert qwen_audio._asr_winner is not None
    assert qwen_audio._asr_winner[2] == "qwen2-audio-instruct"


@pytest.mark.asyncio
async def test_tts_skips_a_rejected_speech_model(monkeypatch):
    qwen_audio._tts_winner = None

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model(request)
        if model == "qwen3-tts-flash" and request.url.path.endswith("/audio/speech"):
            return httpx.Response(403, json={"code": "AccessDenied"})
        if model == "qwen3-tts-flash":
            return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})
        return httpx.Response(404, json={"code": "ModelNotFound"})

    _patch_client(monkeypatch, handler)
    monkeypatch.setattr(qwen_audio, "get_settings", lambda: _settings())
    audio = await qwen_audio.synthesize_qwen("good morning")
    assert audio is not None
    assert audio[0].startswith(b"ID3")
    assert qwen_audio._tts_winner is not None
    assert qwen_audio._tts_winner[3] == "tts"


def test_parse_asr_reads_chat_and_multimodal_text():
    chat = {"choices": [{"message": {"content": "hello"}}]}
    multimodal = {"output": {"choices": [{"message": {"content": [{"text": "வணக்கம்"}]}}]}}
    assert qwen_audio.parse_asr_text(chat) == "hello"
    assert qwen_audio.parse_asr_text(multimodal) == "வணக்கம்"


def _patch_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = transport
        return real(**kwargs)

    monkeypatch.setattr(qwen_audio.httpx, "AsyncClient", client)


def _model(request: httpx.Request) -> str:
    body = json.loads(request.content.decode() or "{}")
    return str(body.get("model") or "")


def _settings():
    return SimpleNamespace(qwen_chat_api_key="test-key", llm_timeout_seconds=5)
