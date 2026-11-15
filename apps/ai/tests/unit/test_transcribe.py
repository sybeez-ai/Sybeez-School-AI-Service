"""POST /api/v1/ai/voice/transcribe sends audio to DashScope, never Gemini."""

import httpx
from fastapi.testclient import TestClient

from src.core.config import get_settings
from src.main import app
from src.modules.voice.transcribe import detect_language, parse_transcript
from tests.security.jwks import bearer, mint

client = TestClient(app)
PATH = "/api/v1/ai/voice/transcribe"


def test_language_code_follows_the_script():
    assert detect_language("hello") == "en"
    assert detect_language("வணக்கம்") == "ta"
    assert detect_language("नमस्ते") == "hi"
    text, language = parse_transcript('{"text": "வணக்கம்", "language": "ta"}')
    assert text == "வணக்கம்" and language == "ta"
    text, language = parse_transcript("plain english words")
    assert language == "en"


def test_transcribe_requires_auth_and_rejects_empty_audio():
    assert client.post(PATH).status_code == 401
    empty = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"", "audio/webm")})
    assert empty.status_code == 400
    assert empty.json()["error"]["message"] == "Audio is empty"
    assert "Traceback" not in empty.text


def test_transcribe_uses_dashscope_and_does_not_call_gemini(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gemini-key")

    async def fake_clip(audio, mime):
        assert audio
        assert "webm" in (mime or "")
        from src.modules.usage.tokens import estimate_usage

        return "good morning", "en", estimate_usage("speech", "good morning", model="qwen2-audio-instruct", provider="qwen")

    monkeypatch.setattr("src.modules.voice.qwen_audio.transcribe_qwen", fake_clip)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        if request.url.path.endswith("/api/v1/ai/usage"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        "src.modules.context.core_client.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = client.post(
        PATH,
        headers=bearer(mint()),
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "good morning"
    assert response.json()["language"] == "en"
    assert "generativelanguage" not in seen.get("host", "")
    assert "gemini-key" not in response.text



def test_transcribe_failure_is_a_clear_error(monkeypatch):
    async def fail(audio, mime):
        from src.core.exceptions import UpstreamError
        raise UpstreamError("Could not transcribe the audio")

    async def aws_fail(audio, mime):
        from src.core.exceptions import UpstreamError
        raise UpstreamError("Could not transcribe the audio")

    monkeypatch.setattr("src.modules.voice.qwen_audio.transcribe_qwen", fail)
    monkeypatch.setattr("src.modules.voice.aws_speech.transcribe_clip", aws_fail)
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert "gemini" not in response.text.lower()
