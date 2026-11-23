import json

from werkzeug.security import generate_password_hash

from .db import utc_now, write_transaction

DEFAULT_RULES = {
    "max_duration_minutes": 240,
    "max_advance_days": 7,
    "check_in_early_minutes": 10,
    "check_in_late_minutes": 15,
    "leave_limit_minutes": 30,
}


def seed_demo():
    accounts = [
        ("student01", "832402116", "申子衡", "123456", "student"),
        ("student02", "student02", "学生 B", "Study1234", "student"),
        ("admin01", "admin01", "演示管理员", "Admin1234", "admin"),
    ]
    rooms = [
        ("lib-a101", "图书馆 3F 自习室 A101", "北校区图书馆 3F 东侧", 480, 1320, 120),
        ("east-b203", "东区教学楼 B203", "东区教学楼 2F", 480, 1320, 48),
        ("activity-24", "学生活动中心 24小时自习室", "西区学生活动中心 1F", 0, 1440, 64),
        ("lib-window", "图书馆 2F 临窗阅览区", "北校区图书馆 2F 西侧", 480, 1320, 80),
    ]
    with write_transaction() as connection:
        for user_id, username, name, password, role in accounts:
            if not connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                connection.execute(
                    "INSERT INTO users(id,username,display_name,password_hash,role) VALUES (?,?,?,?,?)",
                    (
                        user_id,
                        username,
                        name,
                        generate_password_hash(password, method="scrypt"),
                        role,
                    ),
                )
        for room_id, name, location, opens, closes, capacity in rooms:
            connection.execute(
                "INSERT OR IGNORE INTO rooms(id,name,location,opens_minute,closes_minute) VALUES (?,?,?,?,?)",
                (room_id, name, location, opens, closes),
            )
            for index in range(capacity):
                label = chr(65 + index // 30) + f"{index % 30 + 1:02d}"
                connection.execute(
                    "INSERT OR IGNORE INTO seats(id,room_id,label,enabled) VALUES (?,?,?,?)",
                    (f"{room_id}:{label}", room_id, label, int(index != capacity - 1)),
                )
        connection.execute(
            "INSERT OR IGNORE INTO rule_versions VALUES (1, ?, 'admin01', ?)",
            (json.dumps(DEFAULT_RULES), utc_now()),
        )
