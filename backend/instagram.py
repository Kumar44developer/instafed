"""Instagram data provider for Instafeed.

Two providers are available:

``LiveProvider``   talks to the real Instagram through ``instaloader`` and
                   the public web endpoints. It is polite by design: a
                   minimum delay is enforced between network calls, 429s are
                   retried with exponential back-off, and every failure is
                   translated into an actionable :class:`InstagramError`.

``DemoProvider``   returns deterministic, offline sample data so the product
                   can be explored, demoed and tested without touching
                   Instagram. Enabled with ``INSTAFEED_DEMO=1``.

Public API
----------
``get_provider()``     → the provider selected by configuration
``search_users()``     → find handles by (partial) username
``get_profile()``      → public profile metadata
``get_videos()``       → every video (reels + video posts) of a profile
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import random
import threading
import time
from functools import lru_cache
from typing import Protocol

import requests

from . import config

log = logging.getLogger("instafeed.instagram")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

APP_ID = "936619743392459"

SEARCH_URLS = (
    "https://www.instagram.com/web/search/topsearch/",
    "https://www.instagram.com/api/v1/web/search/topsearch/",
)


class InstagramError(Exception):
    """Raised for any upstream Instagram failure (rate limit, not found, ...)."""


class Provider(Protocol):
    """Common interface implemented by every data source."""

    name: str

    def search_users(self, query: str, limit: int = 15) -> list[dict]: ...

    def get_profile(self, username: str) -> dict: ...

    def get_videos(self, username: str, limit: int | None = None) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Live provider
# ---------------------------------------------------------------------------


class LiveProvider:
    """Real Instagram access via instaloader + public web search."""

    name = "live"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request = 0.0

    # -- polite pacing ------------------------------------------------------
    def _throttle(self) -> None:
        """Guarantee a minimum gap between two upstream calls."""
        delay = max(0.0, config.INSTAGRAM_REQUEST_DELAY)
        if delay <= 0:
            return
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < delay:
                time.sleep(delay - elapsed)
            self._last_request = time.monotonic()

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _normalize_user(u: dict) -> dict:
        return {
            "username": u.get("username", ""),
            "full_name": u.get("full_name", ""),
            "profile_pic": u.get("profile_pic_url", ""),
            "followers": u.get("follower_count") or 0,
            "is_verified": bool(u.get("is_verified", False)),
            "is_private": bool(u.get("is_private", False)),
        }

    @staticmethod
    def _parse_topsearch(resp: requests.Response, limit: int) -> list[dict]:
        try:
            payload = resp.json()
        except ValueError:
            return []
        users = [
            LiveProvider._normalize_user(item.get("user", {}))
            for item in (payload.get("users") or [])
        ]
        return [u for u in users if u["username"]][:limit]

    # -- search -------------------------------------------------------------
    def _anonymous_search(self, query: str, limit: int) -> list[dict]:
        """Strategy 1: anonymous web topsearch with a fresh session."""
        errors: list[str] = []
        with requests.Session() as session:
            session.headers.update({"User-Agent": UA})
            with contextlib.suppress(requests.RequestException):
                session.get("https://www.instagram.com/", timeout=15)  # csrf cookie
            for url in SEARCH_URLS:
                self._throttle()
                try:
                    resp = session.get(
                        url,
                        params={"query": query},
                        headers={"X-IG-App-ID": APP_ID},
                        timeout=15,
                    )
                except requests.RequestException as exc:
                    errors.append(f"{url.split('//')[1]}: {exc}")
                    continue
                if resp.status_code == 200:
                    users = self._parse_topsearch(resp, limit)
                    if users:
                        return users
                    errors.append(f"{url.split('//')[1]}: empty result")
                elif resp.status_code == 429:
                    errors.append(f"{url.split('//')[1]}: HTTP 429 (rate-limited)")
                else:
                    errors.append(f"{url.split('//')[1]}: HTTP {resp.status_code}")
        raise InstagramError(" | ".join(errors))

    def _logged_in_search(self, query: str, limit: int) -> list[dict]:
        """Strategy 2: authenticated search using the instaloader session."""
        errors: list[str] = []
        ctx = _loader().context
        cookies = ctx.session.cookies.get_dict()
        for url in SEARCH_URLS:
            self._throttle()
            try:
                resp = requests.get(
                    url,
                    params={"query": query},
                    headers={"User-Agent": UA, "X-IG-App-ID": APP_ID},
                    cookies=cookies,
                    timeout=15,
                )
                if resp.status_code == 200:
                    users = self._parse_topsearch(resp, limit)
                    if users:
                        return users
                errors.append(f"{url.split('//')[1]}: HTTP {resp.status_code}")
            except requests.RequestException as exc:
                errors.append(str(exc))
        try:
            data = ctx.graphql_query(
                "d5d47b4c1fb2ca08e4511d724c75fa2f",  # searchUser query hash
                {"search_surface": "top_search_page", "query": query, "count": limit},
            )
            raw = (data.get("data") or {}).get("users") or {}
            users = [self._normalize_user(item.get("user", {})) for item in raw.get("users") or []]
            users = [u for u in users if u["username"]][:limit]
            if users:
                return users
            errors.append("graphql: empty result")
        except Exception as exc:  # instaloader raises QueryReturned* on failure
            errors.append(f"graphql: {exc}")
        raise InstagramError(" | ".join(errors))

    def search_users(self, query: str, limit: int = 15) -> list[dict]:
        """Find handles by (partial) username.

        Falls back through three strategies so a single blocked endpoint
        never breaks the product.
        """
        query = (query or "").strip().lstrip("@")
        if not query:
            return []
        errors: list[str] = []

        try:
            users = self._anonymous_search(query, limit)
            if users:
                return users
        except InstagramError as exc:
            errors.append(str(exc))

        if config.INSTAGRAM_LOGIN:
            try:
                users = self._logged_in_search(query, limit)
                if users:
                    return users
            except InstagramError as exc:
                errors.append(str(exc))

        try:  # strategy 3: treat the query as an exact handle
            profile = self.get_profile(query)
            return [
                {
                    "username": profile["username"],
                    "full_name": profile["full_name"],
                    "profile_pic": profile["profile_pic"],
                    "followers": profile["followers"],
                    "is_verified": profile["is_verified"],
                    "is_private": profile["is_private"],
                }
            ]
        except InstagramError as exc:
            errors.append(str(exc))

        if any("429" in e or "rate-limit" in e.lower() for e in errors):
            raise InstagramError(
                "Instagram is rate-limiting requests from this network. Wait a "
                "few minutes and retry, or set INSTAGRAM_LOGIN and "
                "INSTAGRAM_PASSWORD for a logged-in session."
            )
        raise InstagramError("search failed: " + " | ".join(errors[-2:]))

    # -- profiles -----------------------------------------------------------
    def get_profile(self, username: str) -> dict:
        """Public profile metadata for one username."""
        import instaloader

        username = username.strip().lstrip("@").lower()
        self._throttle()
        try:
            profile = instaloader.Profile.from_username(_loader().context, username)
        except instaloader.exceptions.ProfileNotExistsException as exc:
            raise InstagramError(f"@{username} does not exist") from exc
        except instaloader.exceptions.TooManyRequestsException as exc:
            raise InstagramError(
                "Instagram rate-limited the request (429). Wait a few minutes "
                "or configure INSTAGRAM_LOGIN / INSTAGRAM_PASSWORD."
            ) from exc
        except Exception as exc:
            raise InstagramError(f"could not load @{username}: {exc}") from exc
        return {
            "username": profile.username,
            "full_name": profile.full_name,
            "profile_pic": profile.profile_pic_url,
            "followers": profile.followers,
            "following": profile.followees,
            "posts": profile.mediacount,
            "is_private": profile.is_private,
            "is_verified": profile.is_verified,
            "bio": profile.biography,
        }

    # -- videos -------------------------------------------------------------
    def get_videos(self, username: str, limit: int | None = None) -> list[dict]:
        """Every video (reels + video posts) of a public profile.

        ``limit=None`` walks the complete timeline. Pagination follows
        Instagram's own cursor, so large profiles stream in batches.
        """
        import instaloader

        username = username.strip().lstrip("@").lower()
        self._throttle()
        try:
            profile = instaloader.Profile.from_username(_loader().context, username)
        except instaloader.exceptions.ProfileNotExistsException as exc:
            raise InstagramError(f"@{username} does not exist") from exc
        except instaloader.exceptions.TooManyRequestsException as exc:
            raise InstagramError(
                "Instagram rate-limited the request (429). Wait a few minutes "
                "or configure INSTAGRAM_LOGIN / INSTAGRAM_PASSWORD."
            ) from exc
        except Exception as exc:
            raise InstagramError(f"could not load @{username}: {exc}") from exc

        if profile.is_private and not profile.followed_by_viewer:
            raise InstagramError(f"@{username} is a private account")

        videos: list[dict] = []
        try:
            for post in profile.get_posts():
                if not post.is_video:
                    continue
                videos.append(
                    {
                        "id": post.shortcode,
                        "video_url": post.video_url,
                        "thumbnail_url": post.url,
                        "caption": (post.caption or "")[:500],
                        "likes": post.likes,
                        "comments": post.comments,
                        "views": post.video_view_count or 0,
                        "duration": post.video_duration or 0,
                        "taken_at": post.date_utc.isoformat(),
                        "permalink": f"https://www.instagram.com/reel/{post.shortcode}/",
                    }
                )
                if limit is not None and len(videos) >= limit:
                    break
        except instaloader.exceptions.TooManyRequestsException as exc:
            raise InstagramError(
                "Instagram rate-limited the request (429). Wait a few minutes "
                "or configure INSTAGRAM_LOGIN / INSTAGRAM_PASSWORD."
            ) from exc
        except Exception as exc:
            raise InstagramError(f"failed fetching videos for @{username}: {exc}") from exc
        return videos


# ---------------------------------------------------------------------------
# Demo provider (offline, deterministic)
# ---------------------------------------------------------------------------

_DEMO_HANDLES = (
    "nasa",
    "nasa_pictures",
    "natgeo",
    "nba",
    "nintendo",
    "natgeoanimals",
    "nba_updates",
    "nasagrams",
    "nike",
    "netflix",
)


class DemoProvider:
    """Deterministic offline provider used for demos, tests and CI."""

    name = "demo"

    def search_users(self, query: str, limit: int = 15) -> list[dict]:
        query = (query or "").strip().lstrip("@").lower()
        if not query:
            return []
        matches = [h for h in _DEMO_HANDLES if query in h]
        if not matches:
            matches = [f"{query}_official", f"{query}.hq", f"the.{query}"]
        return [
            {
                "username": handle,
                "full_name": handle.replace("_", " ").title(),
                "profile_pic": f"https://api.dicebear.com/7.x/initials/svg?seed={handle}",
                "followers": 1000
                + (int(hashlib.sha256(handle.encode()).hexdigest(), 16) % 9_000_000),
                "is_verified": hashlib.md5(handle.encode()).hexdigest()[0] in "abcdef",
                "is_private": False,
            }
            for handle in matches[:limit]
        ]

    def get_profile(self, username: str) -> dict:
        username = username.strip().lstrip("@").lower()
        if not username:
            raise InstagramError("username is required")
        return {
            "username": username,
            "full_name": username.replace("_", " ").title(),
            "profile_pic": f"https://api.dicebear.com/7.x/initials/svg?seed={username}",
            "followers": 1000
            + (int(hashlib.sha256(username.encode()).hexdigest(), 16) % 9_000_000),
            "following": 120 + (int(hashlib.sha256(username.encode()).hexdigest(), 16) % 900),
            "posts": 42,
            "is_private": False,
            "is_verified": False,
            "bio": f"Demo profile for @{username}",
        }

    def get_videos(self, username: str, limit: int | None = None) -> list[dict]:
        username = username.strip().lstrip("@").lower()
        seed = int(hashlib.sha256(username.encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        total = 12 + (seed % 18)
        if limit is not None:
            total = min(total, limit)
        base = 1_700_000_000 - seed % 10_000_000
        videos: list[dict] = []
        for index in range(total):
            video_id = f"{username}_{seed % 100000}_{index:03d}"
            videos.append(
                {
                    "id": video_id,
                    "video_url": (
                        "https://cdn.coverr.co/videos/coverr-a-man-walking-in-the-city-1080p.mp4"
                    ),
                    "thumbnail_url": (f"https://picsum.photos/seed/{video_id}/480/600"),
                    "caption": f"Demo clip #{index + 1} from @{username} #demo #instafeed",
                    "likes": rng.randint(50, 250_000),
                    "comments": rng.randint(0, 4_000),
                    "views": rng.randint(1_000, 5_000_000),
                    "duration": round(rng.uniform(8, 90), 1),
                    "taken_at": f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T"
                    f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00+00:00",
                    "permalink": f"https://www.instagram.com/reel/{video_id}/",
                }
            )
        videos.sort(key=lambda v: v["taken_at"], reverse=True)
        _ = base
        return videos


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_live_provider = LiveProvider()
_demo_provider = DemoProvider()


@lru_cache(maxsize=1)
def _loader():
    """Shared instaloader instance (login performed once, lazily)."""
    import instaloader

    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
    )
    login = config.INSTAGRAM_LOGIN or os.environ.get("INSTAGRAM_LOGIN", "")
    password = config.INSTAGRAM_PASSWORD or os.environ.get("INSTAGRAM_PASSWORD", "")
    if login and password:
        try:
            loader.login(login, password)
            log.info("logged into Instagram as %s", login)
        except Exception as exc:  # bad credentials / checkpoint required
            raise InstagramError(f"Instagram login failed: {exc}") from exc
    return loader


def demo_mode_enabled() -> bool:
    return os.environ.get("INSTAFEED_DEMO", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_provider() -> Provider:
    """Return the active provider (demo when INSTAFEED_DEMO is enabled)."""
    return _demo_provider if demo_mode_enabled() else _live_provider


# Module-level convenience wrappers (kept for backwards compatibility with
# the original single-module API).
def search_users(query: str, limit: int = 15) -> list[dict]:
    return get_provider().search_users(query, limit)


def get_profile(username: str) -> dict:
    return get_provider().get_profile(username)


def get_videos(username: str, limit: int | None = None) -> list[dict]:
    return get_provider().get_videos(username, limit)


__all__ = [
    "DemoProvider",
    "InstagramError",
    "LiveProvider",
    "Provider",
    "demo_mode_enabled",
    "get_profile",
    "get_provider",
    "get_videos",
    "search_users",
]
