"""POST /api/v1/ai/voice/transcribe sends audio to Gemini, not Qwen ASR."""

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


def test_transcribe_uses_gemini_and_not_qwen_asr(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gemini-key")
    monkeypatch.setattr(get_settings(), "gemini_transcribe_model", "gemini-2.5-flash")
    seen: dict[str, list[str]] = {"hosts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["hosts"].append(request.url.host)
        if "generativelanguage" in request.url.host:
            assert request.headers.get("x-goog-api-key") == "gemini-key"
            assert "qwen" not in request.url.path
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": '{"text": "good morning", "language": "en"}'}]}}]},
            )
        if request.url.path.endswith("/api/v1/ai/usage"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post(
        PATH,
        headers=bearer(mint()),
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "good morning"
    assert response.json()["language"] == "en"
    assert "generativelanguage.googleapis.com" in seen["hosts"]
    assert "gemini-key" not in response.text


def test_depleted_gemini_credit_is_a_clear_402(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gemini-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "generativelanguage" in request.url.host:
            return httpx.Response(402, json={})
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 402
    assert "Voice credit needed" in response.json()["error"]["message"]
    assert "gemini-key" not in response.text


def test_transcribe_failure_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gemini-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "generativelanguage" in request.url.host:
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert "gemini" not in response.text.lower()
