"""Authentication, session and account-lifecycle tests."""

from __future__ import annotations

import pytest


def test_register_returns_token_and_user(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "alpha_tester", "password": "hunter2hunter2"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["token"]
    assert payload["user"]["username"] == "alpha_tester"
    assert "password_hash" not in payload["user"]
    assert "salt" not in payload["user"]


def test_duplicate_username_is_rejected(client):
    client.post("/api/auth/register", json={"username": "dupe_user", "password": "hunter2hunter2"})
    response = client.post(
        "/api/auth/register", json={"username": "dupe_user", "password": "hunter2hunter2"}
    )
    assert response.status_code == 409


def test_login_with_wrong_password_is_401(client):
    client.post("/api/auth/register", json={"username": "login_user", "password": "correcthorse1"})
    response = client.post(
        "/api/auth/login", json={"username": "login_user", "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_returns_new_token(client):
    client.post("/api/auth/register", json={"username": "login_ok", "password": "correcthorse1"})
    response = client.post(
        "/api/auth/login", json={"username": "login_ok", "password": "correcthorse1"}
    )
    assert response.status_code == 200
    assert response.json()["token"]


def test_protected_route_requires_token(client):
    assert client.get("/api/subscriptions").status_code == 401


def test_tampered_token_is_rejected(client):
    token = client.post(
        "/api/auth/register", json={"username": "tamper_user", "password": "hunter2hunter2"}
    ).json()["token"]
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    response = client.get("/api/subscriptions", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_me_returns_current_user(client, account):
    response = client.get("/api/auth/me", headers=account["headers"])
    assert response.status_code == 200
    assert response.json()["user"]["username"] == account["user"]["username"]


def test_password_hash_is_not_plaintext(client):
    from backend import database as db

    client.post("/api/auth/register", json={"username": "hash_user", "password": "plaintext123"})
    record = db.get_user_by_username("hash_user")
    assert record is not None
    assert record["password_hash"] != "plaintext123"
    assert record["salt"]
    assert len(record["password_hash"]) == 64  # sha256 hex digest


def test_account_deletion_removes_data(client, account):
    username = account["user"]["username"]
    client.delete("/api/auth/me", headers=account["headers"])
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "sup3rsecret!"}
    )
    assert response.status_code == 401


def test_short_password_is_rejected(client):
    response = client.post("/api/auth/register", json={"username": "shorty", "password": "abc"})
    assert response.status_code == 422


@pytest.mark.parametrize("username", ["ab", "with space", "bad/slash"])
def test_invalid_usernames_are_rejected(client, username):
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "hunter2hunter2"}
    )
    assert response.status_code == 422
