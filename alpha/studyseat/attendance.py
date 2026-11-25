"""Attendance transitions and lazy timeout release.

Every operation runs in the caller's write transaction. Timeout release is a
single server-side sweep so that expired records stop occupying seats without a
background worker or a second occupancy counter.
"""

import json
from datetime import datetime, timedelta

from . import reservations
from .auth import ApiError
from .db import write_transaction
from .reservations import audit, owned, utc_text


def _time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _settings(row):
    value = row["rule_snapshot_json"] if "rule_snapshot_json" in row.keys() else None
    return json.loads(value) if value else row["rule_snapshot"]


def effective_status(row, now):
    """Return (status, ended_at) without writing; used by closure previews."""
    status = row["status"]
    end = _time(row["end_at"])
    if status == "PENDING_CHECKIN":
        deadline = _time(row["start_at"]) + timedelta(
            minutes=_settings(row)["check_in_late_minutes"]
        )
        if now > deadline:
            return "EXPIRED", utc_text(now)
    elif status == "IN_USE":
        if now >= end:
            return "COMPLETED", utc_text(end)
    elif status == "ON_LEAVE":
        if now >= end:
            return "COMPLETED", utc_text(end)
        if row["leave_deadline"] and now > _time(row["leave_deadline"]):
            return "EXPIRED", utc_text(now)
    return status, row["ended_at"]


def _close(connection, row, status, action, ended_at):
    cursor = connection.execute(
        "UPDATE reservations SET status=?, ended_at=? WHERE id=? AND status=?",
        (status, ended_at, row["id"], row["status"]),
    )
    if cursor.rowcount:
        audit(connection, row["student_id"], row["id"], action, _time(ended_at))
    return cursor.rowcount


def expire_due(connection, now=None):
    """Release missed check-ins, over-long absences and finished sessions."""
    now = now or reservations.now_utc()
    rows = connection.execute(
        """SELECT id,student_id,status,start_at,end_at,ended_at,leave_deadline,
                  rule_snapshot_json
           FROM reservations WHERE status IN ('PENDING_CHECKIN','IN_USE','ON_LEAVE')"""
    ).fetchall()
    released = 0
    for row in rows:
        status, ended_at = effective_status(row, now)
        if status == row["status"]:
            continue
        action = "RESERVATION_AUTO_COMPLETED" if status == "COMPLETED" else "RESERVATION_EXPIRED"
        released += _close(connection, row, status, action, ended_at)
    return released


def _transition(student_id, reservation_id, decide):
    with write_transaction() as connection:
        expire_due(connection)
        record = owned(connection, student_id, reservation_id)
        return decide(connection, record, reservations.now_utc())


def check_in(student_id, reservation_id):
    def decide(connection, record, now):
        if record["status"] == "IN_USE":
            return record
        if record["status"] != "PENDING_CHECKIN":
            raise ApiError(409, "STATE_NOT_ALLOWED", "当前预约状态不可签到。")
        start = _time(record["start_at"])
        settings = record["rule_snapshot"]
        earliest = start - timedelta(minutes=settings["check_in_early_minutes"])
        latest = start + timedelta(minutes=settings["check_in_late_minutes"])
        if now < earliest:
            raise ApiError(409, "STATE_NOT_ALLOWED", "签到尚未开始，请在签到窗口内操作。")
        if now > latest or now >= _time(record["end_at"]):
            raise ApiError(409, "STATE_NOT_ALLOWED", "签到窗口已结束，预约已超时。")
        connection.execute(
            "UPDATE reservations SET status='IN_USE', checked_in_at=? WHERE id=? AND status='PENDING_CHECKIN'",
            (utc_text(now), record["id"]),
        )
        audit(connection, student_id, record["id"], "RESERVATION_CHECKED_IN", now)
        return owned(connection, student_id, record["id"])

    return _transition(student_id, reservation_id, decide)


def leave(student_id, reservation_id):
    def decide(connection, record, now):
        if record["status"] == "ON_LEAVE":
            return record
        if record["status"] != "IN_USE":
            raise ApiError(409, "STATE_NOT_ALLOWED", "仅使用中的预约可以暂离。")
        if now >= _time(record["end_at"]):
            raise ApiError(409, "STATE_NOT_ALLOWED", "预约时段已结束。")
        deadline = now + timedelta(minutes=record["rule_snapshot"]["leave_limit_minutes"])
        connection.execute(
            """UPDATE reservations SET status='ON_LEAVE', leave_started_at=?, leave_deadline=?
               WHERE id=? AND status='IN_USE'""",
            (utc_text(now), utc_text(deadline), record["id"]),
        )
        audit(connection, student_id, record["id"], "RESERVATION_LEFT", now)
        return owned(connection, student_id, record["id"])

    return _transition(student_id, reservation_id, decide)


def return_to_seat(student_id, reservation_id):
    def decide(connection, record, now):
        if record["status"] == "IN_USE":
            return record
        if record["status"] != "ON_LEAVE":
            raise ApiError(409, "STATE_NOT_ALLOWED", "仅暂离中的预约可以返回。")
        if now > _time(record["leave_deadline"]):
            raise ApiError(409, "STATE_NOT_ALLOWED", "暂离已超过上限，预约已超时。")
        if now >= _time(record["end_at"]):
            raise ApiError(409, "STATE_NOT_ALLOWED", "预约时段已结束。")
        connection.execute(
            """UPDATE reservations SET status='IN_USE', leave_started_at=NULL, leave_deadline=NULL
               WHERE id=? AND status='ON_LEAVE'""",
            (record["id"],),
        )
        audit(connection, student_id, record["id"], "RESERVATION_RETURNED", now)
        return owned(connection, student_id, record["id"])

    return _transition(student_id, reservation_id, decide)


def finish(student_id, reservation_id):
    def decide(connection, record, now):
        if record["status"] == "COMPLETED":
            return record
        if record["status"] not in ("IN_USE", "ON_LEAVE"):
            raise ApiError(409, "STATE_NOT_ALLOWED", "当前预约状态不可结束。")
        connection.execute(
            "UPDATE reservations SET status='COMPLETED', ended_at=? WHERE id=?",
            (utc_text(now), record["id"]),
        )
        audit(connection, student_id, record["id"], "RESERVATION_COMPLETED", now)
        return owned(connection, student_id, record["id"])

    return _transition(student_id, reservation_id, decide)
