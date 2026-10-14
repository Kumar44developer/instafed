"""Instafeed — FastAPI backend.

Workflow:
  1. GET  /api/search?q=<name>              → find Instagram handles
  2. POST /api/subscribe {username}         → subscribe to a handle
  3. GET  /api/subscriptions/{user}/videos  → fetch EVERY video of that user
  4. GET  /api/feed                         → videos of all subscribed users
  5. POST /api/poll                         → check subs for NEW videos (dedupe)
     + background scheduler polls automatically every POLL_INTERVAL_MINUTES


Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations


import os
from pathlib import Path


from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
