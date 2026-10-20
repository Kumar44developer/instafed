"""SQLite storage layer for Instafeed.

The database holds four kinds of state:

``users``          accounts that own subscriptions, videos and bookmarks.
``subscriptions``  the Instagram handles a user follows.
``videos``         a local, de-duplicated cache of fetched videos.
``bookmarks``      videos a user saved for later.
``poll_log``       an audit trail of every poll cycle (used by the UI).

All writes go through a single re-entrant lock and a per-call connection so
the module is safe to use from FastAPI's threadpool *and* from the daemon
scheduler thread.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now')),
    last_seen_at  TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    username      TEXT NOT NULL,
    full_name     TEXT DEFAULT '',
    profile_pic   TEXT DEFAULT '',
    followers     INTEGER DEFAULT 0,
    is_verified   INTEGER DEFAULT 0,
    subscribed_at TEXT DEFAULT (datetime('now')),
    UNIQUE (user_id, username),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS videos (
    id            TEXT NOT NULL,
    user_id       INTEGER NOT NULL,
    username      TEXT NOT NULL,
    video_url     TEXT NOT NULL,
    thumbnail_url TEXT DEFAULT '',
    caption       TEXT DEFAULT '',
    likes         INTEGER DEFAULT 0,
    comments      INTEGER DEFAULT 0,
    views         INTEGER DEFAULT 0,
    duration      REAL DEFAULT 0,
    permalink     TEXT DEFAULT '',
    taken_at      TEXT DEFAULT '',
    fetched_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_videos_user     ON videos(user_id);
CREATE INDEX IF NOT EXISTS idx_videos_username ON videos(user_id, username);
CREATE INDEX IF NOT EXISTS idx_videos_taken    ON videos(user_id, taken_at DESC);

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id       INTEGER NOT NULL,
    video_id      TEXT NOT NULL,
    note          TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, video_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS poll_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    ran_at     TEXT DEFAULT (datetime('now')),
    total_new  INTEGER DEFAULT 0,
    checked    INTEGER DEFAULT 0,
    errors     INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_poll_user ON poll_log(user_id, id DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def _tx() -> Iterator[sqlite3.Connection]:
    """Serialised, auto-committing transaction context."""
    with _lock:
        conn = _connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create every table/index if they do not exist yet (idempotent)."""
    if db_path is not None:
        global DB_PATH
        DB_PATH = db_path
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _tx() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- users -------------------------------------------------------------------


def create_user(username: str, password_hash: str, salt: str, email: str = "") -> dict:
    with _tx() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash, salt) VALUES (?, ?, ?, ?)",
            (username.strip().lower(), email.strip(), password_hash, salt),
        )
        user_id = int(cursor.lastrowid)
    return get_user(user_id)  # type: ignore[return-value]


def get_user(user_id: int) -> dict | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT id, username, email, created_at, last_seen_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def user_count() -> int:
    with _tx() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])


def touch_user(user_id: int) -> None:
    with _tx() as conn:
        conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (_now(), user_id))


def delete_user(user_id: int) -> bool:
    with _tx() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cursor.rowcount > 0


# --- subscriptions -----------------------------------------------------------


def add_subscription(
    user_id: int,
    username: str,
    full_name: str = "",
    profile_pic: str = "",
    followers: int = 0,
    is_verified: bool = False,
) -> dict:
    username = username.strip().lstrip("@").lower()
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions
                (user_id, username, full_name, profile_pic, followers, is_verified)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, username) DO UPDATE SET
                full_name   = excluded.full_name,
                profile_pic = excluded.profile_pic,
                followers   = excluded.followers,
                is_verified = excluded.is_verified
            """,
            (user_id, username, full_name, profile_pic, int(followers), int(is_verified)),
        )
    return get_subscription(user_id, username)  # type: ignore[return-value]


def remove_subscription(user_id: int, username: str) -> bool:
    username = username.strip().lstrip("@").lower()
    with _tx() as conn:
        cursor = conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND username = ?",
            (user_id, username),
        )
        conn.execute("DELETE FROM videos WHERE user_id = ? AND username = ?", (user_id, username))
    return cursor.rowcount > 0


def get_subscription(user_id: int, username: str) -> dict | None:
    username = username.strip().lstrip("@").lower()
    with _tx() as conn:
        row = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM videos v
                            WHERE v.user_id = s.user_id AND v.username = s.username)
                            AS cached_videos
               FROM subscriptions s
               WHERE s.user_id = ? AND s.username = ?""",
            (user_id, username),
        ).fetchone()
    return dict(row) if row else None


def list_subscriptions(user_id: int) -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM videos v
                            WHERE v.user_id = s.user_id AND v.username = s.username)
                            AS cached_videos
               FROM subscriptions s
               WHERE s.user_id = ?
               ORDER BY s.subscribed_at DESC""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def is_subscribed(user_id: int, username: str) -> bool:
    return get_subscription(user_id, username) is not None


