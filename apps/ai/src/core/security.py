import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt

from src.core.config import get_settings
from src.core.exceptions import ForbiddenError, UnauthorizedError

logger = logging.getLogger("sybeez.ai.auth")

ALLOWED_ROLES = frozenset({"PLATFORM_ADMIN", "SCHOOL_ADMIN", "TEACHER", "STUDENT", "PARENT"})


@dataclass
class AuthContext:
    user_id: UUID
    role: str
    school_id: UUID | None
    membership_id: UUID | None
    raw: dict[str, Any]

    @property
    def is_student(self) -> bool:
        return self.role == "STUDENT"

    @property
    def is_teacher(self) -> bool:
        return self.role == "TEACHER"

    @property
    def is_school_staff(self) -> bool:
        return self.role in {"SCHOOL_ADMIN", "TEACHER"}


class CognitoVerifier:
    """Verify Cognito RS256 tokens against the user-pool JWKS."""

    def __init__(self) -> None:
        self._keys_cache: dict[str, dict[str, Any]] = {}
        self._fetched_at = 0.0
        self._lock = None

    def _mutex(self):
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    async def _fetch_jwks_document(self) -> dict[str, Any]:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.jwks_timeout_seconds) as client:
            response = await client.get(settings.cognito_jwks_url)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("jwks document")
        return data

    async def _keys(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        settings = get_settings()
        ttl = settings.cognito_jwks_cache_seconds
        now = time.monotonic()
        if not force and self._keys_cache and now - self._fetched_at < ttl:
            return self._keys_cache
        async with self._mutex():
            now = time.monotonic()
            if not force and self._keys_cache and now - self._fetched_at < ttl:
                return self._keys_cache
            try:
                document = await self._fetch_jwks_document()
            except Exception:
                logger.warning("jwks fetch failed")
                if self._keys_cache:
                    return self._keys_cache
                raise UnauthorizedError("Invalid or expired token") from None
            keys: dict[str, dict[str, Any]] = {}
            for item in document.get("keys", []):
                if not isinstance(item, dict):
                    continue
                kid = item.get("kid")
                if not kid or item.get("kty") != "RSA":
                    continue
                if item.get("alg") not in (None, "RS256"):
                    continue
                keys[str(kid)] = item
            if not keys:
                raise UnauthorizedError("Invalid or expired token")
            self._keys_cache = keys
            self._fetched_at = time.monotonic()
            return keys

    async def key_for_kid(self, kid: str) -> dict[str, Any] | None:
        keys = await self._keys()
        if kid in keys:
            return keys[kid]
        keys = await self._keys(force=True)
        return keys.get(kid)


_verifier: CognitoVerifier | None = None


def get_verifier() -> CognitoVerifier:
    global _verifier
    if _verifier is None:
        _verifier = CognitoVerifier()
    return _verifier


def reset_verifier() -> None:
    global _verifier
    _verifier = None


def _uuid_claim(payload: dict[str, Any], *names: str, required: bool) -> UUID | None:
    raw = None
    for name in names:
        value = payload.get(name)
        if value:
            raw = value
            break
    if raw is None:
        if required:
            raise UnauthorizedError("Invalid or expired token")
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def auth_from_payload(payload: dict[str, Any]) -> AuthContext:
    """Derive identity from verified claims. Client-supplied fields are not an input."""
    user_id = _uuid_claim(payload, "user_id", "custom:user_id", required=False)
    if user_id is None:
        user_id = _uuid_claim(payload, "sub", required=True)
    role_raw = payload.get("role") or payload.get("custom:role")
    if not role_raw:
        logger.warning("token missing role claim")
        raise UnauthorizedError("Invalid or expired token")
    role = str(role_raw).strip().upper()
    if role not in ALLOWED_ROLES:
        logger.warning("token role rejected")
        raise UnauthorizedError("Invalid or expired token")
    school_id = _uuid_claim(payload, "school_id", "custom:school_id", required=False)
    membership_id = _uuid_claim(payload, "membership_id", "custom:membership_id", required=False)
    assert user_id is not None
    return AuthContext(
        user_id=user_id,
        role=role,
        school_id=school_id,
        membership_id=membership_id,
        raw=payload,
    )


# School backend create_access_token (Sybeez-School-Backend apps/api/src/core/security.py)
# signs with JWT_SECRET and sets sub, role, type=access, iat, exp, optional school_id
# and membership_id, plus extra sid/platform_role. It does not set iss or aud.
_HEADER_KEY_FIELDS = ("jku", "x5u", "jwk")
_SESSION_TOKEN_TYPE = "access"


def _reject_header_keys(header: dict[str, Any]) -> None:
    if any(header.get(field) for field in _HEADER_KEY_FIELDS):
        logger.warning("rejected token header key reference")
        raise UnauthorizedError("Invalid or expired token")


def _unverified_header(token: str) -> dict[str, Any]:
    if not token or token.count(".") != 2:
        raise UnauthorizedError("Invalid or expired token")
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
    if not isinstance(header, dict):
        raise UnauthorizedError("Invalid or expired token")
    _reject_header_keys(header)
    return header


def _claim_matches(actual: Any, expected: str) -> bool:
    if isinstance(actual, list):
        return expected in actual
    return actual == expected


def _require_backend_reserved_claim(payload: dict[str, Any], name: str, expected: str) -> None:
    """Match the issuer or audience the backend actually puts on the token.

    create_access_token omits both claims, so the expected value stays empty and a
    token that carries one is rejected. Set JWT_ISSUER or JWT_AUDIENCE only when
    the backend starts setting the same claim.
    """
    actual = payload.get(name)
    if not expected:
        if actual:
            logger.warning("session token carried unexpected %s", name)
            raise UnauthorizedError("Invalid or expired token")
        return
    if not _claim_matches(actual, expected):
        logger.warning("session token %s rejected", name)
        raise UnauthorizedError("Invalid or expired token")


def _decode_session_token(token: str) -> dict[str, Any]:
    """Verify a School backend HS256 access token. The key is only JWT_SECRET."""
    settings = get_settings()
    secret = settings.jwt_secret
    if settings.jwt_algorithm != "HS256" or not secret:
        logger.error("session token verification is not configured")
        raise UnauthorizedError("Invalid or expired token")
    issuer = settings.jwt_issuer.strip()
    audience = settings.jwt_audience.strip()
    options: dict[str, Any] = {"require_exp": True, "leeway": 30}
    decode_kwargs: dict[str, Any] = {}
    if issuer:
        decode_kwargs["issuer"] = issuer
    if audience:
        decode_kwargs["audience"] = audience
    else:
        # Backend tokens omit aud. A token that includes one is rejected afterwards.
        options["verify_aud"] = False
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options=options,
            **decode_kwargs,
        )
    except JWTError:
        logger.warning("session token signature or claims rejected")
        raise UnauthorizedError("Invalid or expired token") from None
    if not isinstance(payload, dict):
        raise UnauthorizedError("Invalid or expired token")
    if payload.get("type") != _SESSION_TOKEN_TYPE:
        logger.warning("session token type rejected")
        raise UnauthorizedError("Invalid or expired token")
    _require_backend_reserved_claim(payload, "iss", settings.jwt_issuer.strip())
    _require_backend_reserved_claim(payload, "aud", settings.jwt_audience.strip())
    return payload


