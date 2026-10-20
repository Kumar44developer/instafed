#!/usr/bin/env python3
"""Seed a fresh Instafeed installation with a demo account and sample content.

Usage:
    python scripts/seed_demo.py [username] [password]

Creates an account (default ``demo`` / ``demo1234``), subscribes it to a
handful of creators and pulls their (demo-mode) videos so the dashboard has
something to show the moment you open it.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from backend import auth  # noqa: E402
from backend import database as db  # noqa: E402
from backend import instagram as ig  # noqa: E402

CREATORS = ("nasa", "natgeo", "nba", "nintendo", "nike", "netflix")


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "demo"
    password = sys.argv[2] if len(sys.argv) > 2 else "demo1234"

    db.init_db()

    if db.get_user_by_username(username):
        print(f"@{username} already exists — nothing to do.")
        return 0

    password_hash, salt = auth.hash_password(password)
    user = db.create_user(username, password_hash, salt)

    for handle in CREATORS:
        try:
            profile = ig.get_provider().get_profile(handle)
        except ig.InstagramError as exc:
            print(f"  ! skipped @{handle}: {exc}")
            continue
        db.add_subscription(
            user["id"],
            profile["username"],
            profile.get("full_name", ""),
            profile.get("profile_pic", ""),
            profile.get("followers", 0),
            profile.get("is_verified", False),
        )
        videos = ig.get_provider().get_videos(handle, limit=12)
        db.upsert_videos(user["id"], handle, videos)
        print(f"  ✓ @{handle}: {len(videos)} video(s)")

    print(f"\nSeeded @{username} — sign in with '{username}' / '{password}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
