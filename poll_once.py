"""One-shot poll run — drop this into any cron (system cron, Vercel Cron, ...).

Usage:
    python scripts/poll_once.py [limit_per_user]

Equivalent to POST /api/poll. Exits 0 on success.
"""
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))
