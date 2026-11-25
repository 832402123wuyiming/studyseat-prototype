"""Administrator rule versions and resource closures.

A closure is only applied after a signed preview. The preview lists the exact
active reservations it would cancel and refuses to proceed while a reservation
is in use or temporarily away; the administrator must wait for those sessions to
end and preview again. Reopening a resource never revives cancelled bookings.
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app

from . import attendance, reservations
from .auth import ApiError
from .db import get_db, utc_now, write_transaction

RULE_BOUNDS = {
    "max_duration_minutes": (15, 1440),
    "max_advance_days": (0, 30),
    "check_in_early_minutes": (0, 120),
    "check_in_late_minutes": (0, 120),
    "leave_limit_minutes": (1, 240),
}
PREVIEW_MINUTES = 5


def _time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _text(value, maximum):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not 1 <= len(value) <= maximum or "\x00" in value:
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def update_rules(admin_id, body):
    settings = {}
    for key, (low, high) in RULE_BOUNDS.items():
        value = body.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ApiError(400, "INVALID_INPUT", f"{key} 应为 {low} 至 {high} 的整数。")
        settings[key] = value
    with write_transaction() as connection:
        row = connection.execute("SELECT MAX(id) AS version FROM rule_versions").fetchone()
        version = (row["version"] or 0) + 1
        connection.execute(
            "INSERT INTO rule_versions(id,settings_json,created_by,created_at) VALUES (?,?,?,?)",
            (
                version,
                json.dumps(settings, ensure_ascii=False, sort_keys=True),
                admin_id,
                utc_now(),
            ),
        )
        connection.execute(
            "INSERT INTO audit_events(actor_id,action,target_id,occurred_at) VALUES (?,?,?,?)",
            (admin_id, "RULES_UPDATED", str(version), utc_now()),
        )
    return {"version": version, "settings": settings}


def _scope(body):
    room_id, seat_id = body.get("room_id"), body.get("seat_id")
    if bool(room_id) == bool(seat_id):
        raise ApiError(400, "INVALID_INPUT", "关闭范围必须且只能选择房间或座位之一。")
    reason = _text(body.get("reason"), 200)
    if reason is None:
        raise ApiError(400, "INVALID_INPUT", "关闭原因应为 1 至 200 个字符。")
    if room_id:
        room_id = _text(room_id, 100)
        if room_id is None:
            raise ApiError(400, "INVALID_INPUT", "房间标识无效。")
    else:
        seat_id = _text(seat_id, 100)
        if seat_id is None:
            raise ApiError(400, "INVALID_INPUT", "座位标识无效。")
    return room_id, seat_id, reason


def _resource(connection, room_id, seat_id):
    if room_id:
        row = connection.execute("SELECT id,name FROM rooms WHERE id=?", (room_id,)).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "房间不存在。")
        return {"room_id": room_id, "seat_id": None, "label": row["name"]}
    row = connection.execute(
        """SELECT s.id,s.label,s.room_id,r.name FROM seats s JOIN rooms r ON r.id=s.room_id
           WHERE s.id=?""",
        (seat_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "座位不存在。")
    return {
        "room_id": None,
        "seat_id": seat_id,
        "label": f"{row['name']} · {row['label']}",
    }


def _open_closure(connection, room_id, seat_id):
    if room_id:
        return connection.execute(
            "SELECT id FROM resource_closures WHERE reopened_at IS NULL AND room_id=?",
            (room_id,),
        ).fetchone()
    return connection.execute(
        "SELECT id FROM resource_closures WHERE reopened_at IS NULL AND seat_id=?",
        (seat_id,),
    ).fetchone()


def _affected(connection, room_id, seat_id, now, effective):
    condition, parameter = ("s.room_id=?", room_id) if room_id else ("r.seat_id=?", seat_id)
    rows = connection.execute(
        f"""SELECT r.id,r.student_id,r.status,r.start_at,r.end_at,r.ended_at,r.leave_deadline,
                   r.rule_snapshot_json,s.label AS seat_label,s.room_id,
                   rooms.name AS room_name,u.display_name AS student_name
            FROM reservations r JOIN seats s ON s.id=r.seat_id
            JOIN rooms ON rooms.id=s.room_id JOIN users u ON u.id=r.student_id
            WHERE r.status IN {reservations.ACTIVE} AND {condition}
            ORDER BY r.start_at, r.id""",
        (parameter,),
    ).fetchall()
    result = []
    for row in rows:
        status, ended_at = (
            attendance.effective_status(row, now) if effective else (row["status"], row["ended_at"])
        )
        if status not in ("PENDING_CHECKIN", "IN_USE", "ON_LEAVE"):
            continue
        result.append(
            {
                "id": row["id"],
                "student_id": row["student_id"],
                "status": status,
                "student_name": row["student_name"],
                "room_name": row["room_name"],
                "seat_label": row["seat_label"],
                "start_at": row["start_at"],
                "end_at": row["end_at"],
            }
        )
    return result


def _payload(room_id, seat_id, reason, rows):
    return {
        "room_id": room_id,
        "seat_id": seat_id,
        "reason": reason,
        "reservations": [
            {
                "id": row["id"],
                "status": row["status"],
                "start_at": row["start_at"],
                "end_at": row["end_at"],
            }
            for row in rows
        ],
    }


def _sign(payload, issued, expires):
    body = {"payload": payload, "issued_at": issued, "expires_at": expires}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(current_app.config["SECRET_KEY"].encode(), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode("ascii") + "." + signature


def _verify(token):
    if not isinstance(token, str) or token.count(".") != 1:
        raise ApiError(409, "PREVIEW_INVALID", "关闭预览凭据无效，请重新预览。")
    encoded, signature = token.split(".")
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise ApiError(409, "PREVIEW_INVALID", "关闭预览凭据无效，请重新预览。") from None
    expected = hmac.new(current_app.config["SECRET_KEY"].encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ApiError(409, "PREVIEW_INVALID", "关闭预览凭据无效，请重新预览。")
    body = json.loads(raw)
    if _time(body["expires_at"]) < datetime.now(timezone.utc):
        raise ApiError(409, "PREVIEW_EXPIRED", "关闭预览已过期，请重新预览。")
    return body["payload"]


def preview(user_id, body):
    room_id, seat_id, reason = _scope(body)
    connection = get_db()
    _resource(connection, room_id, seat_id)
    if _open_closure(connection, room_id, seat_id):
        raise ApiError(409, "ALREADY_CLOSED", "该资源已有未重开的关闭记录。")
    now = reservations.now_utc()
    rows = _affected(connection, room_id, seat_id, now, effective=True)
    blocking = [row for row in rows if row["status"] in ("IN_USE", "ON_LEAVE")]
    issued = utc_now()
    expires = (
        (datetime.now(timezone.utc) + timedelta(minutes=PREVIEW_MINUTES))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    payload = _payload(room_id, seat_id, reason, rows)
    return {
        "scope": {"room_id": room_id, "seat_id": seat_id},
        "reason": reason,
        "reservations": rows,
        "cancellable_count": sum(row["status"] == "PENDING_CHECKIN" for row in rows),
        "blocking_count": len(blocking),
        "can_apply": not blocking,
        "token": _sign(payload, issued, expires),
        "expires_at": expires,
    }


def close(user_id, body):
    room_id, seat_id, reason = _scope(body)
    token = _verify(body.get("token"))
    now = reservations.now_utc()
    with write_transaction() as connection:
        _resource(connection, room_id, seat_id)
        if _open_closure(connection, room_id, seat_id):
            raise ApiError(409, "ALREADY_CLOSED", "该资源已有未重开的关闭记录。")
        attendance.expire_due(connection)
        rows = _affected(connection, room_id, seat_id, now, effective=False)
        if _payload(room_id, seat_id, reason, rows) != token:
            raise ApiError(409, "PREVIEW_STALE", "关闭影响已变化，请重新预览后确认。")
        blocking = [row for row in rows if row["status"] in ("IN_USE", "ON_LEAVE")]
        if blocking:
            raise ApiError(
                409,
                "CLOSURE_BLOCKED",
                f"仍有 {len(blocking)} 条使用中或暂离中的预约，请结束后重新预览。",
            )
        closure_id = str(uuid.uuid4())
        stamp = utc_now()
        connection.execute(
            """INSERT INTO resource_closures(id,room_id,seat_id,reason,created_by,created_at)
               VALUES (?,?,?,?,?,?)""",
            (closure_id, room_id, seat_id, reason, user_id, stamp),
        )
        cancelled = []
        for row in rows:
            connection.execute(
                "UPDATE reservations SET status='CANCELLED', ended_at=? WHERE id=?",
                (stamp, row["id"]),
            )
            reservations.audit(connection, row["student_id"], row["id"], "RESERVATION_CLOSED", now)
            cancelled.append(row["id"])
        connection.execute(
            "INSERT INTO audit_events(actor_id,action,target_id,occurred_at) VALUES (?,?,?,?)",
            (user_id, "RESOURCE_CLOSED", closure_id, stamp),
        )
        return {"id": closure_id, "cancelled": cancelled}


def reopen(user_id, closure_id):
    with write_transaction() as connection:
        row = connection.execute(
            "SELECT * FROM resource_closures WHERE id=?", (closure_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "关闭记录不存在。")
        if row["reopened_at"] is None:
            stamp = utc_now()
            connection.execute(
                "UPDATE resource_closures SET reopened_at=? WHERE id=?", (stamp, closure_id)
            )
            connection.execute(
                "INSERT INTO audit_events(actor_id,action,target_id,occurred_at) VALUES (?,?,?,?)",
                (user_id, "RESOURCE_REOPENED", closure_id, stamp),
            )
            row = connection.execute(
                "SELECT * FROM resource_closures WHERE id=?", (closure_id,)
            ).fetchone()
        return dict(row)


def closures():
    rows = (
        get_db()
        .execute(
            """SELECT c.*, r.name AS room_name, s.label AS seat_label, u.display_name AS created_by_name
           FROM resource_closures c LEFT JOIN rooms r ON r.id=c.room_id
           LEFT JOIN seats s ON s.id=c.seat_id LEFT JOIN users u ON u.id=c.created_by
           ORDER BY c.created_at DESC, c.id"""
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def resources():
    connection = get_db()
    rooms = [
        dict(row) for row in connection.execute("SELECT id,name,enabled FROM rooms ORDER BY id")
    ]
    seats = [
        dict(row)
        for row in connection.execute(
            "SELECT id,room_id,label,enabled FROM seats ORDER BY room_id,label"
        )
    ]
    return {"rooms": rooms, "seats": seats}
