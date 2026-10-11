"""School backend HS256 session tokens, matching create_access_token."""

import time

from fastapi.testclient import TestClient
from jose import jwt

from src.core.config import get_settings
from src.core.security import authenticate_token
from src.main import app
from src.modules.context.core_client import CoreClient
from tests.security.jwks import SCHOOL_A, SCHOOL_B, USER_A, USER_B, bearer

client = TestClient(app)


def session_token(**overrides) -> str:
    """Same claim set as Sybeez-School-Backend create_access_token."""
    now = int(time.time())
    payload = {
        "sub": str(USER_A),
        "role": "STUDENT",
        "type": "access",
        "school_id": str(SCHOOL_A),
        "iat": now,
        "exp": now + 600,
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    headers = payload.pop("_headers", None)
    return jwt.encode(
        payload,
        get_settings().jwt_secret,
        algorithm="HS256",
        headers=headers if isinstance(headers, dict) else None,
    )


def _allow_conversations(monkeypatch):
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


def test_backend_session_token_is_accepted(monkeypatch):
    _allow_conversations(monkeypatch)
    response = client.get("/api/v1/ai/conversations", headers=bearer(session_token()))
    assert response.status_code == 200


async def test_session_token_uses_sub_as_user_id():
    ctx = await authenticate_token(session_token(school_id=str(SCHOOL_B), role="TEACHER"))
    assert ctx.user_id == USER_A
    assert ctx.school_id == SCHOOL_B
    assert ctx.role == "TEACHER"


async def test_session_user_id_claim_overrides_sub():
    ctx = await authenticate_token(session_token(user_id=str(USER_B)))
    assert ctx.user_id == USER_B
    assert ctx.school_id == SCHOOL_A


def test_session_token_signed_with_another_secret_is_rejected():
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "STUDENT",
            "type": "access",
            "school_id": str(SCHOOL_A),
            "exp": int(time.time()) + 600,
        },
        "another-secret-that-is-not-the-shared-one",
        algorithm="HS256",
    )
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_refresh_token_is_rejected():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(type="refresh")),
    )
    assert response.status_code == 401


def test_session_token_without_exp_is_rejected():
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "STUDENT",
            "type": "access",
            "school_id": str(SCHOOL_A),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_expired_session_token_is_rejected():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(exp=int(time.time()) - 3600)),
    )
    assert response.status_code == 401


def test_session_token_with_header_key_is_rejected():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(_headers={"jwk": {"kty": "oct", "k": "abc"}})),
    )
    assert response.status_code == 401


def test_session_token_with_issuer_is_rejected_until_backend_sets_one():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(iss="https://school.example")),
    )
    assert response.status_code == 401


def test_session_token_with_audience_is_rejected_until_backend_sets_one():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(aud="sybeez-ai")),
    )
    assert response.status_code == 401


def test_configured_issuer_and_audience_are_required(monkeypatch):
    _allow_conversations(monkeypatch)
    monkeypatch.setattr(get_settings(), "jwt_issuer", "https://school.example")
    monkeypatch.setattr(get_settings(), "jwt_audience", "sybeez-ai")
    missing = client.get("/api/v1/ai/conversations", headers=bearer(session_token()))
    assert missing.status_code == 401
    accepted = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(session_token(iss="https://school.example", aud="sybeez-ai")),
    )
    assert accepted.status_code == 200


def test_internal_service_token_is_not_a_user_session():
    response = client.get(
        "/api/v1/ai/conversations",
        headers=bearer(get_settings().core_internal_token),
    )
    assert response.status_code == 401


def test_core_internal_token_is_still_sent_to_the_backend():
    headers = CoreClient()._headers(session_token())
    assert headers["X-Internal-Token"] == get_settings().core_internal_token
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-Internal-Token"] not in headers["Authorization"]
