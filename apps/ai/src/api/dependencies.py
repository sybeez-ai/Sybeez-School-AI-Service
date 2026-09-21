from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import UnauthorizedError
from src.core.security import AuthContext, auth_from_payload, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_auth_context(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthContext:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing bearer token")
    payload = decode_access_token(creds.credentials)
    return auth_from_payload(payload)


async def get_bearer_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    if creds is None:
        return None
    return creds.credentials


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
BearerToken = Annotated[str | None, Depends(get_bearer_token)]

__all__ = ["get_db", "get_auth_context", "AuthDep", "BearerToken", "AsyncSession", "Header"]
