"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth
from . import database as db

_bearer = HTTPBearer(auto_error=False)


def _raw_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    header = request.headers.get("x-instafeed-token")
    if header:
        return header.strip()
    return None


def optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict | None:
    """Resolve the authenticated user, or ``None`` when there is no valid session."""
    token = _raw_token(request, credentials)
    if not token:
        return None
    try:
        payload = auth.decode_token(token)
    except auth.AuthError:
        return None
    user = db.get_user(int(payload["uid"]))
    if user is None:
        return None
    db.touch_user(user["id"])
    return user


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    """Resolve the authenticated user or raise ``401``."""
    token = _raw_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Sign in and send 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = auth.decode_token(token)
    except auth.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid session: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = db.get_user(int(payload["uid"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists"
        )
    db.touch_user(user["id"])
    return user


CurrentUser = Annotated[dict, Depends(current_user)]
OptionalUser = Annotated[dict | None, Depends(optional_user)]

__all__ = ["CurrentUser", "OptionalUser", "current_user", "optional_user"]
