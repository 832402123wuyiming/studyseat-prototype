import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parent.parent
files = [
    "studyseat/attendance.py",
    "studyseat/admin.py",
    "studyseat/api.py",
    "studyseat/reservations.py",
    "studyseat/static/app.js",
    "studyseat/static/app.css",
    "studyseat/templates/index.html",
    "tests/test_attendance.py",
    "tests/test_admin.py",
    "tests/test_reservations.py",
    "docs/API-v1.md",
    "docs/RULES.md",
    "docs/PHASE3.md",
    "README.md",
]
suite = ET.parse(root / "evidence" / "phase3" / "pytest.xml").getroot()
if suite.tag == "testsuites":
    suite = suite.find("testsuite")
ui = json.loads((root / "evidence" / "phase3" / "ui-smoke.json").read_text(encoding="utf-8"))
report = {
    "phase": "alpha-03",
    "generated_at": "2026-11-25T18:32:00+08:00",
    "baseline": "07e6d64",
    "local_commits": 3,
    "environment": {
        "os": "Windows 11 10.0.26300",
        "python": "3.13.3",
        "sqlite": "3.49.1",
        "flask": "3.1.3",
        "pytest": "8.3.5",
        "ruff": "0.17.6",
        "node": "24.19.0",
        "playwright": "1.62.1",
        "browser": "Microsoft Edge 158.0.4370.33",
    },
    "tests": {
        "total": int(suite.get("tests")),
        "failures": int(suite.get("failures")),
        "errors": int(suite.get("errors")),
        "skipped": int(suite.get("skipped")),
    },
    "ui_smoke": {
        "checks": len(ui["checks"]),
        "passed": sum(1 for check in ui["checks"] if check["passed"]),
        "page_errors": len(ui["pageErrors"]),
    },
    "source_sha256": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
    },
}
(root / "evidence" / "phase3" / "verification.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)
print(json.dumps(report["tests"]), report["ui_smoke"], len(report["source_sha256"]))
