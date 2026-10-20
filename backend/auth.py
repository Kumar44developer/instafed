"""Authentication for Instafeed — dependency-free, secure by default.

Design
------
* Passwords are hashed with PBKDF2-HMAC-SHA256 and a per-user random salt.
* Sessions are stateless: a signed token (``payload.signature``) is issued on
  login/registration and presented back as ``Authorization: Bearer <token>``.
  The signature is an HMAC-SHA256 over the payload using ``config.SECRET_KEY``.
* No third-party crypto dependency is required — only the Python standard
  library — which keeps the container image tiny and the supply chain short.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from .config import (
    MIN_PASSWORD_LENGTH,
    PBKDF2_ITERATIONS,
    SECRET_KEY,
    TOKEN_TTL_DAYS,
)

TOKEN_PREFIX = "instafeed"


class AuthError(Exception):
    """Raised for any authentication/authorisation failure."""


# --- password helpers --------------------------------------------------------


def hash_password(password: str, *, salt: str | None = None) -> tuple[str, str]:
    """Return ``(hash_hex, salt_hex)`` for the given plaintext password."""
    if not isinstance(password, str) or not password:
        raise AuthError("password is required")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LENGTH} characters long")
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    )
    return digest.hex(), salt_hex


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Constant-time verification of a plaintext password against a stored hash."""
    if not password_hash or not salt:
        return False
    try:
        candidate, _ = hash_password(password, salt=salt)
    except AuthError:
        return False
    return hmac.compare_digest(candidate, password_hash)


# --- token helpers -----------------------------------------------------------


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _sign(payload: str) -> str:
    digest = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(user_id: int, username: str, ttl_days: int | None = None) -> str:
    """Issue a signed session token for a user."""
    ttl = TOKEN_TTL_DAYS if ttl_days is None else ttl_days
    payload = {
        "uid": int(user_id),
        "usr": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + max(0, ttl) * 86_400,
        "jti": secrets.token_urlsafe(9),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{TOKEN_PREFIX}.{body}.{_sign(body)}"


def decode_token(token: str) -> dict[str, Any]:
    """Validate a session token and return its payload.

    Raises :class:`AuthError` when the token is malformed, tampered with or
    expired.
    """
    if not token or not isinstance(token, str):
        raise AuthError("missing token")
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise AuthError("malformed token")
    _, body, signature = parts
    if not hmac.compare_digest(_sign(body), signature):
        raise AuthError("invalid token signature")
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError) as exc:
        raise AuthError("malformed token payload") from exc
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise AuthError("token expired")
    return payload


def user_id_from_token(token: str) -> int:
    """Extract the numeric user id carried by a valid token."""
    return int(decode_token(token)["uid"])


__all__ = [
    "AuthError",
    "create_token",
    "decode_token",
    "hash_password",
    "user_id_from_token",
    "verify_password",
]
