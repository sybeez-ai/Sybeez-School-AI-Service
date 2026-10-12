import httpx
from fastapi.testclient import TestClient

from src.core.config import get_settings
from src.main import app
from src.modules.voice import router as voice
from tests.security.jwks import bearer, mint

client = TestClient(app)
PATH = "/api/v1/ai/voice/gemini/session"


def test_requires_auth():
    assert client.post(PATH).status_code == 401


def test_unconfigured_is_503(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    response = client.post(PATH, headers=bearer(mint()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "voice_unavailable"


def test_mints_ephemeral_token_without_leaking_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"name": "auth_tokens/abc"})

    real = httpx.AsyncClient
    monkeypatch.setattr(voice.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    response = client.post(PATH, headers=bearer(mint()))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["value"] == "auth_tokens/abc"
    assert body["ws_url"].endswith("BidiGenerateContentConstrained")
    assert "server-key" not in response.text
    assert seen["key"] == "server-key" and seen["url"] == voice.TOKEN_URL


def test_upstream_rejection_is_502(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    real = httpx.AsyncClient
    monkeypatch.setattr(
        voice.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})), **kw),
    )
    assert client.post(PATH, headers=bearer(mint())).status_code == 502
