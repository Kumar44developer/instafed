"""Instagram data provider for Instafeed.

- search_users():  multi-strategy handle search:
      1. anonymous web topsearch (works from most home IPs)
      2. logged-in search via instaloader session (when INSTAGRAM_LOGIN is set)
      3. exact-handle match via public profile fetch (search blocked, profile OK)
- get_profile():   instaloader public profile metadata.
- get_videos():    instaloader — walks every post of a public profile and
                   keeps only video posts (reels / video posts).

NOTE: Instagram rate-limits anonymous scraping, especially from cloud/datacenter
IPs (HTTP 429). If you hit rate limits, set INSTAGRAM_LOGIN / INSTAGRAM_PASSWORD
env vars so instaloader uses a logged-in session (see README).
"""
from __future__ import annotations

import os
from functools import lru_cache

import requests

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


def _normalize_user(u: dict) -> dict:
    """Map an Instagram user JSON blob onto our result schema."""
    return {
        "username": u.get("username", ""),
        "full_name": u.get("full_name", ""),
        "profile_pic": u.get("profile_pic_url", ""),
        "followers": u.get("follower_count") or 0,
        "is_verified": u.get("is_verified", False),
        "is_private": u.get("is_private", False),
    }


def _parse_topsearch(resp: requests.Response, limit: int) -> list[dict]:
    users = [_normalize_user(item.get("user", {}))
             for item in (resp.json().get("users") or [])]
    return [u for u in users if u["username"]][:limit]

def _anonymous_search(query: str, limit: int) -> list[dict]:
    """Strategy 1: anonymous web topsearch with a fresh session."""
    errors = []
    with requests.Session() as s:
        s.headers.update({"User-Agent": UA})
        try:
            s.get("https://www.instagram.com/", timeout=15)  # seed csrftoken cookie
        except requests.RequestException:
            pass
        for url in SEARCH_URLS:
            try:
                resp = s.get(url, params={"query": query},
                             headers={"X-IG-App-ID": APP_ID}, timeout=15)
            except requests.RequestException as exc:
                errors.append(f"{url.split('//')[1]}: {exc}")
                continue
