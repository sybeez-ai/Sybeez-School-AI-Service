from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal, install_tenant_context
from src.core.exceptions import UnauthorizedError
from src.core.security import AuthContext, require_school


async def get_auth_context(request: Request) -> AuthContext:
    ctx = getattr(request.state, "auth", None)
    if not isinstance(ctx, AuthContext):
        raise UnauthorizedError("Missing bearer token")
    return ctx


async def get_bearer_token(request: Request) -> str | None:
    token = getattr(request.state, "token", None)
    if isinstance(token, str) and token:
        return token
    return None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """One transaction per request, with SET LOCAL tenant context from the token."""
    auth = await get_auth_context(request)
    school_id = require_school(auth)
    async with AsyncSessionLocal() as session:
        install_tenant_context(
            session, school_id=school_id, user_id=auth.user_id, role=auth.role
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
BearerToken = Annotated[str | None, Depends(get_bearer_token)]

__all__ = ["get_db", "get_auth_context", "AuthDep", "BearerToken", "AsyncSession"]
