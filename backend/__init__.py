"""Instafeed — your Instagram video feed, distilled.

A small, self-hosted FastAPI application that turns the Instagram handles
you care about into one searchable, bookmarkable, always-fresh video feed.

Modules
-------
``config``      every tunable, read from the environment exactly once
``auth``        PBKDF2 password hashing + HMAC signed session tokens
``database``    SQLite storage (users, subscriptions, videos, bookmarks, polls)
``instagram``   live and offline data providers behind one interface
``scheduler``   background polling daemon
``main``        the FastAPI application and its routes
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