def _require_audience(payload: dict[str, Any], client_id: str) -> None:
    token_use = payload.get("token_use")
    if token_use == "access":
        if payload.get("client_id") != client_id:
            raise UnauthorizedError("Invalid or expired token")
        return
    if token_use == "id":
        audience = payload.get("aud")
        if audience == client_id or (isinstance(audience, list) and client_id in audience):
            return
        raise UnauthorizedError("Invalid or expired token")
    raise UnauthorizedError("Invalid or expired token")


async def _decode_cognito_token(token: str, header: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.cognito_configured:
        logger.error("cognito settings are missing")
        raise UnauthorizedError("Invalid or expired token")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise UnauthorizedError("Invalid or expired token")
    key = await get_verifier().key_for_kid(kid)
    if key is None:
        raise UnauthorizedError("Invalid or expired token")
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"verify_aud": False, "verify_at_hash": False, "leeway": 30},
        )
    except JWTError:
        logger.warning("token signature or claims rejected: %s", "JWTError")
        raise UnauthorizedError("Invalid or expired token") from None
    if not isinstance(payload, dict):
        raise UnauthorizedError("Invalid or expired token")
    _require_audience(payload, settings.cognito_app_client_id)
    return payload


async def decode_access_token(token: str) -> dict[str, Any]:
    header = _unverified_header(token)
    algorithm = header.get("alg")
    if algorithm == "RS256":
        return await _decode_cognito_token(token, header)
    if algorithm == "HS256":
        return _decode_session_token(token)
    logger.warning("rejected token alg")
    raise UnauthorizedError("Invalid or expired token")


async def authenticate_token(token: str) -> AuthContext:
    return auth_from_payload(await decode_access_token(token))


def require_school(ctx: AuthContext) -> UUID:
    if ctx.school_id is None:
        raise ForbiddenError("School context required")
    return ctx.school_id
