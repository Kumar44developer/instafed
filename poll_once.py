"""One-shot poll run — drop this into any cron (system cron, Vercel Cron, ...).

Usage:
    python scripts/poll_once.py [limit_per_user]

Equivalent to POST /api/poll. Exits 0 on success.
"""
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))


from backend import database as db
from backend.scheduler import run_poll


db.init_db()
limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
summary = run_poll(limit=limit)
print(
    f"polled {len(summary['per_user'])} subscription(s) "
    f"at {summary['ran_at']}; {summary['total_new']} new video(s)"
)
