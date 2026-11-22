import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import login

from studyseat import create_app
from studyseat.db import get_db, initialize, write_transaction
from studyseat.seed import seed_demo


def test_health_home_and_assets(client):
    assert client.get("/api/v1/health").json["data"]["status"] == "ok"
    assert "登录 Study Seat" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


@pytest.mark.parametrize(
    "path", ["/me", "/rooms", "/rules", "/persistence-notes", "/admin/audit-events"]
)
def test_anonymous_denied(client, path):
    assert client.get("/api/v1" + path).status_code == 401


@pytest.mark.parametrize(
    "username,password,role",
    [
        ("832402116", "123456", "student"),
        ("student02", "Study1234", "student"),
        ("admin01", "Admin1234", "admin"),
    ],
)
def test_login_roles(client, username, password, role):
    response = login(client, username, password)
    assert response.status_code == 200
    assert response.json["data"]["user"]["role"] == role
    assert client.get("/api/v1/me").json["data"]["role"] == role


@pytest.mark.parametrize(
    "username,password", [("832402116", "wrong"), ("unknown", "wrong"), ("' OR 1=1 --", "wrong")]
)
def test_bad_credentials(client, username, password):
    assert login(client, username, password).status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_role_is_server_owned(client, app):
    login(client)
    assert client.get("/api/v1/admin/audit-events").status_code == 403
    with app.app_context(), write_transaction() as connection:
        connection.execute("UPDATE users SET role='admin' WHERE id='student01'")
    assert client.get("/api/v1/admin/audit-events").status_code == 200
    with app.app_context(), write_transaction() as connection:
        connection.execute("UPDATE users SET enabled=0 WHERE id='student01'")
    assert client.get("/api/v1/me").status_code == 401


def test_csrf_rotation_logout_and_replay(client, app):
    anonymous = client.get("/api/v1/auth/session").json["data"]["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin01", "password": "Admin1234"}
        ).status_code
        == 403
    )
    response = login(client)
    csrf = response.json["data"]["csrf_token"]
    assert csrf != anonymous
    cookie = client.get_cookie("studyseat_alpha")
    assert cookie.http_only and cookie.same_site == "Lax"
    assert (
        client.post(
            "/api/v1/persistence-notes",
            json={"content": "blocked"},
            headers={"X-CSRF-Token": anonymous},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    replay = app.test_client()
    replay.set_cookie("studyseat_alpha", cookie.value)
    assert replay.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_expired_session(client, app):
    login(client)
    with app.app_context(), write_transaction() as connection:
        expired = (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
        connection.execute("UPDATE sessions SET expires_at=?", (expired,))
    assert client.get("/api/v1/me").status_code == 401


def test_persistence_and_ownership(client, app):
    csrf = login(client).json["data"]["csrf_token"]
    response = client.post(
        "/api/v1/persistence-notes",
        json={"content": "重启后仍存在 <script>"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    note = response.json["data"]
    # A fresh application and connection must use the same on-disk data.
    restarted = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": app.config["SECRET_KEY"],
            "DATABASE": app.config["DATABASE"],
        }
    )
    browser = restarted.test_client()
    browser.set_cookie("studyseat_alpha", client.get_cookie("studyseat_alpha").value)
    assert browser.get("/api/v1/persistence-notes").json["data"][0] == note
    assert browser.get("/api/v1/persistence-notes/" + note["id"]).status_code == 200
    login(browser, "student02", "Study1234")
    assert browser.get("/api/v1/persistence-notes").json["data"] == []
    assert browser.get("/api/v1/persistence-notes/" + note["id"]).status_code == 404
    login(browser, "admin01", "Admin1234")
    events = browser.get("/api/v1/admin/audit-events").json["data"]
    assert any(event["target_id"] == note["id"] for event in events)


@pytest.mark.parametrize("body", [{}, {"content": " "}, {"content": 1}, {"content": "a" * 201}, []])
def test_invalid_notes(client, body):
    csrf = login(client).json["data"]["csrf_token"]
    assert (
        client.post(
            "/api/v1/persistence-notes", json=body, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 400
    )
    assert client.get("/api/v1/persistence-notes").json["data"] == []


def test_seed_is_idempotent_and_passwords_hashed(app):
    with app.app_context():
        initialize()
        seed_demo()
        connection = get_db()
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM seats").fetchone()[0] == 312
        assert connection.execute("SELECT COUNT(*) FROM rule_versions").fetchone()[0] == 1
        assert (
            connection.execute("SELECT password_hash FROM users LIMIT 1")
            .fetchone()[0]
            .startswith("scrypt:")
        )
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_atomic_rollback(app):
    with app.app_context():
        with pytest.raises(sqlite3.IntegrityError), write_transaction() as connection:
            connection.execute(
                "INSERT INTO persistence_notes VALUES ('rollback','student01','x','2026-11-22T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO persistence_notes VALUES ('invalid','missing-user','x','2026-11-22T00:00:00Z')"
            )
        assert get_db().execute("SELECT COUNT(*) FROM persistence_notes").fetchone()[0] == 0


def test_busy_database_is_retryable(app, client):
    csrf = login(client).json["data"]["csrf_token"]
    other = sqlite3.connect(app.config["DATABASE"], isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        response = client.post(
            "/api/v1/persistence-notes", json={"content": "busy"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 503
        assert response.json["error"]["code"] == "DATABASE_BUSY"
        assert response.headers["Retry-After"] == "1"
    finally:
        other.rollback()
        other.close()
    assert client.get("/api/v1/persistence-notes").json["data"] == []


def test_no_secret_rejected(monkeypatch):
    monkeypatch.delenv("STUDYSEAT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="STUDYSEAT_SECRET_KEY"):
        create_app()
