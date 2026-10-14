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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database as db
from . import instagram as ig
from . import scheduler

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Instafeed", version="1.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    scheduler.start_if_enabled()



class SubscribeRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=30)

@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    """Step 1 — search Instagram handles by username."""
    try:
        results = ig.search_users(q)
    except ig.InstagramError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for r in results:
        r["subscribed"] = db.is_subscribed(r["username"])
    return {"query": q, "count": len(results), "results": results}
