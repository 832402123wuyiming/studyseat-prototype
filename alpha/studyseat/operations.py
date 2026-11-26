"""Durable replay protection shared by student and administrator commands."""

import json

from .auth import ApiError
from .reservations import utc_text


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def replay(connection, actor, key, operation, payload):
    row = connection.execute(
        "SELECT * FROM operation_receipts WHERE actor_id=? AND idempotency_key=?", (actor, key)
    ).fetchone()
    if row and (row["operation"] != operation or row["payload_json"] != canonical(payload)):
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "此操作键已用于其他操作，请刷新后重试。")
    return row


def remember(connection, actor, key, operation, target, payload, now):
    connection.execute(
        "INSERT INTO operation_receipts VALUES (?,?,?,?,?,?)",
        (actor, key, operation, target, canonical(payload), utc_text(now)),
    )


def event(connection, actor, action, target, now, details=None, reservation_id=None):
    connection.execute(
        """INSERT INTO audit_events(actor_id,reservation_id,action,target_id,occurred_at,details_json)
           VALUES (?,?,?,?,?,?)""",
        (
            actor,
            reservation_id,
            action,
            target,
            utc_text(now),
            canonical({"result": "success", **(details or {})}),
        ),
    )
