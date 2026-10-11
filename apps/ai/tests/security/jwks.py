import time
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from src.core.config import get_settings

SCHOOL_A = UUID("11111111-1111-1111-1111-111111111111")
SCHOOL_B = UUID("22222222-2222-2222-2222-222222222222")
USER_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
KID = "test-key-1"

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC = _PRIVATE.public_key().public_numbers()
PRIVATE_PEM = _PRIVATE.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)


def _b64u(value: int) -> str:
    import base64

    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


PUBLIC_JWK = {
    "kty": "RSA",
    "kid": KID,
    "use": "sig",
    "alg": "RS256",
    "n": _b64u(_PUBLIC.n),
    "e": _b64u(_PUBLIC.e),
}


def mint(**overrides) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(USER_A),
        "user_id": str(USER_A),
        "role": "STUDENT",
        "school_id": str(SCHOOL_A),
        "token_use": "access",
        "client_id": settings.cognito_app_client_id,
        "iss": settings.cognito_issuer,
        "iat": now,
        "exp": now + 600,
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    headers = {"kid": KID}
    extra_headers = payload.pop("_headers", None)
    if isinstance(extra_headers, dict):
        headers.update(extra_headers)
    return jwt.encode(payload, PRIVATE_PEM, algorithm="RS256", headers=headers)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
