"""Phase 3 attendance transitions and lazy timeout release."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import login

from studyseat import reservations
from studyseat.db import get_db

BASE = "/api/v1/reservations"
NOW = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def frozen_time(monkeypatch):
    monkeypatch.setattr(reservations, "now_utc", lambda: NOW)


def student(client, username="832402116", password="123456"):
    return {"X-CSRF-Token": login(client, username, password).json["data"]["csrf_token"]}


def create(
    client,
    headers,
    seat="lib-a101:A01",
    key="attendance-1",
    start="2026-11-24T08:00:00+08:00",
    hours=1,
):
    end = (datetime.fromisoformat(start) + timedelta(hours=hours)).isoformat()
    response = client.post(
        BASE,
        json={"seat_id": seat, "start_at": start, "end_at": end, "idempotency_key": key},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json["data"]


def at(monkeypatch, **changes):
    monkeypatch.setattr(reservations, "now_utc", lambda: START + timedelta(**changes))


def count(app, table, where="1=1"):
    with app.app_context():
        return get_db().execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def status(client, record):
    return client.get(BASE + "/" + record["id"]).json["data"]["status"]


def action(client, headers, record, name):
    return client.post(BASE + "/" + record["id"] + "/" + name, headers=headers)


def test_check_in_window_is_inclusive_at_both_edges(monkeypatch, client):
    headers = student(client)
    early = create(client, headers)
    at(monkeypatch, minutes=-10)
    assert action(client, headers, early, "check-in").status_code == 200
    assert status(client, early) == "IN_USE"

    too_early = create(
        client, headers, seat="lib-a101:A02", key="too-early", start="2026-11-24T10:00:00+08:00"
    )
    at(monkeypatch, minutes=-9)
    assert action(client, headers, too_early, "check-in").status_code == 409
    assert status(client, too_early) == "PENDING_CHECKIN"

    late = create(
        client, headers, seat="lib-a101:A03", key="late", start="2026-11-24T12:00:00+08:00"
    )
    at(monkeypatch, hours=4, minutes=15)
    assert action(client, headers, late, "check-in").status_code == 200
    assert status(client, late) == "IN_USE"


def test_missed_check_in_expires_and_releases_seat(monkeypatch, app, client):
    headers = student(client)
    record = create(client, headers)
    at(monkeypatch, minutes=16)
    assert action(client, headers, record, "check-in").status_code == 409
    assert status(client, record) == "EXPIRED"
    open_seats = client.get(
        "/api/v1/seats",
        query_string={
            "room_id": "lib-a101",
            "start_at": "2026-11-24T08:30:00+08:00",
            "end_at": "2026-11-24T09:30:00+08:00",
        },
    ).json["data"]["seats"]
    assert "lib-a101:A01" in [seat["id"] for seat in open_seats]
    assert count(app, "audit_events", "action='RESERVATION_EXPIRED'") == 1
    assert client.get(BASE).json["data"][0]["status"] == "EXPIRED"
    assert count(app, "audit_events", "action='RESERVATION_EXPIRED'") == 1


def test_check_in_is_idempotent_and_keeps_first_timestamp(monkeypatch, app, client):
    headers = student(client)
    record = create(client, headers)
    at(monkeypatch, minutes=-5)
    first = action(client, headers, record, "check-in").json["data"]
    at(monkeypatch, minutes=-1)
    replay = action(client, headers, record, "check-in").json["data"]
    assert replay == first
    assert replay["checked_in_at"].endswith("Z")
    assert count(app, "audit_events", "action='RESERVATION_CHECKED_IN'") == 1


def test_leave_return_and_deadline(monkeypatch, app, client):
    headers = student(client)
    record = create(client, headers, hours=3)
    at(monkeypatch, minutes=0)
    action(client, headers, record, "check-in")
    at(monkeypatch, minutes=20)
    left = action(client, headers, record, "leave").json["data"]
    assert left["status"] == "ON_LEAVE"
    assert left["leave_deadline"] == "2026-11-24T00:50:00.000000Z"
    assert action(client, headers, record, "leave").status_code == 200
    assert count(app, "audit_events", "action='RESERVATION_LEFT'") == 1

    at(monkeypatch, minutes=49)
    returned = action(client, headers, record, "return").json["data"]
    assert returned["status"] == "IN_USE"
    assert returned["leave_started_at"] is None and returned["leave_deadline"] is None

    at(monkeypatch, minutes=60)
    action(client, headers, record, "leave")
    at(monkeypatch, minutes=90)
    assert action(client, headers, record, "return").status_code == 200

    at(monkeypatch, minutes=91)
    action(client, headers, record, "leave")
    at(monkeypatch, minutes=122)
    assert action(client, headers, record, "return").status_code == 409
    assert status(client, record) == "EXPIRED"
    assert count(app, "audit_events", "action='RESERVATION_EXPIRED'") == 1


def test_finish_from_use_and_leave_and_auto_completion(monkeypatch, app, client):
    headers = student(client)
    record = create(client, headers)
    at(monkeypatch, minutes=0)
    action(client, headers, record, "check-in")
    at(monkeypatch, minutes=30)
    finished = action(client, headers, record, "finish").json["data"]
    assert finished["status"] == "COMPLETED"
    first_end = finished["ended_at"]
    at(monkeypatch, minutes=40)
    assert action(client, headers, record, "finish").json["data"]["ended_at"] == first_end
    assert count(app, "audit_events", "action='RESERVATION_COMPLETED'") == 1

    monkeypatch.setattr(reservations, "now_utc", lambda: NOW)
    other = create(client, headers, seat="lib-a101:A02", key="finish-leave")
    at(monkeypatch, minutes=0)
    action(client, headers, other, "check-in")
    action(client, headers, other, "leave")
    assert action(client, headers, other, "finish").json["data"]["status"] == "COMPLETED"

    monkeypatch.setattr(reservations, "now_utc", lambda: NOW)
    auto = create(client, headers, seat="lib-a101:A03", key="auto")
    at(monkeypatch, minutes=0)
    action(client, headers, auto, "check-in")
    at(monkeypatch, minutes=60)
    assert status(client, auto) == "COMPLETED"
    assert (
        client.get(BASE + "/" + auto["id"])
        .json["data"]["ended_at"]
        .startswith("2026-11-24T01:00:00")
    )
    assert count(app, "audit_events", "action='RESERVATION_AUTO_COMPLETED'") == 1


def test_invalid_transitions_and_access(monkeypatch, app, client):
    headers = student(client)
    record = create(client, headers)
    assert client.post(BASE + "/" + record["id"] + "/check-in").status_code == 403
    admin = app.test_client()
    admin_headers = {
        "X-CSRF-Token": login(admin, "admin01", "Admin1234").json["data"]["csrf_token"]
    }
    assert (
        admin.post(BASE + "/" + record["id"] + "/check-in", headers=admin_headers).status_code
        == 403
    )
    assert client.post(BASE + "/missing/check-in", headers=headers).status_code == 404
    assert client.post(BASE + "/missing/finish", headers=headers).status_code == 404

    other = app.test_client()
    other_headers = student(other, "student02", "Study1234")
    assert (
        other.post(BASE + "/" + record["id"] + "/check-in", headers=other_headers).status_code
        == 404
    )
    assert (
        other.post(BASE + "/" + record["id"] + "/leave", headers=other_headers).status_code == 404
    )

    assert action(client, headers, record, "leave").status_code == 409
    assert action(client, headers, record, "return").status_code == 409
    assert action(client, headers, record, "finish").status_code == 409

    at(monkeypatch, minutes=0)
    action(client, headers, record, "check-in")
    # A repeated return is harmless and keeps the first successful transition.
    assert action(client, headers, record, "return").status_code == 200
    at(monkeypatch, minutes=30)
    action(client, headers, record, "finish")
    assert action(client, headers, record, "check-in").status_code == 409
    assert action(client, headers, record, "leave").status_code == 409
