"""Shell execution tool, with a denylist and per-call timeout."""

from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any

from jarvis.config import get_settings
from jarvis.tools.registry import tool
from jarvis.utils.logging import get_logger

log = get_logger("tools.shell")

# Patterns we refuse outright. Order matters; check before any allow list.
_DENY = [
    re.compile(r"\brm\s+-rf?\s+/(?!\w)"),  # rm -rf / (root)
    re.compile(r"\bmkfs(\.\w+)?\b"),
    re.compile(r"\bdd\s+if=.*\bof=/dev/"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"),
    re.compile(r"\bchmod\s+-R\s+777\s+/\b"),
    re.compile(r">\s*/dev/sd[a-z]"),
]


def _denied(cmd: str) -> str | None:
    for pat in _DENY:
        if pat.search(cmd):
            return pat.pattern
    return None


@tool(
    name="shell.run",
    description=(
        "Run a shell command inside WSL and return its stdout, stderr, and exit "
        "code. Refuses obviously destructive commands. Use this for read-only "
        "system inspection by default; ask the user before running anything "
        "that mutates state."
    ),
    risk="high",
    requires_confirmation=False,  # confirmation happens at agent prompt level
)
async def shell_run(
    command: str,
    cwd: str = "",
    timeout_sec: int = 30,
) -> dict[str, Any]:
    """Execute *command* with /bin/bash -lc."""
    deny = _denied(command)
    if deny:
        return {"ok": False, "error": f"refused: matches denylist /{deny}/"}

    settings = get_settings()
    timeout = min(max(1, timeout_sec), max(1, settings.tool_timeout_sec * 4))

    args = ["/bin/bash", "-lc", command]
    log.info("shell_run", command=command, cwd=cwd or None)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or None,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"timeout after {timeout}s", "command": command}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "command": command,
        }
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"shell not found: {exc}", "command": command}


@tool(
    name="shell.which",
    description="Locate an executable on $PATH; returns the absolute path or null.",
    risk="low",
)
async def shell_which(name: str) -> dict[str, Any]:
    # Cheap convenience wrapper; avoid spawning a full shell.
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/which",
        shlex.quote(name),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    path = out.decode().strip() or None
    return {"ok": path is not None, "name": name, "path": path}
