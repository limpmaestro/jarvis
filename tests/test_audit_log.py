"""Audit log tests."""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.utils.audit import write


def test_audit_write(tmp_path, monkeypatch):
    from jarvis.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    get_settings.cache_clear()

    write("test_event", tool="shell.run", cmd="ls")
    log_file = tmp_path / "state" / "audit.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text().strip())
    assert line["event"] == "test_event"
    assert line["tool"] == "shell.run"
