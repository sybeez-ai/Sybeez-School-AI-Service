"""Platform-team sessions carry no school; only the platform assistant accepts them."""

from fastapi.testclient import TestClient

from src.main import app
from tests.security.test_session_tokens import session_token

client = TestClient(app)


def _headers(**claims) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(**claims)}"}


def test_platform_admin_without_school_reaches_platform_assistant(monkeypatch):
    async def fake_complete(llm, *, system, user):
        return "ok"

    monkeypatch.setattr("src.modules.platform_assistant.router.guarded_complete", fake_complete)
    monkeypatch.setattr("src.modules.platform_assistant.router.get_llm", lambda: None)
    r = client.post(
        "/api/v1/ai/platform-assistant/chat",
        json={"message": "hello"},
        headers=_headers(role="PLATFORM_ADMIN", school_id=None),
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "ok"


def test_platform_admin_without_school_is_still_blocked_elsewhere():
    r = client.get("/api/v1/ai/conversations", headers=_headers(role="PLATFORM_ADMIN", school_id=None))
    assert r.status_code == 403
    assert "School context required" in r.text


def test_school_role_without_school_cannot_use_platform_assistant():
    r = client.post(
        "/api/v1/ai/platform-assistant/chat",
        json={"message": "hello"},
        headers=_headers(role="TEACHER", school_id=None),
    )
    assert r.status_code == 403
