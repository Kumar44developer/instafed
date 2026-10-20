"""Automatic polling pipeline for Instafeed.

The loop mirrors a classic cron job:

    for every user:
        for every subscription of that user:
            fetch the LATEST videos only (default 10)   # fast, rate-limit friendly
            insert only the ones we do not already have  # dedupe by video id
    the frontend simply reads the database, newest first

``run_poll()`` is also exposed as ``POST /api/poll`` so an external cron
(Vercel Cron, GitHub Actions, system cron) can trigger it instead of, or in
addition to, the in-process daemon thread.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from . import config
from . import database as db
from . import instagram as ig

log = logging.getLogger("instafeed.scheduler")


def run_poll(user_id: int | None = None, limit: int | None = None) -> dict:
    """Run one poll cycle.

    Parameters
    ----------
    user_id:
        Restrict the poll to a single user. ``None`` polls every user.
    limit:
        How many latest videos to check per subscription. Defaults to
        ``config.POLL_LATEST_LIMIT``.

    Returns a summary::

        {
          "ran_at": "2024-05-01T10:00:00+00:00",
          "total_new": 3,
          "checked": 42,
          "errors": 0,
          "duration_ms": 8123,
          "per_user": {"1": {"username": "...", "new": 2, "checked": 10}},
        }
    """
    started = time.monotonic()
    limit = limit or config.POLL_LATEST_LIMIT

    users = [user_id] if user_id is not None else _all_user_ids()
    per_user: dict[str, dict] = {}
    total_new = 0
    checked = 0
    errors = 0

    for uid in users:
        subs = db.list_subscriptions(uid)
        user_summary: dict[str, dict] = {}
        for subscription in subs:
            username = subscription["username"]
            try:
                videos = ig.get_videos(username, limit=limit)
            except ig.InstagramError as exc:
                errors += 1
                user_summary[username] = {"error": str(exc)}
                log.warning("poll @%s failed: %s", username, exc)
                continue
            new = db.insert_new_videos(uid, username, videos)
            user_summary[username] = {"checked": len(videos), "new": new}
            checked += len(videos)
            total_new += new
            if new:
                log.info("poll @%s: %d new video(s)", username, new)
        if user_summary:
            per_user[str(uid)] = user_summary
        db.record_poll(
            uid,
            total_new=sum(v.get("new", 0) for v in user_summary.values()),
            checked=sum(v.get("checked", 0) for v in user_summary.values()),
            errors=sum(1 for v in user_summary.values() if "error" in v),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "total_new": total_new,
        "checked": checked,
        "errors": errors,
        "duration_ms": duration_ms,
        "per_user": per_user,
    }


def _all_user_ids() -> list[int]:
    """Every user id that owns at least one subscription."""
    with db._tx() as conn:  # noqa: SLF001 - intentional internal reuse
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM subscriptions ORDER BY user_id"
        ).fetchall()
    return [int(r["user_id"]) for r in rows]


class PollScheduler:
    """Daemon thread that runs :func:`run_poll` every interval minutes."""

    def __init__(self, interval_minutes: int = config.POLL_INTERVAL_MINUTES):
        self.interval_seconds = max(1, interval_minutes) * 60
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="instafeed-poll", daemon=True)
        self._thread.start()
        log.info("poll scheduler started (every %d min)", self.interval_seconds // 60)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Small initial delay so the app finishes booting before the first hit.
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                summary = run_poll()
                log.info("poll cycle done: %d new video(s)", summary["total_new"])
            except Exception as exc:  # never let one bad cycle kill the loop
                log.warning("poll cycle failed: %s", exc)
            if self._stop.wait(self.interval_seconds):
                return


_scheduler = PollScheduler()


def start_if_enabled() -> None:
    """Start the in-process scheduler unless ``INSTAFEED_SCHEDULER=0``."""
    if os.environ.get("INSTAFEED_SCHEDULER", "1") != "0" and config.SCHEDULER_ENABLED:
        _scheduler.start()


def stop() -> None:
    _scheduler.stop()


__all__ = ["PollScheduler", "run_poll", "start_if_enabled", "stop"]
