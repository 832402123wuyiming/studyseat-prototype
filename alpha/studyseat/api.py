import json
import uuid

from flask import Blueprint, g, jsonify, render_template, request

from .auth import ApiError, authenticate, check_csrf, new_session, require_role
from .db import get_db, utc_now, write_transaction

bp = Blueprint("api", __name__)


def ok(data, status=200):
    return jsonify(data=data), status


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", "请提交 JSON 对象。")
    return body


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/api/v1/health")
def health():
    get_db().execute("SELECT version FROM schema_versions WHERE version=1").fetchone()
    return ok({"status": "ok", "schema_version": 1, "server_time": utc_now()})


@bp.get("/api/v1/auth/session")
def auth_session():
    if not g.auth_session:
        with write_transaction() as connection:
            csrf = new_session(connection)
    else:
        csrf = g.auth_session["csrf_token"]
    return ok({"user": g.identity, "csrf_token": csrf})


@bp.post("/api/v1/auth/login")
def login():
    check_csrf()
    body = json_body()
    username, password = body.get("username"), body.get("password")
    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or not 1 <= len(username) <= 100
        or not 1 <= len(password) <= 256
    ):
        raise ApiError(400, "INVALID_INPUT", "请输入账号和密码。")
    user = authenticate(username, password)
    with write_transaction() as connection:
        csrf = new_session(connection, user["id"])
        connection.execute(
            "INSERT INTO audit_events(actor_id,action,target_id,occurred_at) VALUES (?,?,?,?)",
            (user["id"], "LOGIN", user["id"], utc_now()),
        )
    return ok({"user": user, "csrf_token": csrf})


@bp.post("/api/v1/auth/logout")
@require_role()
def logout():
    check_csrf()
    with write_transaction() as connection:
        csrf = new_session(connection)
    return ok({"user": None, "csrf_token": csrf})


@bp.get("/api/v1/me")
@require_role()
def me():
    return ok(g.identity)


@bp.get("/api/v1/rooms")
@require_role()
def rooms():
    rows = (
        get_db()
        .execute(
            "SELECT r.*, COUNT(s.id) AS seat_count FROM rooms r LEFT JOIN seats s ON s.room_id=r.id GROUP BY r.id ORDER BY r.id"
        )
        .fetchall()
    )
    return ok([dict(row) for row in rows])


@bp.get("/api/v1/rules")
@require_role()
def rules():
    row = get_db().execute("SELECT * FROM rule_versions ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise ApiError(503, "NOT_INITIALIZED", "请先初始化演示数据。")
    return ok({"version": row["id"], "settings": json.loads(row["settings_json"])})


@bp.get("/api/v1/persistence-notes")
@require_role()
def list_notes():
    rows = (
        get_db()
        .execute(
            "SELECT * FROM persistence_notes WHERE owner_id=? ORDER BY created_at DESC",
            (g.identity["id"],),
        )
        .fetchall()
    )
    return ok([dict(row) for row in rows])


@bp.post("/api/v1/persistence-notes")
@require_role()
def add_note():
    check_csrf()
    content = json_body().get("content")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 200:
        raise ApiError(400, "INVALID_INPUT", "验证文本应为 1 至 200 个字符。")
    note = {
        "id": str(uuid.uuid4()),
        "owner_id": g.identity["id"],
        "content": content.strip(),
        "created_at": utc_now(),
    }
    with write_transaction() as connection:
        connection.execute(
            "INSERT INTO persistence_notes VALUES (:id,:owner_id,:content,:created_at)", note
        )
        connection.execute(
            "INSERT INTO audit_events(actor_id,action,target_id,occurred_at) VALUES (?,?,?,?)",
            (g.identity["id"], "PERSISTENCE_NOTE_CREATED", note["id"], note["created_at"]),
        )
    return ok(note, 201)


@bp.get("/api/v1/persistence-notes/<note_id>")
@require_role()
def get_note(note_id):
    row = (
        get_db()
        .execute(
            "SELECT * FROM persistence_notes WHERE id=? AND owner_id=?", (note_id, g.identity["id"])
        )
        .fetchone()
    )
    if row is None:
        raise ApiError(404, "NOT_FOUND", "记录不存在或不可访问。")
    return ok(dict(row))


@bp.get("/api/v1/admin/audit-events")
@require_role("admin")
def audit_events():
    rows = get_db().execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 100").fetchall()
    return ok([dict(row) for row in rows])
