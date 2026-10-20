#!/usr/bin/env python3
"""One-shot poll run — drop this into any cron (system cron, GitHub Actions, ...).

Usage:
    python scripts/poll_once.py [limit_per_user]

Equivalent to ``POST /api/poll``. Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from backend import database as db  # noqa: E402
from backend.scheduler import run_poll  # noqa: E402


def main() -> int:
    db.init_db()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    summary = run_poll(limit=limit)
    print(
        f"polled {len(summary['per_user'])} user(s) at {summary['ran_at']}; "
        f"{summary['total_new']} new video(s), {summary['checked']} checked, "
        f"{summary['errors']} error(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
