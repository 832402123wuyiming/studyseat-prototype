"""Verify real HTTP traffic across two independent service processes."""

import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        environment = dict(os.environ)
        environment.update(
            STUDYSEAT_SECRET_KEY=secrets.token_hex(32),
            STUDYSEAT_DATABASE=str(Path(directory) / "smoke.sqlite3"),
            STUDYSEAT_HTTPS="0",
        )
        subprocess.run(
            [sys.executable, "-m", "flask", "--app", "studyseat", "init-db", "--demo"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        browser = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

        def request(path, body=None, csrf=None):
            headers = {"Content-Type": "application/json"}
            if csrf:
                headers["X-CSRF-Token"] = csrf
            req = urllib.request.Request(
                origin + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            with browser.open(req, timeout=3) as response:
                return json.load(response)["data"]

        def start():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "flask",
                    "--app",
                    "studyseat",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(100):
                    try:
                        request("/api/v1/health")
                        return process
                    except (OSError, urllib.error.URLError):
                        if process.poll() is not None:
                            raise RuntimeError("Service exited during startup")
                        time.sleep(0.1)
                raise RuntimeError("Service startup timed out")
            except Exception:
                process.terminate()
                process.wait(timeout=10)
                raise

        first = start()
        try:
            csrf = request("/api/v1/auth/session")["csrf_token"]
            logged_in = request(
                "/api/v1/auth/login", {"username": "832402116", "password": "123456"}, csrf
            )
            note = request(
                "/api/v1/persistence-notes",
                {"content": "独立进程重启持久化验证"},
                logged_in["csrf_token"],
            )
            tomorrow = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
            booking = {
                "seat_id": "lib-a101:A01",
                "start_at": f"{tomorrow}T09:00:00+08:00",
                "end_at": f"{tomorrow}T10:00:00+08:00",
                "idempotency_key": "restart-smoke",
            }
            seats_query = "/api/v1/seats?" + urlencode(
                {
                    "room_id": "lib-a101",
                    "start_at": booking["start_at"],
                    "end_at": booking["end_at"],
                }
            )
            assert len(request(seats_query)["seats"]) == 119
            reservation = request("/api/v1/reservations", booking, logged_in["csrf_token"])
        finally:
            first.terminate()
            first.wait(timeout=10)
        second = start()
        try:
            assert first.pid != second.pid
            assert request("/api/v1/me")["id"] == "student01"
            assert request("/api/v1/persistence-notes")[0] == note
            assert request("/api/v1/reservations") == [reservation]
            assert request(seats_query)["seats"] == []
            csrf = request("/api/v1/auth/session")["csrf_token"]
            relogged = request(
                "/api/v1/auth/login", {"username": "832402116", "password": "123456"}, csrf
            )
            assert request("/api/v1/reservations") == [reservation]
            replay = request("/api/v1/reservations", booking, relogged["csrf_token"])
            assert replay == reservation
            cancelled = request(
                f"/api/v1/reservations/{reservation['id']}/cancel", {}, relogged["csrf_token"]
            )
            assert (
                request(
                    f"/api/v1/reservations/{reservation['id']}/cancel", {}, relogged["csrf_token"]
                )
                == cancelled
            )
            student_b = request(
                "/api/v1/auth/login",
                {"username": "student02", "password": "Study1234"},
                relogged["csrf_token"],
            )
            assert request("/api/v1/reservations") == []
            assert len(request(seats_query)["seats"]) == 119
            assert (
                request("/api/v1/reservations", booking, student_b["csrf_token"])["student_id"]
                == "student02"
            )
            request(
                "/api/v1/auth/login",
                {"username": "admin01", "password": "Admin1234"},
                student_b["csrf_token"],
            )
            assert any(
                event["target_id"] == note["id"] for event in request("/api/v1/admin/audit-events")
            )
            events = request("/api/v1/admin/audit-events")
            assert (
                sum(
                    e["reservation_id"] == reservation["id"]
                    and e["action"] == "RESERVATION_CREATED"
                    for e in events
                )
                == 1
            )
            assert (
                sum(
                    e["reservation_id"] == reservation["id"]
                    and e["action"] == "RESERVATION_CANCELLED"
                    for e in events
                )
                == 1
            )
        finally:
            second.terminate()
            second.wait(timeout=10)
        report = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "result": "passed",
            "first_pid": first.pid,
            "second_pid": second.pid,
            "checks": [
                "HTTP health",
                "student login",
                "database write",
                "process restart",
                "session restored",
                "note restored",
                "reservation and session restored across real process restart",
                "reservation survives relogin",
                "create replay returns original reservation",
                "duplicate cancel preserves original receipt and single audit",
                "student B can reserve released interval",
                "admin shares audit data",
            ],
            "scope": "Real persisted reservations and foundation persistence notes",
            "reservation_id": reservation["id"],
        }
        target = (
            Path(os.environ.get("STUDYSEAT_EVIDENCE_DIR", str(ROOT / "evidence")))
            / "process-smoke.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
