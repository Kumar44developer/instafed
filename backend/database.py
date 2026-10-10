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

            CREATE TABLE IF NOT EXISTS videos (
                id            TEXT PRIMARY KEY,   -- shortcode
                username      TEXT NOT NULL,
                video_url     TEXT NOT NULL,
                thumbnail_url TEXT DEFAULT '',
                caption       TEXT DEFAULT '',
                likes         INTEGER DEFAULT 0,
                comments      INTEGER DEFAULT 0,
                taken_at      TEXT DEFAULT '',
                fetched_at    TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (username) REFERENCES subscriptions(username)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(username);

            CREATE TABLE IF NOT EXISTS poll_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at     TEXT DEFAULT (datetime('now')),
                total_new  INTEGER DEFAULT 0
            );
            """
        )

def add_subscription(username: str, full_name: str = "", profile_pic: str = "",
                     followers: int = 0) -> dict:
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO subscriptions (username, full_name, profile_pic, followers)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                   full_name=excluded.full_name,
                   profile_pic=excluded.profile_pic,
                   followers=excluded.followers""",
            (username.lower(), full_name, profile_pic, followers),
        )
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE username = ?", (username.lower(),)
        ).fetchone()
    return dict(row)

def remove_subscription(username: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE username = ?", (username.lower(),)
        )
        conn.execute("DELETE FROM videos WHERE username = ?", (username.lower(),))
        return cur.rowcount > 0

def list_subscriptions() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM videos v WHERE v.username = s.username)
                      AS cached_videos
               FROM subscriptions s ORDER BY subscribed_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]

def is_subscribed(username: str) -> bool:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM subscriptions WHERE username = ?", (username.lower(),)
        ).fetchone()
    return row is not None

def upsert_videos(username: str, videos: list[dict]) -> int:
    """On-demand full fetch: insert new rows, refresh likes/comments on existing."""
