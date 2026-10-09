"""SQLite storage layer for Instafeed.

Stores subscriptions and a local cache of fetched videos so repeated
feed loads don't re-hit Instagram. Also keeps a poll log so the UI can
show when the last automatic check ran and how many new videos it found.
"""
import sqlite3
import threading
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "instafeed.db"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                username      TEXT PRIMARY KEY,
                full_name     TEXT DEFAULT '',
                profile_pic   TEXT DEFAULT '',
                followers     INTEGER DEFAULT 0,
                subscribed_at TEXT DEFAULT (datetime('now'))
            );
