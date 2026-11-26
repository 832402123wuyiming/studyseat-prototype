"""Six-state lifecycle. All clock decisions happen after acquiring the write lock."""

import json
from datetime import datetime, timedelta

from . import reservations as r
from .auth import ApiError
from .db import write_transaction
from .operations import event, remember, replay
from .policy import valid_settings


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def snapshot(record):
    try:
        settings = record.get("rule_snapshot")
        if settings is None:
            settings = json.loads(record["rule_snapshot_json"])
        if not valid_settings(settings):
            raise ValueError
        return settings
    except (ValueError, TypeError, KeyError):
        raise ApiError(503, "RULES_UNAVAILABLE", "预约规则快照无效，请联系管理员。") from None


def due(record, now):
    status = record["status"]
    end = instant(record["end_at"])
    if status == "PENDING_CHECKIN":
        deadline = instant(record["start_at"]) + timedelta(
            minutes=snapshot(record)["check_in_late_minutes"]
        )
        if now > deadline or now >= end:
            return "EXPIRED", min(deadline, end), "CHECKIN_EXPIRED"
    elif status == "IN_USE" and now >= end:
        return "COMPLETED", end, "RESERVATION_COMPLETED"
    elif status == "ON_LEAVE":
        deadline = instant(record["leave_deadline"])
        # A later observation preserves which deadline happened first. Ties end normally.
        if deadline < end and now > deadline:
            return "EXPIRED", deadline, "LEAVE_EXPIRED"
        if now >= end:
            return "COMPLETED", end, "RESERVATION_COMPLETED"
    return None


def reconcile(connection, now):
    changed = []
    for row in connection.execute(
        f"SELECT * FROM reservations WHERE status IN {r.ACTIVE}"
    ).fetchall():
        record = dict(row)
        result = due(record, now)
        if result:
            status, effective, action = result
            connection.execute(
                "UPDATE reservations SET status=?,ended_at=?,state_version=state_version+1 WHERE id=?",
                (status, r.utc_text(effective), record["id"]),
            )
            event(
                connection,
                None,
                action,
                record["id"],
                now,
                {"effective_at": r.utc_text(effective), "source": "timeout"},
                record["id"],
            )
            changed.append(record["id"])
    return changed


def sweep():
    with write_transaction() as connection:
        return reconcile(connection, r.now_utc())


def transition(student_id, reservation_id, action, key, expected_version=None):
    cyclic = action in ("leave", "return")
    if cyclic and (type(expected_version) is not int or expected_version < 0):
        raise ApiError(400, "INVALID_INPUT", "页面状态凭据无效，请刷新预约后重试。")
    # Due transitions and the requested action share one lock. A state error is
    # raised after commit so a rejected late action cannot roll back its timeout.
    with write_transaction() as connection:
        r.owned(connection, student_id, reservation_id)
        now = r.now_utc()
        reconcile(connection, now)
        record = r.owned(connection, student_id, reservation_id)
        payload = {"reservation_id": reservation_id}
        if cyclic:
            payload["expected_version"] = expected_version
        if replay(connection, student_id, key, action, payload):
            return record
        settings = snapshot(record)
        status = record["status"]
        error = None
        error_code = "STATE_NOT_ALLOWED"
        updates = None
        if cyclic and record["state_version"] != expected_version:
            error_code = "STALE_RESERVATION"
            error = "预约状态已改变，请刷新后按当前状态重新操作。"
        elif action == "check-in":
            if record["checked_in_at"] is not None:
                pass  # Retry cannot return from leave or revive a terminal reservation.
            elif status != "PENDING_CHECKIN":
                error = "预约已结束，不能签到。"
            elif now < instant(record["start_at"]) - timedelta(
                minutes=settings["check_in_early_minutes"]
            ):
                error = "签到窗口尚未开放。"
            else:
                updates = ("status='IN_USE',checked_in_at=?", (r.utc_text(now),))
        elif action == "leave":
            if status == "ON_LEAVE":
                pass
            elif status != "IN_USE":
                error = "仅使用中预约可暂离。"
            else:
                deadline = min(
                    now + timedelta(minutes=settings["leave_limit_minutes"]),
                    instant(record["end_at"]),
                )
                updates = (
                    "status='ON_LEAVE',leave_started_at=?,leave_deadline=?",
                    (r.utc_text(now), r.utc_text(deadline)),
                )
        elif action == "return":
            if status == "IN_USE" and record["leave_started_at"] is not None:
                pass
            elif status != "ON_LEAVE":
                error = "仅暂离中预约可返回。"
            else:
                updates = ("status='IN_USE'", ())
        elif action == "finish":
            if status == "COMPLETED":
                pass
            elif status not in ("IN_USE", "ON_LEAVE"):
                error = "仅使用中或暂离中预约可结束。"
            else:
                updates = ("status='COMPLETED',ended_at=?", (r.utc_text(now),))
        else:
            raise ValueError("Unknown lifecycle action")
        if not error:
            if updates:
                sql, parameters = updates
                connection.execute(
                    f"UPDATE reservations SET {sql},state_version=state_version+1 WHERE id=?",
                    (*parameters, reservation_id),
                )
                event(
                    connection,
                    student_id,
                    {
                        "check-in": "CHECKED_IN",
                        "leave": "LEFT_SEAT",
                        "return": "RETURNED",
                        "finish": "RESERVATION_FINISHED",
                    }[action],
                    reservation_id,
                    now,
                    reservation_id=reservation_id,
                )
            remember(connection, student_id, key, action, reservation_id, payload, now)
            record = r.owned(connection, student_id, reservation_id)
    if error:
        raise ApiError(409, error_code, error)
    return record
