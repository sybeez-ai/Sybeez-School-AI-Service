import asyncio

from src.core import health


class _S:
    cognito_configured = False
    jwt_algorithm = "HS256"
    jwt_secret = "a-real-secret-value-0123456789abcdef"
    active_chat_api_key = "k"


def _run(monkeypatch, settings):
    async def ok():
        return True

    class Core:
        async def ping(self):
            return True

    monkeypatch.setattr(health, "get_settings", lambda: settings)
    monkeypatch.setattr(health, "database_ok", ok)
    monkeypatch.setattr(health, "CoreClient", Core)
    return asyncio.run(health.readiness())[0]


def test_ready_when_session_secret_configured_without_cognito(monkeypatch):
    body = _run(monkeypatch, _S())
    assert body["dependencies"]["auth"]["ok"] is True and body["status"] == "ready"


def test_degraded_when_secret_is_the_default(monkeypatch):
    s = _S()
    s.jwt_secret = "change-me-in-production"
    assert _run(monkeypatch, s)["dependencies"]["auth"]["ok"] is False
