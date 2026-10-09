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
