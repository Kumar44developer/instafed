"""Automatic polling pipeline for Instafeed.


The core loop mirrors a classic cron job:

    for each subscribed user:
        fetch their LATEST videos only (default 10)      # fast, rate-limit friendly
        insert only the ones we don't already have       # dedupe by video id
    frontend just reads the DB, newest first             # nothing new -> nothing changes

`run_poll()` is also exposed as POST /api/poll so it can be triggered by
Vercel Cron / a system cron job instead of (or in addition to) the
in-process scheduler thread.
"""
from __future__ import annotations


import logging
import os
import threading
import time
from datetime import datetime, timezone


from . import database as db
from . import instagram as ig


log = logging.getLogger("instafeed.scheduler")


POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "15"))
POLL_LATEST_LIMIT = int(os.environ.get("POLL_LATEST_LIMIT", "10"))

def run_poll(limit: int | None = None) -> dict:
    """One poll cycle: fetch latest videos per subscription, keep only new ones.

    Returns a summary like:
        {"ran_at": "...", "total_new": 3,
         "per_user": {"cristiano": {"checked": 10, "new": 2}, ...}}
    """

    limit = limit or POLL_LATEST_LIMIT
    subs = db.list_subscriptions()
    per_user: dict = {}
    total_new = 0
    for s in subs:
        username = s["username"]
        try:
            videos = ig.get_videos(username, limit=limit)
        except ig.InstagramError as exc:
            per_user[username] = {"error": str(exc)}
            continue
