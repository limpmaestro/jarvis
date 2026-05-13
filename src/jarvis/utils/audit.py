"""Append-only audit log for tool calls.

One line of JSON per call. Stored at ``$JARVIS_STATE_DIR/audit.jsonl``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from jarvis.config import get_settings


def _path() -> Path:
    return get_settings().state_path / "audit.jsonl"


def write(event: str, **fields: Any) -> None:
    """Append one JSON line to the audit log. Best-effort; never raises."""
    record = {"ts": time.time(), "event": event, **fields}
    try:
        with _path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # We never let logging break the agent.
        pass
