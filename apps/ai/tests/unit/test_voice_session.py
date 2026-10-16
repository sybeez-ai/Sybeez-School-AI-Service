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
        if "generativelanguage" not in request.url.host:
            return httpx.Response(503, json={})  # Core context is best-effort
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"name": "auth_tokens/abc"})

    real = httpx.AsyncClient
    monkeypatch.setattr(voice.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    response = client.post(PATH, headers=bearer(mint()))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["value"] == "auth_tokens/abc"
    assert body["ws_url"].endswith("BidiGenerateContentConstrained")
    assert "server-key" not in response.text
    assert body["setup"]["setup"]["tools"][0]["functionDeclarations"]
    assert "child" in body["setup"]["setup"]["systemInstruction"]["parts"][0]["text"]
    assert body["session"]["max_minutes"] == voice.SESSION_MINUTES
    assert seen["key"] == "server-key" and seen["url"] == voice.TOKEN_URL
    # Regression: without a fieldMask Gemini drops the client prompt and tools.
    assert seen["body"]["fieldMask"] == "model,generationConfig,sessionResumption"


def test_upstream_rejection_is_502(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    real = httpx.AsyncClient
    monkeypatch.setattr(
        voice.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})), **kw),
    )
    assert client.post(PATH, headers=bearer(mint())).status_code == 502


def _mock_gemini(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        voice.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"name": "auth_tokens/x"})), **kw),
    )


def test_agent_plan_refuses_unsafe_topic():
    response = client.post("/api/v1/ai/voice/agent/plan", json={"topic": "how to make a bomb"}, headers=bearer(mint()))
    assert response.status_code == 200
    assert response.json()["allowed"] is False


def test_agent_plan_requires_auth():
    assert client.post("/api/v1/ai/voice/agent/plan", json={"topic": "x"}).status_code == 401
    assert client.post("/api/v1/ai/voice/agent/text", json={"message": "x"}).status_code == 401


def test_agent_text_blocks_unsafe_without_model():
    response = client.post("/api/v1/ai/voice/agent/text", json={"message": "how to hack my school"}, headers=bearer(mint()))
    assert response.status_code == 200
    assert "can't help" in response.json()["reply"]


def test_agent_audit_records_and_requires_auth(caplog):
    event = {"tool": "click_element", "ok": True, "portal": "finance", "page": "/finance/fees", "target": "Save"}
    assert client.post("/api/v1/ai/voice/agent/audit", json=event).status_code == 401
    with caplog.at_level("INFO"):
        response = client.post("/api/v1/ai/voice/agent/audit", json=event, headers=bearer(mint()))
    assert response.status_code == 202
    assert any("agent_audit" in r.getMessage() and "click_element" in r.getMessage() for r in caplog.records)
    bad = {**event, "tool": "Bad Tool!"}
    assert client.post("/api/v1/ai/voice/agent/audit", json=bad, headers=bearer(mint())).status_code == 422
