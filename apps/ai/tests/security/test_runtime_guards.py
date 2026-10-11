import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

from src.core.config import Settings, get_settings, validate_production_settings
from src.core.rate_limit import limiter
from src.core.secrets import apply_secret_mapping, fetch_secrets_manager_json
from src.main import app
from src.providers.llm import guarded_complete
from tests.security.jwks import bearer, mint

client = TestClient(app)


def test_health_is_public():
    root = client.get("/health")
    prefixed = client.get("/api/v1/ai/health")
    assert root.status_code == 200
    assert root.json()["status"] == "ok"
    assert prefixed.status_code == 200
    assert "sybeez:sybeez" not in root.text


def test_ready_reports_dependencies(monkeypatch):
    async def database_ok():
        return True

    async def ping(self):
        return False

    monkeypatch.setattr("src.core.health.database_ok", database_ok)
    monkeypatch.setattr("src.core.health.CoreClient.ping", ping)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["ok"] is True
    assert body["dependencies"]["core_api"]["ok"] is False
    assert "url" not in body["dependencies"]["core_api"]


def test_ready_fails_when_database_is_down(monkeypatch):
    async def database_ok():
        return False

    async def ping(self):
        return True

    monkeypatch.setattr("src.core.health.database_ok", database_ok)
    monkeypatch.setattr("src.core.health.CoreClient.ping", ping)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_rate_limit(monkeypatch):
    class Dummy:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def fake_list(self, auth):
        return []

    monkeypatch.setattr("src.api.dependencies.AsyncSessionLocal", lambda: Dummy())
    monkeypatch.setattr("src.api.dependencies.install_tenant_context", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.modules.conversations.router.ConversationService.list", fake_list)
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2)
    limiter.reset()
    headers = bearer(mint())
    for _ in range(2):
        allowed = client.get("/api/v1/ai/conversations", headers=headers)
        assert allowed.status_code == 200
    blocked = client.get("/api/v1/ai/conversations", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert client.get("/health").status_code == 200


def test_request_timeout(monkeypatch):
    async def slow(self, auth, body, bearer_token=None):
        await asyncio.sleep(1)

    monkeypatch.setattr(get_settings(), "request_timeout_seconds", 0.05)
    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", slow)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


def test_internal_error_hides_details(monkeypatch):
    async def boom(self, auth, body, bearer_token=None):
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", boom)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


def test_validation_error_omits_input():
    response = client.post(
        "/api/v1/ai/practice",
        headers=bearer(mint()),
        json={"count": 0, "topic": "secret-topic-value"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "secret-topic-value" not in response.text


def test_body_too_large(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_body_bytes", 16)
    response = client.post(
        "/api/v1/ai/practice",
        headers=bearer(mint()),
        json={"count": 1, "topic": "photosynthesis lesson"},
    )
    assert response.status_code == 413


def test_production_error_does_not_echo_password():
    password = "super-secret-password"
    settings = Settings(
        app_env="production",
        database_url=f"postgresql+asyncpg://ai_app:{password}@db.internal/sybeez",
        cognito_region="",
        cognito_user_pool_id="",
        cognito_app_client_id="",
        core_internal_token="dev-internal-service-token",
    )
    with pytest.raises(RuntimeError) as exc:
        validate_production_settings(settings)
    message = str(exc.value)
    assert password not in message
    assert "COGNITO_REGION" in message
    assert "CORE_INTERNAL_TOKEN" in message


def test_production_settings_accept_real_config():
    settings = Settings(
        app_env="production",
        database_url="postgresql+asyncpg://ai_app:secret@db.internal/sybeez",
        cognito_region="us-east-1",
        cognito_user_pool_id="us-east-1_abc",
        cognito_app_client_id="client",
        core_internal_token="prod-internal-token",
    )
    validate_production_settings(settings)


def test_env_wins_over_secrets_manager():
    previous = os.environ.get("DEEPSEEK_API_KEY")
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "from-env")
    try:
        os.environ["DATABASE_URL"] = "from-env"
        changed = apply_secret_mapping({"DATABASE_URL": "from-secret", "DEEPSEEK_API_KEY": "k", "not-valid": "x"})
        assert changed is True
        assert os.environ["DATABASE_URL"] == "from-env"
        assert os.environ["DEEPSEEK_API_KEY"] == "k"
        assert "not-valid" not in os.environ
    finally:
        if previous is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = previous


def test_secret_fetch_error_hides_payload(monkeypatch):
    class FakeBoto:
        def client(self, name, region_name=None):
            raise RuntimeError("secret-value-should-not-leak")

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto())
    with pytest.raises(RuntimeError) as exc:
        fetch_secrets_manager_json("sid", "us-east-1")
    assert "secret-value-should-not-leak" not in str(exc.value)


async def test_llm_errors_are_generic():
    class Boom:
        async def complete(self, *, system, user):
            raise RuntimeError("sk-live-secret")

    from src.core.exceptions import UpstreamError

    with pytest.raises(UpstreamError) as exc:
        await guarded_complete(Boom(), system="s", user="u")
    assert "sk-live-secret" not in str(exc.value)
