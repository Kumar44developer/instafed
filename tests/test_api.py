"""Subscription, feed, bookmark and statistics API tests."""

from __future__ import annotations


def test_subscribe_and_list(client, account):
    headers = account["headers"]
    response = client.post("/api/subscribe", json={"username": "nasa"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["subscription"]["username"] == "nasa"

    listed = client.get("/api/subscriptions", headers=headers)
    assert listed.status_code == 200
    usernames = [s["username"] for s in listed.json()["subscriptions"]]
    assert "nasa" in usernames


def test_subscriptions_are_isolated_per_user(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nba"}, headers=headers)
    listed = client.get("/api/subscriptions", headers=headers).json()
    assert len(listed["subscriptions"]) == 1


def test_user_videos_requires_subscription(client, account):
    response = client.get("/api/subscriptions/nasa/videos", headers=account["headers"])
    assert response.status_code == 409


def test_user_videos_fetches_and_caches(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nasa"}, headers=headers)

    first = client.get("/api/subscriptions/nasa/videos", headers=headers)
    assert first.status_code == 200
    payload = first.json()
    assert payload["count"] > 0
    assert payload["source"] == "live"

    second = client.get("/api/subscriptions/nasa/videos", headers=headers)
    assert second.json()["source"] == "cache"


def test_unsubscribe_removes_videos(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nba"}, headers=headers)
    client.get("/api/subscriptions/nba/videos", headers=headers)

    assert client.delete("/api/subscriptions/nba", headers=headers).status_code == 200
    listed = client.get("/api/subscriptions", headers=headers).json()
    assert listed["subscriptions"] == []
    feed = client.get("/api/feed", headers=headers).json()
    assert feed["total"] == 0


def test_feed_pagination_and_filters(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "natgeo"}, headers=headers)
    client.get("/api/subscriptions/natgeo/videos", headers=headers)

    feed = client.get("/api/feed?page=1&page_size=5", headers=headers)
    assert feed.status_code == 200
    payload = feed.json()
    assert payload["page_size"] == 5
    assert payload["total"] >= payload["count"]
    assert payload["pages"] >= 1

    filtered = client.get("/api/feed?username=natgeo", headers=headers).json()
    assert filtered["total"] >= 1
    assert all(v["username"] == "natgeo" for v in filtered["videos"])

    search = client.get("/api/feed?q=demo", headers=headers).json()
    assert search["total"] >= 1


def test_feed_sorting(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nintendo"}, headers=headers)
    client.get("/api/subscriptions/nintendo/videos", headers=headers)

    popular = client.get("/api/feed?sort=popular", headers=headers).json()["videos"]
    if len(popular) > 1:
        assert popular[0]["likes"] >= popular[-1]["likes"]


def test_bookmark_lifecycle(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nike"}, headers=headers)
    videos = client.get("/api/subscriptions/nike/videos", headers=headers).json()["videos"]
    video_id = videos[0]["id"]

    created = client.post("/api/bookmarks", json={"video_id": video_id}, headers=headers)
    assert created.status_code == 201

    listed = client.get("/api/bookmarks", headers=headers).json()
    assert len(listed["bookmarks"]) == 1

    only = client.get("/api/feed?bookmarked=true", headers=headers).json()
    assert only["total"] == 1

    assert client.delete(f"/api/bookmarks/{video_id}", headers=headers).status_code == 200
    assert client.get("/api/bookmarks", headers=headers).json()["bookmarks"] == []


def test_bookmark_unknown_video_is_404(client, account):
    response = client.post(
        "/api/bookmarks", json={"video_id": "does-not-exist"}, headers=account["headers"]
    )
    assert response.status_code == 404


def test_stats_endpoint(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "netflix"}, headers=headers)
    client.get("/api/subscriptions/netflix/videos", headers=headers)

    stats = client.get("/api/stats", headers=headers).json()
    assert stats["subscriptions"] == 1
    assert stats["videos"] > 0
    assert stats["total_views"] >= 0
    assert isinstance(stats["top_creators"], list)


def test_poll_creates_new_videos_and_records_history(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nba"}, headers=headers)

    result = client.post("/api/poll", headers=headers)
    assert result.status_code == 200
    payload = result.json()
    assert payload["total_new"] >= 1
    assert "ran_at" in payload

    status = client.get("/api/poll/status", headers=headers).json()
    assert status["ran_at"] is not None


def test_export_feed_csv(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nasagrams"}, headers=headers)
    client.get("/api/subscriptions/nasagrams/videos", headers=headers)

    response = client.get("/api/feed/export?format=csv", headers=headers)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "permalink" in response.text


def test_export_feed_json(client, account):
    response = client.get("/api/feed/export?format=json", headers=account["headers"])
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")


def test_digest_endpoint(client, account):
    headers = account["headers"]
    client.post("/api/subscribe", json={"username": "nba_updates"}, headers=headers)
    client.get("/api/subscriptions/nba_updates/videos", headers=headers)

    digest = client.get("/api/digest?limit=5", headers=headers).json()
    assert digest["count"] >= 1
    assert "digest" in digest


def test_search_endpoint(client, account):
    response = client.get("/api/search?q=nasa", headers=account["headers"])
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["results"][0]["username"]
    assert "subscribed" in payload["results"][0]


def test_health_and_config(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json()["demo_mode"] is True


def test_spa_shell_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Instafeed" in response.text
