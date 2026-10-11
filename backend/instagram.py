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
