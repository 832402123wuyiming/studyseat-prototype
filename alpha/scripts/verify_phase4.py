"""Run the Alpha delivery checks on isolated databases and real local HTTP."""

import importlib.metadata
import json
import os
import platform
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault(
    "STUDYSEAT_EVIDENCE_DIR", str(Path(__file__).resolve().parents[1] / "evidence/phase4")
)
from verify_phase2 import ALPHA, EVIDENCE, NODE, browser_case, run  # noqa: E402


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "verification.json").unlink(missing_ok=True)
    run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={EVIDENCE / 'pytest.xml'}"],
        "pytest.txt",
        ALPHA,
    )
    run([sys.executable, "-m", "ruff", "check", "."], "ruff-check.txt", ALPHA)
    run([sys.executable, "-m", "ruff", "format", "--check", "."], "ruff-format.txt", ALPHA)
    for file in [ALPHA / "studyseat/static/app.js", *sorted((ALPHA / "tests").glob("*.cjs"))]:
        run([NODE, "--check", str(file)], f"syntax-{file.name}.txt")
    restart_env = dict(os.environ, STUDYSEAT_EVIDENCE_DIR=str(EVIDENCE / "restart"))
    run([sys.executable, "scripts/process_smoke.py"], "process-smoke.txt", ALPHA, restart_env)
    with tempfile.TemporaryDirectory(prefix="phase4-ui-") as temporary:
        for script in (
            "browser.cjs",
            "reservations-browser.cjs",
            "account-switch.cjs",
            "initialization-browser.cjs",
            "reservation-list-browser.cjs",
            "phase3-browser.cjs",
        ):
            browser_case(Path(temporary), script)
    run([sys.executable, "scripts/phase4_load.py"], "performance.txt", ALPHA)
    result = {
        "result": "passed",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "baseline": "60f40e1089d6fd1da6125c19d897331019c9b775",
        "platform": platform.platform(),
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "packages": {
            name: importlib.metadata.version(name) for name in ("Flask", "pytest", "ruff")
        },
        "scope": "Alpha backend, syntax, restart, six browser suites, HTTP load; historical prototype excluded",
    }
    (EVIDENCE / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