# --- videos ------------------------------------------------------------------

_VIDEO_COLUMNS = (
    "id, username, video_url, thumbnail_url, caption, likes, comments, "
    "views, duration, permalink, taken_at, fetched_at"
)


def _video_payload(video: dict, user_id: int) -> dict:
    return {
        "id": str(video.get("id") or ""),
        "user_id": user_id,
        "username": (video.get("username") or "").strip().lstrip("@").lower(),
        "video_url": video.get("video_url") or "",
        "thumbnail_url": video.get("thumbnail_url") or "",
        "caption": video.get("caption") or "",
        "likes": int(video.get("likes") or 0),
        "comments": int(video.get("comments") or 0),
        "views": int(video.get("views") or 0),
        "duration": float(video.get("duration") or 0),
        "permalink": video.get("permalink") or "",
        "taken_at": video.get("taken_at") or "",
    }


def upsert_videos(user_id: int, username: str, videos: Sequence[dict]) -> int:
    """Insert videos and refresh engagement counters on existing rows."""
    username = username.strip().lstrip("@").lower()
    rows = [{**_video_payload(v, user_id), "username": username} for v in videos]
    rows = [r for r in rows if r["id"]]
    if not rows:
        return 0
    with _tx() as conn:
        conn.executemany(
            """
            INSERT INTO videos
                (id, user_id, username, video_url, thumbnail_url, caption,
                 likes, comments, views, duration, permalink, taken_at, fetched_at)
            VALUES
                (:id, :user_id, :username, :video_url, :thumbnail_url, :caption,
                 :likes, :comments, :views, :duration, :permalink, :taken_at,
                 datetime('now'))
            ON CONFLICT(user_id, id) DO UPDATE SET
                likes         = excluded.likes,
                comments      = excluded.comments,
                views         = excluded.views,
                caption       = excluded.caption,
                thumbnail_url = excluded.thumbnail_url,
                video_url     = excluded.video_url,
                taken_at      = excluded.taken_at,
                fetched_at    = datetime('now')
            """,
            rows,
        )
    return len(rows)


def insert_new_videos(user_id: int, username: str, videos: Sequence[dict]) -> int:
    """Insert only videos that are not cached yet. Returns the number of new rows."""
    username = username.strip().lstrip("@").lower()
    if not videos:
        return 0
    with _tx() as conn:
        existing = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM videos WHERE user_id = ? AND username = ?",
                (user_id, username),
            ).fetchall()
        }
        fresh = [v for v in videos if v.get("id") and v["id"] not in existing]
        if fresh:
            rows = [{**_video_payload(v, user_id), "username": username} for v in fresh]
            conn.executemany(
                """
                INSERT INTO videos
                    (id, user_id, username, video_url, thumbnail_url, caption,
                     likes, comments, views, duration, permalink, taken_at, fetched_at)
                VALUES
                    (:id, :user_id, :username, :video_url, :thumbnail_url, :caption,
                     :likes, :comments, :views, :duration, :permalink, :taken_at,
                     datetime('now'))
                """,
                rows,
            )
    return len(fresh)


def get_video(user_id: int, video_id: str) -> dict | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE user_id = ? AND id = ?", (user_id, video_id)
        ).fetchone()
    return dict(row) if row else None


def get_videos(user_id: int, username: str | None = None, limit: int = 500) -> list[dict]:
    """Convenience wrapper: every cached video of one (or all) creators."""
    return query_videos(user_id, username=username, limit=limit, sort="new")


def query_videos(
    user_id: int,
    *,
    username: str | None = None,
    search: str | None = None,
    bookmarked_only: bool = False,
    sort: str = "new",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Filtered, sorted, paginated video feed for one user."""
    where = ["v.user_id = ?"]
    params: list[Any] = [user_id]
    if username:
        where.append("v.username = ?")
        params.append(username.strip().lstrip("@").lower())
    if search:
        where.append("(v.caption LIKE ? OR v.username LIKE ?)")
        needle = f"%{search.strip()}%"
        params.extend([needle, needle])
    if bookmarked_only:
        where.append(
            "EXISTS (SELECT 1 FROM bookmarks b WHERE b.user_id = v.user_id AND b.video_id = v.id)"
        )
    order = {
        "new": "v.taken_at DESC, v.fetched_at DESC",
        "old": "v.taken_at ASC, v.fetched_at ASC",
        "popular": "v.likes DESC, v.views DESC",
        "views": "v.views DESC, v.likes DESC",
        "reactions": "(v.likes + v.comments) DESC",
    }.get(sort, "v.taken_at DESC, v.fetched_at DESC")

    sql = f"""
        SELECT v.*,
               EXISTS (SELECT 1 FROM bookmarks b
                       WHERE b.user_id = v.user_id AND b.video_id = v.id) AS bookmarked
        FROM videos v
        WHERE {" AND ".join(where)}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    params.extend([int(limit), int(offset)])
    with _tx() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_videos(
    user_id: int,
    *,
    username: str | None = None,
    search: str | None = None,
    bookmarked_only: bool = False,
) -> int:
    where = ["v.user_id = ?"]
    params: list[Any] = [user_id]
    if username:
        where.append("v.username = ?")
        params.append(username.strip().lstrip("@").lower())
    if search:
        where.append("(v.caption LIKE ? OR v.username LIKE ?)")
        needle = f"%{search.strip()}%"
        params.extend([needle, needle])
    if bookmarked_only:
        where.append(
            "EXISTS (SELECT 1 FROM bookmarks b WHERE b.user_id = v.user_id AND b.video_id = v.id)"
        )
    with _tx() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM videos v WHERE {' AND '.join(where)}", params
        ).fetchone()
    return int(row["c"])


