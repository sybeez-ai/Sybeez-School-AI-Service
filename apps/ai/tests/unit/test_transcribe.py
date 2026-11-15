"""POST /api/v1/ai/voice/transcribe is the Web Speech fallback."""

import json

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


def test_transcribe_prefers_qwen_over_the_gemini_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gemini-key")
    monkeypatch.setattr(get_settings(), "qwen_chat_api_key", "qwen-key")
    monkeypatch.setattr(get_settings(), "qwen_asr_model", "qwen3-asr-flash")
    seen = {"hosts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["hosts"].append(request.url.host)
        if "dashscope" in request.url.host:
            assert request.headers.get("authorization") == "Bearer qwen-key"
            return httpx.Response(
                200,
                json={"output": {"choices": [{"message": {"content": [{"text": "good morning"}]}}]}},
            )
        return httpx.Response(429, json={"error": {"message": "prepayment credits are depleted"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        "src.modules.voice.qwen_audio.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("src.modules.context.core_client.httpx.AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post(
        PATH,
        headers=bearer(mint()),
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "good morning"
    assert any("dashscope" in host for host in seen["hosts"])
    assert "generativelanguage" not in "".join(seen["hosts"])
    assert "qwen-key" not in response.text
    assert "gemini-key" not in response.text


def test_transcribe_returns_text_and_language_without_leaking_the_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_chat_api_key", "")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "generativelanguage" in host:
            seen["key"] = request.headers.get("x-goog-api-key")
            body = json.loads(request.content)
            seen["has_audio"] = "inlineData" in json.dumps(body.get("contents"))
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": '{"text": "good morning", "language": "en"}'}]}}],
                    "usageMetadata": {"promptTokenCount": 15, "candidatesTokenCount": 3},
                },
            )
        if request.url.path.endswith("/api/v1/ai/usage"):
            seen["usage"] = json.loads(request.content)
            assert "authorization" not in json.dumps(seen["usage"]).lower()
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(503, json={})

    real = httpx.AsyncClient

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("src.modules.voice.transcribe.httpx.AsyncClient", factory)
    monkeypatch.setattr("src.modules.context.core_client.httpx.AsyncClient", factory)
    response = client.post(
        PATH,
        headers=bearer(mint()),
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "good morning", "language": "en"}
    assert seen["key"] == "server-key"
    assert seen["has_audio"] is True
    assert seen["usage"]["input_tokens"] == 15
    assert seen["usage"]["output_tokens"] == 3
    assert seen["usage"]["capability"] == "CHAT"
    assert "server-key" not in response.text
    assert "audio" not in response.text.lower() or response.json()["text"]


def test_usage_report_failure_still_returns_the_transcript(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_chat_api_key", "")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "generativelanguage" in request.url.host:
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": '{"text": "hi", "language": "en"}'}]}}]},
            )
        return httpx.Response(500, json={"error": "nope"})

    real = httpx.AsyncClient
    factory = lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)  # noqa: E731
    monkeypatch.setattr("src.modules.voice.transcribe.httpx.AsyncClient", factory)
    monkeypatch.setattr("src.modules.context.core_client.httpx.AsyncClient", factory)
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "hi"
    assert "Traceback" not in response.text


def test_provider_rejection_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_chat_api_key", "")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "src.modules.voice.transcribe.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})), **kwargs),
    )
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert response.json()["error"]["message"]
