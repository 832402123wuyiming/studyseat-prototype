"""Phase 3 administrator rule versions and previewed resource closures."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import login

from studyseat import admin, reservations
from studyseat.db import get_db

BASE = "/api/v1"
NOW = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)
RULES = {
    "max_duration_minutes": 240,
    "max_advance_days": 7,
    "check_in_early_minutes": 10,
    "check_in_late_minutes": 15,
    "leave_limit_minutes": 30,
}


@pytest.fixture(autouse=True)
def frozen_time(monkeypatch):
    monkeypatch.setattr(reservations, "now_utc", lambda: NOW)


def student(client, username="832402116", password="123456"):
    return {"X-CSRF-Token": login(client, username, password).json["data"]["csrf_token"]}


def administrator(client):
    return {"X-CSRF-Token": login(client, "admin01", "Admin1234").json["data"]["csrf_token"]}


def create(client, headers, seat="lib-a101:A01", key="admin-1", start="2026-11-24T08:00:00+08:00"):
    end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
    response = client.post(
        BASE + "/reservations",
        json={
            "seat_id": seat,
            "start_at": start,
            "end_at": end,
            "idempotency_key": key,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json["data"]


def count(app, table, where="1=1"):
    with app.app_context():
        return get_db().execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def status(client, record):
    return client.get(BASE + "/reservations/" + record["id"]).json["data"]["status"]


def preview(client, headers, **body):
    payload = {"reason": "设备检修", **body}
    return client.post(BASE + "/admin/closures/preview", json=payload, headers=headers)


def apply(client, headers, token, **body):
    payload = {"reason": "设备检修", "token": token, **body}
    return client.post(BASE + "/admin/closures", json=payload, headers=headers)


def test_rule_version_is_additive_and_snapshots_are_kept(app, client):
    student_headers = student(client)
    record = create(client, student_headers)
    admin_client = app.test_client()
    admin_headers = administrator(admin_client)

    settings = dict(RULES, leave_limit_minutes=45, max_duration_minutes=120)
    response = admin_client.post(BASE + "/admin/rules", json=settings, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["data"] == {"version": 2, "settings": settings}
    assert admin_client.get(BASE + "/rules").json["data"] == {"version": 2, "settings": settings}
    assert count(app, "audit_events", "action='RULES_UPDATED'") == 1

    kept = client.get(BASE + "/reservations/" + record["id"]).json["data"]
    assert kept["rule_version_id"] == 1
    assert kept["rule_snapshot"]["leave_limit_minutes"] == 30

    fresh = create(
        client,
        student_headers,
        seat="lib-a101:A02",
        key="new-rule",
        start="2026-11-24T10:00:00+08:00",
    )
    assert fresh["rule_version_id"] == 2
    assert fresh["rule_snapshot"]["leave_limit_minutes"] == 45


@pytest.mark.parametrize(
    "changes",
    [
        {"max_duration_minutes": 0},
        {"max_duration_minutes": 1441},
        {"max_advance_days": -1},
        {"max_advance_days": 31},
        {"check_in_early_minutes": 121},
        {"check_in_late_minutes": "15"},
        {"leave_limit_minutes": 1.5},
        {"leave_limit_minutes": True},
        {"leave_limit_minutes": None},
    ],
)
def test_rule_validation_rejects_invalid_settings(app, changes):
    admin_client = app.test_client()
    headers = administrator(admin_client)
    body = {**RULES, **changes}
    response = admin_client.post(BASE + "/admin/rules", json=body, headers=headers)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_INPUT"
    assert count(app, "rule_versions") == 1


def test_rule_endpoint_access_and_csrf(app):
    admin_client = app.test_client()
    assert admin_client.post(BASE + "/admin/rules", json=RULES).status_code == 401
    headers = administrator(admin_client)
    assert admin_client.post(BASE + "/admin/rules", json=RULES).status_code == 403
    student_client = app.test_client()
    student_headers = student(student_client)
    assert (
        student_client.post(BASE + "/admin/rules", json=RULES, headers=student_headers).status_code
        == 403
    )
    assert admin_client.post(BASE + "/admin/rules", json=RULES, headers=headers).status_code == 200


def test_closure_preview_is_read_only_then_apply_cancels_pending(app, client):
    first_headers = student(client)
    first = create(client, first_headers)
    second_client = app.test_client()
    second_headers = student(second_client, "student02", "Study1234")
    second = create(second_client, second_headers, seat="lib-a101:A02", key="second")

    admin_client = app.test_client()
    admin_headers = administrator(admin_client)
    body = {"room_id": "lib-a101", "reason": "设备检修"}
    response = preview(admin_client, admin_headers, **body)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["can_apply"] is True
    assert data["cancellable_count"] == 2
    assert data["blocking_count"] == 0
    assert len(data["reservations"]) == 2
    assert {row["status"] for row in data["reservations"]} == {"PENDING_CHECKIN"}
    assert count(app, "resource_closures") == 0
    assert count(app, "audit_events", "action='RESERVATION_CLOSED'") == 0

    applied = apply(admin_client, admin_headers, data["token"], **body)
    assert applied.status_code == 201
    closure_id = applied.json["data"]["id"]
    assert sorted(applied.json["data"]["cancelled"]) == sorted([first["id"], second["id"]])
    assert count(app, "resource_closures") == 1
    assert count(app, "audit_events", "action='RESERVATION_CLOSED'") == 2
    assert count(app, "audit_events", "action='RESOURCE_CLOSED'") == 1
    assert status(client, first) == "CANCELLED"
    assert status(second_client, second) == "CANCELLED"

    blocked = client.post(
        BASE + "/reservations",
        json={
            "seat_id": "lib-a101:A03",
            "start_at": "2026-11-24T08:00:00+08:00",
            "end_at": "2026-11-24T09:00:00+08:00",
            "idempotency_key": "after-close",
        },
        headers=first_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "RESOURCE_UNAVAILABLE"
    assert preview(admin_client, admin_headers, **body).status_code == 409

    reopened = admin_client.post(
        BASE + "/admin/closures/" + closure_id + "/reopen", headers=admin_headers
    )
    assert reopened.status_code == 200
    assert reopened.json["data"]["reopened_at"] is not None
    assert count(app, "audit_events", "action='RESOURCE_REOPENED'") == 1
    assert status(client, first) == "CANCELLED"
    assert count(app, "resource_closures") == 1

    replacement = client.post(
        BASE + "/reservations",
        json={
            "seat_id": "lib-a101:A03",
            "start_at": "2026-11-24T08:00:00+08:00",
            "end_at": "2026-11-24T09:00:00+08:00",
            "idempotency_key": "after-reopen",
        },
        headers=first_headers,
    )
    assert replacement.status_code == 201
    again = admin_client.post(
        BASE + "/admin/closures/" + closure_id + "/reopen", headers=admin_headers
    )
    assert again.status_code == 200
    assert count(app, "audit_events", "action='RESOURCE_REOPENED'") == 1


def test_closure_blocks_in_use_and_temporarily_away(app, client, monkeypatch):
    headers = student(client)
    record = create(client, headers)
    admin_client = app.test_client()
    admin_headers = administrator(admin_client)

    monkeypatch.setattr(reservations, "now_utc", lambda: START)
    assert (
        client.post(
            BASE + "/reservations/" + record["id"] + "/check-in", headers=headers
        ).status_code
        == 200
    )
    data = preview(admin_client, admin_headers, room_id="lib-a101").json["data"]
    assert data["can_apply"] is False
    assert data["blocking_count"] == 1
    assert data["cancellable_count"] == 0
    blocked = apply(admin_client, admin_headers, data["token"], room_id="lib-a101")
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "CLOSURE_BLOCKED"
    assert count(app, "resource_closures") == 0
    assert status(client, record) == "IN_USE"

    client.post(BASE + "/reservations/" + record["id"] + "/finish", headers=headers)
    data = preview(admin_client, admin_headers, room_id="lib-a101").json["data"]
    assert data["can_apply"] is True
    assert data["cancellable_count"] == 0
    assert apply(admin_client, admin_headers, data["token"], room_id="lib-a101").status_code == 201


def test_stale_tampered_and_expired_previews_are_rejected(app, client):
    headers = student(client)
    record = create(client, headers)
    admin_client = app.test_client()
    admin_headers = administrator(admin_client)
    data = preview(admin_client, admin_headers, room_id="lib-a101").json["data"]
    assert data["cancellable_count"] == 1

    client.post(BASE + "/reservations/" + record["id"] + "/cancel", headers=headers)
    stale = apply(admin_client, admin_headers, data["token"], room_id="lib-a101")
    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "PREVIEW_STALE"
    assert count(app, "resource_closures") == 0

    tampered = apply(admin_client, admin_headers, data["token"] + "x", room_id="lib-a101")
    assert tampered.status_code == 409
    assert tampered.json["error"]["code"] == "PREVIEW_INVALID"

    expired_client = app.test_client()
    expired_headers = administrator(expired_client)
    original = admin.PREVIEW_MINUTES
    admin.PREVIEW_MINUTES = -1
    try:
        expired = preview(expired_client, expired_headers, room_id="lib-a101").json["data"]
    finally:
        admin.PREVIEW_MINUTES = original
    response = apply(expired_client, expired_headers, expired["token"], room_id="lib-a101")
    assert response.status_code == 409
    assert response.json["error"]["code"] == "PREVIEW_EXPIRED"


def test_seat_scope_and_closure_validation(app, client):
    first_headers = student(client)
    first = create(client, first_headers)
    second_client = app.test_client()
    second_headers = student(second_client, "student02", "Study1234")
    second = create(second_client, second_headers, seat="lib-a101:A02", key="seat-scope")

    admin_client = app.test_client()
    admin_headers = administrator(admin_client)
    data = preview(admin_client, admin_headers, seat_id="lib-a101:A01").json["data"]
    assert data["cancellable_count"] == 1
    assert data["reservations"][0]["id"] == first["id"]
    applied = apply(admin_client, admin_headers, data["token"], seat_id="lib-a101:A01")
    assert applied.status_code == 201
    assert status(client, first) == "CANCELLED"
    assert status(second_client, second) == "PENDING_CHECKIN"

    for body in (
        {"room_id": "lib-a101", "seat_id": "lib-a101:A01"},
        {},
        {"room_id": ""},
        {"room_id": "missing"},
        {"seat_id": "missing"},
    ):
        response = admin_client.post(
            BASE + "/admin/closures/preview", json={"reason": "x", **body}, headers=admin_headers
        )
        assert response.status_code in (400, 404)
    assert (
        admin_client.post(
            BASE + "/admin/closures/preview",
            json={"room_id": "lib-a101", "reason": "   "},
            headers=admin_headers,
        ).status_code
        == 400
    )
    assert (
        admin_client.post(
            BASE + "/admin/closures/preview",
            json={"room_id": "lib-a101", "reason": "x" * 201},
            headers=admin_headers,
        ).status_code
        == 400
    )
    assert (
        admin_client.post(
            BASE + "/admin/closures/missing/reopen", headers=admin_headers
        ).status_code
        == 404
    )

    student_client = app.test_client()
    student_headers = student(student_client)
    for path, method in (
        ("/admin/closures", "get"),
        ("/admin/closures/preview", "post"),
        ("/admin/closures", "post"),
        ("/admin/closures/x/reopen", "post"),
        ("/admin/resources", "get"),
    ):
        assert (
            getattr(student_client, method)(BASE + path, headers=student_headers).status_code == 403
        )
