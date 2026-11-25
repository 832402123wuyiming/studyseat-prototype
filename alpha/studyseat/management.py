"""Shared administrator data, immutable rules and preview/revalidate closure workflow."""

import hashlib
import json
import uuid

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import reservations as r
from .auth import ApiError
from .db import get_db, write_transaction
from .lifecycle import reconcile, sweep
from .operations import canonical, event, remember, replay
from .policy import RULE_LIMITS


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != set(RULE_LIMITS):
        raise ApiError(400, "INVALID_INPUT", "请提交完整的五项规则，不能包含额外字段。")
    for key, (low, high) in RULE_LIMITS.items():
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ApiError(400, "INVALID_INPUT", f"{key} 必须为 {low}—{high} 的整数。")
    return settings


def save_rules(actor, settings, base_version, key):
    validate_settings(settings)
    if type(base_version) is not int or base_version < 1:
        raise ApiError(400, "INVALID_INPUT", "缺少当前规则版本，请重新加载。")
    payload = {"settings": settings, "base_version": base_version}
    with write_transaction() as connection:
        receipt = replay(connection, actor, key, "save-rules", payload)
        if receipt:
            row = connection.execute(
                "SELECT * FROM rule_versions WHERE id=?", (receipt["target_id"],)
            ).fetchone()
            return {"version": row["id"], "settings": json.loads(row["settings_json"])}
        version, current = r.rules(connection)
        if version != base_version:
            raise ApiError(409, "RULE_VERSION_CONFLICT", "规则已被更新，请重新加载后修改。")
        now = r.now_utc()
        if current != settings:
            version += 1
            connection.execute(
                "INSERT INTO rule_versions VALUES (?,?,?,?)",
                (version, canonical(settings), actor, r.utc_text(now)),
            )
            event(
                connection,
                actor,
                "RULES_UPDATED",
                str(version),
                now,
                {"previous_version": base_version, "settings": settings},
            )
        remember(connection, actor, key, "save-rules", str(version), payload, now)
        return {"version": version, "settings": settings}


def scope(connection, body):
    room_id, seat_id = body.get("room_id"), body.get("seat_id")
    if (room_id is None) == (seat_id is None):
        raise ApiError(400, "INVALID_INPUT", "请选择一个房间或一个座位。")
    value = room_id if room_id is not None else seat_id
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ApiError(400, "INVALID_INPUT", "资源编号无效。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, "INVALID_INPUT", "资源编号包含无效字符。") from None
    resource = (
        r.room_resource(connection, room_id)
        if room_id is not None
        else r.seat_resource(connection, seat_id)
    )
    reason = body.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200 or "\x00" in reason:
        raise ApiError(400, "INVALID_INPUT", "请填写 1—200 字的关闭原因。")
    try:
        reason.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, "INVALID_INPUT", "关闭原因包含无效字符。") from None
    return {"room_id": room_id, "seat_id": seat_id, "reason": reason.strip()}, dict(resource)


def impact(connection, target, resource):
    # Include every active reservation, including later dates. Closures are immediate
    # and remain in force until explicitly reopened, never silently scheduled.
    rows = connection.execute(
        r.SELECT
        + f" WHERE r.status IN {r.ACTIVE} AND "
        + ("s.room_id=?" if target["room_id"] else "r.seat_id=?")
        + " ORDER BY r.id",
        (target["room_id"] or target["seat_id"],),
    ).fetchall()
    records = [r.serialize(row) for row in rows]
    actual_room = target["room_id"] or resource["room_id"]
    closures = [
        dict(row)
        for row in connection.execute(
            """SELECT c.* FROM resource_closures c LEFT JOIN seats s ON s.id=c.seat_id
        WHERE c.reopened_at IS NULL AND (c.room_id=? OR s.room_id=?) ORDER BY c.id""",
            (actual_room, actual_room),
        )
    ]
    fingerprint = hashlib.sha256(
        canonical(
            {"target": target, "resource": resource, "records": records, "closures": closures}
        ).encode()
    ).hexdigest()
    return {
        "affected": [record for record in records if record["status"] == "PENDING_CHECKIN"],
        "blockers": [record for record in records if record["status"] in ("IN_USE", "ON_LEAVE")],
        "fingerprint": fingerprint,
    }


def signer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="studyseat-closure-preview-v1"
    )


def preview(actor, body):
    # Read transaction is a consistent snapshot. Never run reconciliation or write
    # audit/preview rows here: preview must have no database side effects.
    connection = get_db()
    connection.execute("BEGIN")
    try:
        target, resource = scope(connection, body)
        result = impact(connection, target, resource)
        token = signer().dumps(
            {"actor": actor, "target": target, "fingerprint": result["fingerprint"]}
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        **result,
        "target": target,
        "preview_token": token,
        "expires_in_seconds": 300,
        "server_time": r.utc_text(r.now_utc()),
        "mode": "immediate_until_reopened",
    }


def closure_record(connection, closure_id):
    row = connection.execute("SELECT * FROM resource_closures WHERE id=?", (closure_id,)).fetchone()
    if not row:
        raise ApiError(404, "NOT_FOUND", "关闭记录不存在。")
    return dict(row)


