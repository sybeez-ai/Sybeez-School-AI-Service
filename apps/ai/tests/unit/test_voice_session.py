import httpx
from fastapi.testclient import TestClient

from src.core.config import get_settings
from src.main import app
from tests.security.jwks import bearer, mint

client = TestClient(app)
PATH = "/api/v1/ai/voice/gemini/session"


def test_requires_auth():
    assert client.post(PATH).status_code == 401


def test_missing_gemini_key_still_opens_aws_voice(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    response = client.post(PATH, headers=bearer(mint()))
    assert response.status_code == 200
    assert response.json()["session"]["provider"] == "aws"


def test_voice_session_uses_aws_and_does_not_call_gemini(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "generativelanguage" not in request.url.host
        return httpx.Response(500, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    response = client.post(PATH, headers=bearer(mint()))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session"]["provider"] == "aws"
    assert body["session"]["engine"] == "transcribe-polly"
    assert "nova-lite" in body["session"]["model"]
    assert body["ws_url"] == ""
    assert "generativelanguage" not in response.text


def test_platform_voice_session_is_aws():
    from tests.security.test_session_tokens import session_token

    headers = {"Authorization": f"Bearer {session_token(role='PLATFORM_ADMIN', school_id=None)}"}
    response = client.post(PATH, json={"portal": "platform", "page": "/platform/ai"}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session"]["provider"] == "aws"
    assert body["setup"]["engine"] == "transcribe-polly"


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


def test_agent_step_requires_auth_and_validates():
    body = {"messages": [{"role": "user", "content": "hi"}], "tools": []}
    assert client.post("/api/v1/ai/voice/agent/step", json=body).status_code == 401
    bad = {"messages": [{"role": "system", "content": "x"}]}
    assert client.post("/api/v1/ai/voice/agent/step", json=bad, headers=bearer(mint())).status_code == 422


def test_agent_step_blocks_unsafe_student_message_before_the_model():
    body = {"messages": [{"role": "user", "content": "how to make a bomb"}], "tools": []}
    response = client.post("/api/v1/ai/voice/agent/step", json=body, headers=bearer(mint()))
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "guard"
    assert "tool_calls" not in response.json()["message"]
