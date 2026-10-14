"""Instafeed — FastAPI backend.

Workflow:
  1. GET  /api/search?q=<name>              → find Instagram handles
  2. POST /api/subscribe {username}         → subscribe to a handle
  3. GET  /api/subscriptions/{user}/videos  → fetch EVERY video of that user
  4. GET  /api/feed                         → videos of all subscribed users
