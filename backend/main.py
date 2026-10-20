"""Instafeed — FastAPI application.

Your Instagram video feed, distilled: search handles, subscribe, and let the
scheduler pull every reel into a single, searchable, bookmarkable feed.

Route map
---------
``POST   /api/auth/register``      create an account
``POST   /api/auth/login``         sign in
``GET    /api/auth/me``            current session
``DELETE /api/auth/me``            delete the account
``GET    /api/search``             find Instagram handles
``POST   /api/subscribe``          subscribe to a handle
``GET    /api/subscriptions``      list subscriptions
``DELETE /api/subscriptions/{u}``  unsubscribe
``GET    /api/subscriptions/{u}/videos``  every video of one handle
``GET    /api/feed``               the combined, filtered, paginated feed
``DELETE /api/videos/{id}``        drop one video from the cache
``GET    /api/bookmarks``          saved videos
``POST   /api/bookmarks``          save a video
``DELETE /api/bookmarks/{id}``     remove a saved video
``GET    /api/stats``              dashboard aggregates
``GET    /api/feed/export``        export the feed (json / csv)
``GET    /api/digest``             markdown digest of the newest videos
``POST   /api/poll``               run a poll cycle now
``GET    /api/poll/status``        last poll summary
``GET    /api/health``             liveness probe
``GET    /api/config``             public runtime configuration

Run locally:  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import csv
import io
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth, config, scheduler
from . import database as db
from . import instagram as ig
from .deps import CurrentUser, OptionalUser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("instafeed")

FRONTEND_DIR = config.BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    scheduler.start_if_enabled()
    log.info(
        "%s %s ready — provider=%s",
        config.APP_NAME,
        config.APP_VERSION,
        "demo" if ig.demo_mode_enabled() else "live",
    )
    yield
    scheduler.stop()


app = FastAPI(
    title=config.APP_NAME,
    description=(
        "Instafeed turns the Instagram handles you care about into one "
        "searchable, bookmarkable video feed."
    ),
    version=config.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=256)
    email: str = Field("", max_length=254)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise ValueError(
                "username may only contain letters, numbers, dots, dashes and underscores"
            )
        return value


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SubscribeRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)

    @field_validator("username")
    @classmethod
    def _clean(cls, value: str) -> str:
        return value.strip().lstrip("@").lower()


class BookmarkRequest(BaseModel):
    video_id: str = Field(..., min_length=1, max_length=64)
    note: str = Field("", max_length=500)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED, tags=["auth"])
def register(body: RegisterRequest) -> dict:
    """Create an account and return a ready-to-use session token."""
    if db.get_user_by_username(body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"@{body.username} is already taken",
        )
    try:
        password_hash, salt = auth.hash_password(body.password)
    except auth.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    user = db.create_user(body.username, password_hash, salt, body.email)
    token = auth.create_token(user["id"], user["username"])
    return {"token": token, "user": user}


@app.post("/api/auth/login", tags=["auth"])
def login(body: LoginRequest) -> dict:
    """Exchange credentials for a session token."""
    record = db.get_user_by_username(body.username)
    if record is None or not auth.verify_password(
        body.password, record["password_hash"], record["salt"]
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = db.get_user(record["id"])
    token = auth.create_token(record["id"], record["username"])
    return {"token": token, "user": user}


@app.get("/api/auth/me", tags=["auth"])
def me(user: CurrentUser) -> dict:
    """Return the currently authenticated profile."""
    return {"user": user}


@app.delete("/api/auth/me", tags=["auth"])
def delete_account(user: CurrentUser) -> dict:
    """Permanently delete the account and every artefact it owns."""
    db.delete_user(user["id"])
    return {"message": f"account @{user['username']} deleted"}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@app.get("/api/search", tags=["discovery"])
def search(
    user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(15, ge=1, le=50),
) -> dict:
    """Step 1 — find Instagram handles by name."""
    try:
        results = ig.get_provider().search_users(q, limit=limit)
    except ig.InstagramError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    for result in results:
        result["subscribed"] = db.is_subscribed(user["id"], result["username"])
    return {"query": q, "count": len(results), "results": results}


@app.post("/api/subscribe", status_code=status.HTTP_201_CREATED, tags=["subscriptions"])
def subscribe(body: SubscribeRequest, user: CurrentUser) -> dict:
    """Step 2 — subscribe to a handle (stored locally, then polled)."""
    try:
        profile = ig.get_provider().get_profile(body.username)
    except ig.InstagramError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    subscription = db.add_subscription(
        user["id"],
        profile["username"],
        profile.get("full_name", ""),
        profile.get("profile_pic", ""),
        profile.get("followers", 0),
        profile.get("is_verified", False),
    )
    return {
        "message": f"subscribed to @{profile['username']}",
        "subscription": subscription,
    }


@app.get("/api/subscriptions", tags=["subscriptions"])
def subscriptions(user: CurrentUser) -> dict:
    """Every handle the current user follows."""
    return {"subscriptions": db.list_subscriptions(user["id"])}


@app.delete("/api/subscriptions/{username}", tags=["subscriptions"])
def unsubscribe(username: str, user: CurrentUser) -> dict:
    """Stop following a handle and drop its cached videos."""
    if not db.remove_subscription(user["id"], username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"not subscribed to @{username}",
        )
    return {"message": f"unsubscribed from @{username}"}


@app.get("/api/subscriptions/{username}/videos", tags=["subscriptions"])
def user_videos(
    username: str,
    user: CurrentUser,
    refresh: bool = False,
    limit: int | None = Query(None, ge=1, le=1000),
) -> dict:
    """Step 3 — every video of one subscribed handle.

    Results are cached in SQLite; pass ``?refresh=true`` to re-fetch from
    Instagram. ``?limit=N`` caps the fetch (default: all videos).
    """
    username = username.strip().lstrip("@").lower()
    if not db.is_subscribed(user["id"], username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"subscribe to @{username} first (POST /api/subscribe)",
        )
    cached = db.query_videos(user["id"], username=username, limit=1000, sort="new")
    if cached and not refresh:
        return {
            "username": username,
            "count": len(cached),
            "source": "cache",
            "videos": cached,
        }
    try:
        videos = ig.get_provider().get_videos(username, limit=limit)
    except ig.InstagramError as exc:
        if cached:
            return {
                "username": username,
                "count": len(cached),
                "source": "cache",
                "warning": str(exc),
                "videos": cached,
            }
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    db.upsert_videos(user["id"], username, videos)
    return {
        "username": username,
        "count": len(videos),
        "source": "live",
        "videos": videos,
    }


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


@app.get("/api/feed", tags=["feed"])
def feed(
    user: CurrentUser,
    refresh: bool = False,
    username: str | None = Query(None),
    q: str | None = Query(None, description="Free-text filter on caption/handle"),
    bookmarked: bool = False,
    sort: str = Query("new", pattern="^(new|old|popular|views|reactions)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE),
) -> dict:
    """The combined video feed across every subscription, newest first."""
    if refresh:
        for subscription in db.list_subscriptions(user["id"]):
            try:
                videos = ig.get_provider().get_videos(subscription["username"])
            except ig.InstagramError:
                continue  # keep the old cache for that user
            db.upsert_videos(user["id"], subscription["username"], videos)

    total = db.count_videos(user["id"], username=username, search=q, bookmarked_only=bookmarked)
    offset = (page - 1) * page_size
    videos = db.query_videos(
        user["id"],
        username=username,
        search=q,
        bookmarked_only=bookmarked,
        sort=sort,
        limit=page_size,
        offset=offset,
    )
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "count": len(videos),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "subscriptions": len(db.list_subscriptions(user["id"])),
        "videos": videos,
    }


@app.get("/api/feed/export", tags=["feed"])
def export_feed(
    user: CurrentUser,
    format: str = Query("json", pattern="^(json|csv|markdown)$"),
    username: str | None = Query(None),
) -> Response:
    """Export the whole feed as JSON, CSV or Markdown."""
    videos = db.query_videos(
        user["id"], username=username, limit=config.MAX_PAGE_SIZE * 50, sort="new"
    )
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "username",
                "caption",
                "likes",
                "comments",
                "views",
                "duration",
                "taken_at",
                "permalink",
                "video_url",
            ]
        )
        for video in videos:
            writer.writerow(
                [
                    video["id"],
                    video["username"],
                    (video.get("caption") or "").replace("\n", " "),
                    video["likes"],
                    video["comments"],
                    video["views"],
                    video["duration"],
                    video["taken_at"],
                    video["permalink"],
                    video["video_url"],
                ]
            )
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="instafeed-feed.csv"'},
        )
    if format == "markdown":
        lines = ["# Instafeed digest", ""]
        for video in videos:
            lines.append(
                f"- **@{video['username']}** — {(video.get('caption') or '').strip()[:160]}"
                f" ({video['likes']} likes) {video.get('permalink', '')}"
            )
        return PlainTextResponse(
            "\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="instafeed-feed.md"'},
        )
    return Response(
        content=json.dumps({"videos": videos}, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="instafeed-feed.json"'},
    )


@app.get("/api/digest", tags=["feed"])
def digest(user: CurrentUser, limit: int = Query(10, ge=1, le=50)) -> dict:
    """A compact summary of the newest videos — handy for bots and automations."""
    videos = db.query_videos(user["id"], limit=limit, sort="new")
    return {
        "generated_at": db.last_poll(user["id"]) or {},
        "count": len(videos),
        "digest": [
            {
                "id": v["id"],
                "username": v["username"],
                "caption": (v.get("caption") or "")[:200],
                "likes": v["likes"],
                "permalink": v.get("permalink", ""),
                "taken_at": v["taken_at"],
            }
            for v in videos
        ],
    }


@app.delete("/api/videos/{video_id}", tags=["feed"])
def delete_video(video_id: str, user: CurrentUser) -> dict:
    """Remove one video from the local cache."""
    if not db.delete_video(user["id"], video_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="video not found")
    return {"message": "video removed"}


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


@app.get("/api/bookmarks", tags=["bookmarks"])
def list_bookmarks(user: CurrentUser) -> dict:
    """Every video the user saved."""
    return {"bookmarks": db.list_bookmarks(user["id"])}


@app.post("/api/bookmarks", status_code=status.HTTP_201_CREATED, tags=["bookmarks"])
def add_bookmark(body: BookmarkRequest, user: CurrentUser) -> dict:
    """Save a video to the personal collection."""
    if db.get_video(user["id"], body.video_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="video not found — fetch the feed first",
        )
    return {"bookmark": db.add_bookmark(user["id"], body.video_id, body.note)}


@app.delete("/api/bookmarks/{video_id}", tags=["bookmarks"])
def remove_bookmark(video_id: str, user: CurrentUser) -> dict:
    """Remove a video from the personal collection."""
    if not db.remove_bookmark(user["id"], video_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bookmark not found")
    return {"message": "bookmark removed"}


# ---------------------------------------------------------------------------
# Dashboard / operations
# ---------------------------------------------------------------------------


@app.get("/api/stats", tags=["dashboard"])
def stats(user: CurrentUser) -> dict:
    """Aggregated numbers powering the dashboard."""
    payload = db.user_stats(user["id"])
    payload["last_poll"] = db.last_poll(user["id"])
    payload["poll_history"] = db.poll_history(user["id"], limit=14)
    return payload


@app.post("/api/poll", tags=["operations"])
def poll(user: CurrentUser, limit: int | None = Query(None, ge=1, le=200)) -> dict:
    """Check every subscription for new videos right now.

    Mirrors exactly what the background scheduler does on its own interval,
    so an external cron can trigger it too.
    """
    return scheduler.run_poll(user_id=user["id"], limit=limit)


@app.get("/api/poll/status", tags=["operations"])
def poll_status(user: CurrentUser) -> dict:
    """When did the last poll run, and what did it find?"""
    info = db.last_poll(user["id"])
    return info if info else {"ran_at": None, "last_total_new": None}


@app.get("/api/health", tags=["operations"])
def health() -> dict:
    """Liveness probe — no authentication required."""
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "provider": "demo" if ig.demo_mode_enabled() else "live",
        "scheduler": "on" if config.SCHEDULER_ENABLED else "off",
        "users": db.user_count(),
    }


@app.get("/api/config", tags=["operations"])
def public_config(user: OptionalUser) -> dict:
    """Public runtime configuration used by the frontend to adapt itself."""
    return {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "tagline": config.APP_TAGLINE,
        "demo_mode": ig.demo_mode_enabled(),
        "poll_interval_minutes": config.POLL_INTERVAL_MINUTES,
        "page_size": config.DEFAULT_PAGE_SIZE,
        "authenticated": user is not None,
    }


# ---------------------------------------------------------------------------
# Frontend (single-page app)
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> Response:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<defs><linearGradient id="g" x1="0" y1="1" x2="1" y2="0">'
            '<stop offset="0" stop-color="#f9ce34"/><stop offset="0.5" '
            'stop-color="#ee2a7b"/><stop offset="1" stop-color="#6228d7"/>'
            '</linearGradient></defs><rect width="64" height="64" rx="16" '
            'fill="url(#g)"/><circle cx="32" cy="32" r="14" fill="none" '
            'stroke="#fff" stroke-width="4"/><circle cx="32" cy="32" r="5" '
            'fill="#fff"/><circle cx="46" cy="19" r="3" fill="#fff"/></svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve the SPA shell for any non-API route."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(FRONTEND_DIR / "index.html")
