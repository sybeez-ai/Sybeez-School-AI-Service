from dataclasses import dataclass
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from src.core.config import get_settings
from src.core.exceptions import ForbiddenError, UnauthorizedError


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


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")
    return payload


def auth_from_payload(payload: dict[str, Any]) -> AuthContext:
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Invalid subject") from exc
    school_id = UUID(payload["school_id"]) if payload.get("school_id") else None
    membership_id = UUID(payload["membership_id"]) if payload.get("membership_id") else None
    return AuthContext(
        user_id=user_id,
        role=str(payload.get("role", "")),
        school_id=school_id,
        membership_id=membership_id,
        raw=payload,
    )


def require_school(ctx: AuthContext) -> UUID:
    if ctx.school_id is None:
        raise ForbiddenError("School context required")
    return ctx.school_id