def delete_video(user_id: int, video_id: str) -> bool:
    with _tx() as conn:
        cursor = conn.execute(
            "DELETE FROM videos WHERE user_id = ? AND id = ?", (user_id, video_id)
        )
        conn.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND video_id = ?", (user_id, video_id)
        )
    return cursor.rowcount > 0


# --- bookmarks ---------------------------------------------------------------


def add_bookmark(user_id: int, video_id: str, note: str = "") -> dict | None:
    with _tx() as conn:
        conn.execute(
            """INSERT INTO bookmarks (user_id, video_id, note) VALUES (?, ?, ?)
               ON CONFLICT(user_id, video_id) DO UPDATE SET note = excluded.note""",
            (user_id, video_id, note),
        )
    return get_bookmark(user_id, video_id)


def remove_bookmark(user_id: int, video_id: str) -> bool:
    with _tx() as conn:
        cursor = conn.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND video_id = ?", (user_id, video_id)
        )
    return cursor.rowcount > 0


def get_bookmark(user_id: int, video_id: str) -> dict | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM bookmarks WHERE user_id = ? AND video_id = ?",
            (user_id, video_id),
        ).fetchone()
    return dict(row) if row else None


def list_bookmarks(user_id: int) -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            """SELECT b.*, v.username, v.caption, v.thumbnail_url, v.video_url,
                      v.likes, v.views, v.taken_at, v.permalink
               FROM bookmarks b
               LEFT JOIN videos v ON v.user_id = b.user_id AND v.id = b.video_id
               WHERE b.user_id = ?
               ORDER BY b.created_at DESC""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- poll log ----------------------------------------------------------------


def record_poll(
    user_id: int | None,
    total_new: int,
    checked: int = 0,
    errors: int = 0,
    duration_ms: int = 0,
) -> None:
    with _tx() as conn:
        conn.execute(
            """INSERT INTO poll_log
                   (user_id, total_new, checked, errors, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, int(total_new), int(checked), int(errors), int(duration_ms)),
        )


def last_poll(user_id: int | None = None) -> dict | None:
    with _tx() as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT ran_at, total_new, checked, errors FROM poll_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT ran_at, total_new, checked, errors FROM poll_log "
                "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
    return dict(row) if row else None


def poll_history(user_id: int, limit: int = 20) -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            """SELECT ran_at, total_new, checked, errors, duration_ms
               FROM poll_log WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


# --- statistics --------------------------------------------------------------


def user_stats(user_id: int) -> dict:
    """Aggregate numbers powering the dashboard."""
    with _tx() as conn:
        subs = conn.execute(
            "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        videos = conn.execute(
            "SELECT COUNT(*) AS c FROM videos WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        marks = conn.execute(
            "SELECT COUNT(*) AS c FROM bookmarks WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        totals = conn.execute(
            """SELECT COALESCE(SUM(likes), 0)    AS likes,
                      COALESCE(SUM(views), 0)    AS views,
                      COALESCE(SUM(comments), 0) AS comments
               FROM videos WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        top = conn.execute(
            """SELECT username,
                      COUNT(*)          AS videos,
                      COALESCE(SUM(likes), 0) AS likes,
                      COALESCE(SUM(views), 0) AS views
               FROM videos WHERE user_id = ?
               GROUP BY username
               ORDER BY videos DESC, likes DESC
               LIMIT 5""",
            (user_id,),
        ).fetchall()
        timeline = conn.execute(
            """SELECT substr(taken_at, 1, 10) AS day, COUNT(*) AS videos
               FROM videos WHERE user_id = ? AND taken_at <> ''
               GROUP BY day ORDER BY day DESC LIMIT 14""",
            (user_id,),
        ).fetchall()
    return {
        "subscriptions": int(subs),
        "videos": int(videos),
        "bookmarks": int(marks),
        "total_likes": int(totals["likes"]),
        "total_views": int(totals["views"]),
        "total_comments": int(totals["comments"]),
        "top_creators": [dict(r) for r in top],
        "timeline": [dict(r) for r in reversed(timeline)],
    }
