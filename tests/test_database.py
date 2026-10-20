"""Unit tests for the storage layer and the auth primitives."""

from __future__ import annotations

import pytest

from backend import auth
from backend import database as db


@pytest.fixture()
def user(db_module):
    import uuid

    record = db_module.create_user(
        f"storage_{uuid.uuid4().hex[:8]}", "hash", "salt", "storage@example.com"
    )
    return record


@pytest.fixture()
def db_module():
    db.init_db()
    return db


def test_hash_and_verify_roundtrip():
    digest, salt = auth.hash_password("correct horse battery")
    assert digest != "correct horse battery"
    assert auth.verify_password("correct horse battery", digest, salt) is True
    assert auth.verify_password("wrong password", digest, salt) is False


def test_hash_is_salted():
    first, salt_a = auth.hash_password("same-password")
    second, salt_b = auth.hash_password("same-password")
    assert salt_a != salt_b
    assert first != second


def test_token_roundtrip():
    token = auth.create_token(7, "someone")
    payload = auth.decode_token(token)
    assert payload["uid"] == 7
    assert payload["usr"] == "someone"


def test_expired_token_is_rejected():
    token = auth.create_token(1, "someone", ttl_days=0)
    with pytest.raises(auth.AuthError):
        auth.decode_token(token)


def test_malformed_token_is_rejected():
    for bad in ("", "garbage", "instafeed.only-two", "other.aaa.bbb"):
        with pytest.raises(auth.AuthError):
            auth.decode_token(bad)


def test_subscription_lifecycle(db_module, user):
    db_module.add_subscription(user["id"], "nasa", "NASA", "pic.png", 1_000_000)
    assert db_module.is_subscribed(user["id"], "nasa") is True
    assert db_module.list_subscriptions(user["id"])[0]["cached_videos"] == 0

    videos = [
        {
            "id": "abc123",
            "username": "nasa",
            "video_url": "https://example.com/v.mp4",
            "thumbnail_url": "https://example.com/t.jpg",
            "caption": "Hello",
            "likes": 10,
            "comments": 2,
            "views": 100,
            "duration": 12.5,
            "permalink": "https://instagram.com/reel/abc123",
            "taken_at": "2024-05-01T10:00:00+00:00",
        }
    ]
    assert db_module.upsert_videos(user["id"], "nasa", videos) == 1
    assert db_module.insert_new_videos(user["id"], "nasa", videos) == 0
    assert db_module.insert_new_videos(user["id"], "nasa", videos + [dict(videos[0], id="x2")]) == 1

    stored = db_module.get_videos(user["id"], "nasa")
    assert len(stored) == 2
    assert stored[0]["views"] == 100


def test_query_videos_filters_and_pagination(db_module, user):
    db_module.add_subscription(user["id"], "nasa")
    rows = [
        {
            "id": f"vid{i}",
            "username": "nasa",
            "video_url": "https://example.com/v.mp4",
            "thumbnail_url": "",
            "caption": f"caption {i}",
            "likes": i * 10,
            "comments": 0,
            "views": i * 100,
            "duration": 5,
            "permalink": "",
            "taken_at": f"2024-05-{i + 1:02d}T10:00:00+00:00",
        }
        for i in range(5)
    ]
    db_module.upsert_videos(user["id"], "nasa", rows)

    page = db_module.query_videos(user["id"], limit=2, offset=0, sort="new")
    assert len(page) == 2
    assert db_module.count_videos(user["id"]) == 5

    liked = db_module.query_videos(user["id"], sort="popular", limit=5)
    assert liked[0]["likes"] == 40

    searched = db_module.query_videos(user["id"], search="caption 3", limit=10)
    assert len(searched) == 1


def test_bookmark_helpers(db_module, user):
    db_module.add_subscription(user["id"], "nasa")
    db_module.upsert_videos(
        user["id"],
        "nasa",
        [
            {
                "id": "b1",
                "username": "nasa",
                "video_url": "u",
                "thumbnail_url": "",
                "caption": "c",
                "likes": 0,
                "comments": 0,
                "views": 0,
                "duration": 0,
                "permalink": "",
                "taken_at": "",
            }
        ],
    )
    db_module.add_bookmark(user["id"], "b1", "watch later")
    assert db_module.get_bookmark(user["id"], "b1")["note"] == "watch later"
    assert db_module.count_videos(user["id"], bookmarked_only=True) == 1
    assert db_module.remove_bookmark(user["id"], "b1") is True
    assert db_module.count_videos(user["id"], bookmarked_only=True) == 0


def test_deleting_user_cascades(db_module, user):
    db_module.add_subscription(user["id"], "nasa")
    db_module.upsert_videos(
        user["id"],
        "nasa",
        [
            {
                "id": "z1",
                "username": "nasa",
                "video_url": "u",
                "thumbnail_url": "",
                "caption": "",
                "likes": 0,
                "comments": 0,
                "views": 0,
                "duration": 0,
                "permalink": "",
                "taken_at": "",
            }
        ],
    )
    assert db_module.delete_user(user["id"]) is True
    assert db_module.list_subscriptions(user["id"]) == []
    assert db_module.get_videos(user["id"]) == []