def close(actor, body, key):
    token = body.get("preview_token")
    if not isinstance(token, str) or len(token) > 4096:
        raise ApiError(400, "INVALID_INPUT", "请先预览关闭影响。")
    payload = {"preview_token": token}
    with write_transaction() as connection:
        receipt = replay(connection, actor, key, "close-resource", payload)
        if receipt:
            return closure_record(connection, receipt["target_id"])
        try:
            saved = signer().loads(token, max_age=300)
        except (BadSignature, SignatureExpired):
            raise ApiError(409, "PREVIEW_STALE", "预览已失效，请重新预览。") from None
        if saved["actor"] != actor:
            raise ApiError(403, "FORBIDDEN", "预览不属于当前管理员。")
        target, resource = scope(connection, saved["target"])
        now = r.now_utc()
        result = impact(connection, target, resource)
        if result["fingerprint"] != saved["fingerprint"]:
            raise ApiError(409, "PREVIEW_STALE", "影响范围已改变，请重新预览。")
        if result["blockers"]:
            raise ApiError(
                409, "RESOURCE_IN_USE", "存在使用中或暂离中预约，请现场处理并结束后重新预览。"
            )
        actual_room = target["room_id"] or resource["room_id"]
        if r.closed(connection, actual_room, target["seat_id"]):
            raise ApiError(409, "RESOURCE_UNAVAILABLE", "资源已关闭，请先检查关闭记录。")
        # Deadlines may have passed without changing raw rows since the preview.
        # Require a fresh preview of reconciled data rather than canceling no-shows.
        from .lifecycle import due

        if any(due(record, now) for record in result["affected"]):
            raise ApiError(409, "PREVIEW_STALE", "预约已到期，请刷新管理数据后重新预览。")
        closure_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO resource_closures(id,room_id,seat_id,reason,created_by,created_at) VALUES (?,?,?,?,?,?)",
            (
                closure_id,
                target["room_id"],
                target["seat_id"],
                target["reason"],
                actor,
                r.utc_text(now),
            ),
        )
        for record in result["affected"]:
            connection.execute(
                "UPDATE reservations SET status='CANCELLED',ended_at=?,state_version=state_version+1 WHERE id=?",
                (r.utc_text(now), record["id"]),
            )
            event(
                connection,
                actor,
                "RESERVATION_CANCELLED_BY_CLOSURE",
                closure_id,
                now,
                {"reason": target["reason"]},
                record["id"],
            )
        event(
            connection,
            actor,
            "RESOURCE_CLOSED",
            closure_id,
            now,
            {**target, "reservation_ids": [x["id"] for x in result["affected"]]},
        )
        remember(connection, actor, key, "close-resource", closure_id, payload, now)
        return closure_record(connection, closure_id)


def reopen(actor, closure_id, key):
    payload = {"closure_id": closure_id}
    with write_transaction() as connection:
        record = closure_record(connection, closure_id)
        if replay(connection, actor, key, "reopen-resource", payload):
            return record
        now = r.now_utc()
        if record["reopened_at"] is None:
            connection.execute(
                "UPDATE resource_closures SET reopened_at=? WHERE id=?",
                (r.utc_text(now), closure_id),
            )
            event(connection, actor, "RESOURCE_REOPENED", closure_id, now)
        remember(connection, actor, key, "reopen-resource", closure_id, payload, now)
        return closure_record(connection, closure_id)


def list_reservations():
    sweep()
    return [
        r.serialize(row) for row in get_db().execute(r.SELECT + " ORDER BY r.start_at DESC,r.id")
    ]


def resources():
    return {
        "seats": [
            dict(row) for row in get_db().execute("SELECT * FROM seats ORDER BY room_id,label")
        ],
        "closures": [
            dict(row)
            for row in get_db().execute(
                "SELECT * FROM resource_closures ORDER BY created_at DESC,id"
            )
        ],
    }


def save_hours(actor, room_id, body, key):
    opens, closes = body.get("opens_minute"), body.get("closes_minute")
    if type(opens) is not int or type(closes) is not int or not 0 <= opens < closes <= 1440:
        raise ApiError(400, "INVALID_INPUT", "开放分钟应满足 0 ≤ 开始 < 结束 ≤ 1440。")
    payload = {
        "room_id": room_id,
        "opens_minute": opens,
        "closes_minute": closes,
        "base_hours": body.get("base_hours"),
    }
    with write_transaction() as connection:
        if replay(connection, actor, key, "save-hours", payload):
            return dict(r.room_resource(connection, room_id))
        resource = dict(r.room_resource(connection, room_id))
        if body.get("base_hours") != [resource["opens_minute"], resource["closes_minute"]]:
            raise ApiError(409, "RESOURCE_CHANGED", "开放时间已更新，请重新加载。")
        now = r.now_utc()
        reconcile(connection, now)
        candidate = dict(resource, opens_minute=opens, closes_minute=closes)
        rows = connection.execute(
            r.SELECT + f" WHERE s.room_id=? AND r.status IN {r.ACTIVE}", (room_id,)
        ).fetchall()
        for row in rows:
            from .lifecycle import instant

            # Reuse daily opening validation without reapplying new booking limits
            # to existing snapshots or rejecting a start already in the past.
            start, end = instant(row["start_at"]), instant(row["end_at"])
            try:
                r.validate_policy(
                    dict(candidate, enabled=1, room_enabled=1),
                    start,
                    end,
                    {"max_duration_minutes": 1440 * 365, "max_advance_days": 36500},
                    start,
                )
            except ApiError:
                raise ApiError(
                    409,
                    "RESERVATIONS_AFFECTED",
                    "新开放时间覆盖不了现有有效预约，请先处理相关预约。",
                ) from None
        if [opens, closes] != [resource["opens_minute"], resource["closes_minute"]]:
            connection.execute(
                "UPDATE rooms SET opens_minute=?,closes_minute=? WHERE id=?",
                (opens, closes, room_id),
            )
            event(connection, actor, "ROOM_HOURS_UPDATED", room_id, now, payload)
        remember(connection, actor, key, "save-hours", room_id, payload, now)
        return dict(r.room_resource(connection, room_id))
