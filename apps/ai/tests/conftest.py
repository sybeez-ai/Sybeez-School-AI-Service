import os

os.environ["APP_ENV"] = "test"
os.environ["COGNITO_REGION"] = "us-east-1"
os.environ["COGNITO_USER_POOL_ID"] = "us-east-1_TestPool"
os.environ["COGNITO_APP_CLIENT_ID"] = "test-client-id"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["UPSTREAM_TIMEOUT_SECONDS"] = "1"
os.environ["HEALTH_TIMEOUT_SECONDS"] = "1"
os.environ["DB_CONNECT_TIMEOUT_SECONDS"] = "1"
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("QWEN_CHAT_API_KEY", "")

import pytest

from src.core.rate_limit import limiter
from src.core.security import CognitoVerifier, reset_verifier
from tests.security.jwks import PUBLIC_JWK


@pytest.fixture(autouse=True)
def _jwks_and_limits(monkeypatch):
    async def fake_fetch(self):
        return {"keys": [PUBLIC_JWK]}

    monkeypatch.setattr(CognitoVerifier, "_fetch_jwks_document", fake_fetch)
    reset_verifier()
    limiter.reset()
    yield
    limiter.reset()
    reset_verifier()
