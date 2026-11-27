"""Verify committed WAL data survives backup and existing files stay intact."""

import os
import sqlite3
import sys

import pytest

from scripts import verify_phase2
from scripts.backup_db import backup


def test_backup_restores_committed_wal_data(tmp_path):
    source, target = tmp_path / "live.db", tmp_path / "restore.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE records(id PRIMARY KEY, value)")
        connection.execute("INSERT INTO records VALUES(1, 'committed')")
        connection.commit()
        backup(source, target)
    with sqlite3.connect(target) as restored:
        assert restored.execute("SELECT value FROM records").fetchone()[0] == "committed"
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_refuses_overwrite(tmp_path):
    source, target = tmp_path / "live.db", tmp_path / "existing.db"
    source.touch()
    target.write_bytes(b"keep existing backup")
    with pytest.raises(FileExistsError):
        backup(source, target)
    assert target.read_bytes() == b"keep existing backup"


def test_backup_missing_source_creates_no_database(tmp_path):
    source, target = tmp_path / "missing.db", tmp_path / "copy.db"
    with pytest.raises(FileNotFoundError):
        backup(source, target)
    assert not source.exists() and not target.exists()


def test_verifier_captures_utf8_child_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_phase2, "EVIDENCE", tmp_path)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    verify_phase2.run(
        [sys.executable, "-c", "print('中文验证日志')"],
        "output.txt",
        cwd=tmp_path,
        env=environment,
    )
    assert (tmp_path / "output.txt").read_text(encoding="utf-8").strip() == "中文验证日志"
