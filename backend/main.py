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

@app.post("/api/subscribe", status_code=201)
def subscribe(body: SubscribeRequest):
    """Step 1.2 — subscribe to a username (stores it locally)."""
    username = body.username.strip().lstrip("@").lower()
    try:
        profile = ig.get_profile(username)
    except ig.InstagramError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sub = db.add_subscription(
        profile["username"], profile["full_name"],
        profile["profile_pic"], profile["followers"],
    )
    return {"message": f"subscribed to @{profile['username']}", "subscription": sub}


@app.get("/api/subscriptions")
def subscriptions():
    return {"subscriptions": db.list_subscriptions()}

@app.delete("/api/subscriptions/{username}")
def unsubscribe(username: str):
    if not db.remove_subscription(username):
        raise HTTPException(status_code=404, detail=f"not subscribed to @{username}")
    return {"message": f"unsubscribed from @{username}"}

@app.get("/api/subscriptions/{username}/videos")
def user_videos(username: str, refresh: bool = False,
                limit: int | None = Query(None, ge=1)):
    """Step 1.3 — get EACH AND EVERY video of a subscribed username.

    Videos are cached in SQLite; pass ?refresh=true to re-fetch from
    Instagram. ?limit=N caps the fetch (default: all videos).
    """

    username = username.strip().lstrip("@").lower()
    if not db.is_subscribed(username):
        raise HTTPException(
            status_code=409,
            detail=f"subscribe to @{username} first (POST /api/subscribe)",
        )
    cached = db.get_videos(username)
    if cached and not refresh:
        return {"username": username, "count": len(cached),
                "source": "cache", "videos": cached}
    try:
        videos = ig.get_videos(username, limit=limit)
    except ig.InstagramError as exc:
        if cached:
            return {"username": username, "count": len(cached), "source": "cache",
                    "warning": str(exc), "videos": cached}
        raise HTTPException(status_code=502, detail=str(exc)) from exc
