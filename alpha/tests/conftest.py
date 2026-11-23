import pytest

from studyseat import create_app
from studyseat.db import initialize
from studyseat.seed import seed_demo


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-" * 4,
            "DATABASE": str(tmp_path / "test.sqlite3"),
        }
    )
    with application.app_context():
        initialize()
        seed_demo()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="832402116", password="123456"):
    csrf = client.get("/api/v1/auth/session").json["data"]["csrf_token"]
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
