"""One-shot poll run — drop this into any cron (system cron, Vercel Cron, ...).

Usage:
    python scripts/poll_once.py [limit_per_user]

Equivalent to POST /api/poll. Exits 0 on success.
"""
import os
import sys
