import base64
import json
import time

from fastapi.testclient import TestClient
from jose import jwt

from src.core.security import authenticate_token
from src.main import app
from tests.security.jwks import KID, PRIVATE_PEM, SCHOOL_A, SCHOOL_B, USER_A, USER_B, bearer, mint

client = TestClient(app)


def test_missing_token_is_rejected():
    response = client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_alg_none_is_rejected():
    def encode(data: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")
        return raw.decode("ascii")

    token = encode({"alg": "none", "typ": "JWT"}) + "." + encode({"sub": str(USER_A), "role": "STUDENT"}) + "."
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_embedded_jwk_header_is_rejected():
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "STUDENT",
            "school_id": str(SCHOOL_A),
            "token_use": "access",
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
            "client_id": "test-client-id",
            "exp": int(time.time()) + 600,
        },
        PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": KID, "jwk": PUBLIC_JWK_STUB},
    )
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


PUBLIC_JWK_STUB = {"kty": "RSA", "kid": KID, "n": "abc", "e": "AQAB"}


def test_expired_token_is_rejected():
    token = mint(exp=int(time.time()) - 3600)
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_wrong_issuer_is_rejected():
    token = mint(iss="https://evil.example/pool")
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_wrong_client_is_rejected():
    token = mint(client_id="other-client")
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


def test_missing_school_is_forbidden():
    token = mint(school_id=None)
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_missing_role_is_rejected():
    token = mint(role=None)
    response = client.get("/api/v1/ai/conversations", headers=bearer(token))
    assert response.status_code == 401


async def test_explicit_user_id_claim_wins_over_cognito_sub():
    token = mint(sub=str(USER_B), user_id=str(USER_A))
    ctx = await authenticate_token(token)
    assert ctx.user_id == USER_A
    assert ctx.school_id == SCHOOL_A


async def test_custom_claims_match_backend_identity():
    token = mint(
        **{
            "role": None,
            "school_id": None,
            "user_id": None,
            "sub": str(USER_A),
            "custom:role": "teacher",
            "custom:school_id": str(SCHOOL_B),
            "custom:user_id": str(USER_B),
        }
    )
    ctx = await authenticate_token(token)
    assert ctx.role == "TEACHER"
    assert ctx.school_id == SCHOOL_B
    assert ctx.user_id == USER_B


async def test_id_token_audience_is_accepted():
    from src.core.config import get_settings

    token = mint(token_use="id", client_id=None, aud=get_settings().cognito_app_client_id)
    ctx = await authenticate_token(token)
    assert ctx.school_id == SCHOOL_A
    assert ctx.role == "STUDENT"
