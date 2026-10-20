"""Central configuration for Instafeed.

Every tunable lives here and is read from the environment exactly once at
import time. Nothing else in the codebase calls ``os.environ`` directly,
so the whole app can be reconfigured from a single place (env vars,
``.env`` file, or a container orchestrator).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).

    Existing environment variables always win over the file, which keeps
    container/CI configuration authoritative.
    """
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


_load_dotenv()

# --- Storage -----------------------------------------------------------------
DB_PATH = Path(os.environ.get("INSTAFEED_DB_PATH", BASE_DIR / "instafeed.db"))

# --- Application -------------------------------------------------------------
APP_NAME = "Instafeed"
APP_TAGLINE = "Your Instagram video feed, distilled."
APP_VERSION = "2.0.0"

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "INSTAFEED_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if origin.strip()
]

# --- Authentication ----------------------------------------------------------
# The signing secret is persisted next to the database so that tokens stay
# valid across restarts even when no environment variable is provided.
_SECRET_FILE = DB_PATH.with_suffix(".secret")

TOKEN_TTL_DAYS = _env_int("INSTAFEED_TOKEN_TTL_DAYS", 30)
PBKDF2_ITERATIONS = _env_int("INSTAFEED_PBKDF2_ITERATIONS", 240_000)
MIN_PASSWORD_LENGTH = _env_int("INSTAFEED_MIN_PASSWORD_LENGTH", 8)


def _load_or_create_secret() -> str:
    env_secret = os.environ.get("INSTAFEED_SECRET_KEY")
    if env_secret:
        return env_secret
    try:
        if _SECRET_FILE.is_file():
            existing = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except OSError:
        pass
    import secrets

    generated = secrets.token_urlsafe(48)
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(generated, encoding="utf-8")
    except OSError:
        pass
    return generated


SECRET_KEY = _load_or_create_secret()

# --- Instagram ---------------------------------------------------------------
INSTAGRAM_LOGIN = os.environ.get("INSTAGRAM_LOGIN", "").strip()
INSTAGRAM_PASSWORD = os.environ.get("INSTAGRAM_PASSWORD", "").strip()
INSTAGRAM_REQUEST_DELAY = float(os.environ.get("INSTAGRAM_REQUEST_DELAY", "1.5"))
INSTAGRAM_MAX_RETRIES = _env_int("INSTAGRAM_MAX_RETRIES", 3)

# --- Scheduler ---------------------------------------------------------------
SCHEDULER_ENABLED = _env_bool("INSTAFEED_SCHEDULER", True)
POLL_INTERVAL_MINUTES = _env_int("POLL_INTERVAL_MINUTES", 15)
POLL_LATEST_LIMIT = _env_int("POLL_LATEST_LIMIT", 10)

# --- Pagination --------------------------------------------------------------
DEFAULT_PAGE_SIZE = _env_int("INSTAFEED_PAGE_SIZE", 24)
MAX_PAGE_SIZE = _env_int("INSTAFEED_MAX_PAGE_SIZE", 100)

__all__ = [
    "APP_NAME",
    "APP_TAGLINE",
    "APP_VERSION",
    "BASE_DIR",
    "CORS_ORIGINS",
    "DB_PATH",
    "DEFAULT_PAGE_SIZE",
    "INSTAGRAM_LOGIN",
    "INSTAGRAM_MAX_RETRIES",
    "INSTAGRAM_PASSWORD",
    "INSTAGRAM_REQUEST_DELAY",
    "MAX_PAGE_SIZE",
    "MIN_PASSWORD_LENGTH",
    "PBKDF2_ITERATIONS",
    "POLL_INTERVAL_MINUTES",
    "POLL_LATEST_LIMIT",
    "SCHEDULER_ENABLED",
    "SECRET_KEY",
    "TOKEN_TTL_DAYS",
]
