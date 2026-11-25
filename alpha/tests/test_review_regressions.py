import pytest
from conftest import login

from studyseat.db import get_db, write_transaction


def test_non_ascii_csrf_is_rejected_without_server_error(client):
    client.get("/api/v1/auth/session")
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "832402116", "password": "123456"},
        headers={"X-CSRF-Token": "é"},
    )
    assert response.status_code == 403
    assert response.json["error"]["code"] == "CSRF_INVALID"


@pytest.mark.parametrize("field", ["username", "password"])
def test_invalid_unicode_login_returns_input_error(client, field):
    csrf = client.get("/api/v1/auth/session").json["data"]["csrf_token"]
    body = {"username": "832402116", "password": "123456"}
    body[field] = "\ud800"
    response = client.post("/api/v1/auth/login", json=body, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize("content", ["\ud800", "\x00", "a\x00b"])
def test_invalid_note_text_returns_input_error(client, content):
    csrf = login(client).json["data"]["csrf_token"]
    response = client.post(
        "/api/v1/persistence-notes", json={"content": content}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 400
    assert client.get("/api/v1/persistence-notes").json["data"] == []


@pytest.mark.parametrize("mutation", ["missing-version", "unsupported-version"])
def test_health_requires_supported_schema(client, app, mutation):
    with app.app_context(), write_transaction() as connection:
        if mutation == "missing-version":
            connection.execute("DELETE FROM schema_versions")
        else:
            connection.execute("PRAGMA user_version = 99")
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_failed_login_transaction_preserves_original_session(client, app):
    csrf = login(client).json["data"]["csrf_token"]
    original_cookie = client.get_cookie("studyseat_alpha").value
    with app.app_context(), write_transaction() as connection:
        connection.execute(
            "CREATE TRIGGER reject_login BEFORE INSERT ON audit_events "
            "WHEN NEW.action='LOGIN' BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END"
        )
    app.config["TESTING"] = False
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "student02", "password": "Study1234"},
        headers={"X-CSRF-Token": csrf},
    )
    assert client.get_cookie("studyseat_alpha").value == original_cookie
    assert response.status_code == 503
    assert response.json["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert client.get("/api/v1/me").json["data"]["id"] == "student01"
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
