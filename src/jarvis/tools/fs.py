"""Filesystem tools, sandboxed to ``JARVIS_ALLOWED_ROOTS``."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from jarvis.config import get_settings
from jarvis.tools.registry import tool
from jarvis.utils.logging import get_logger

log = get_logger("tools.fs")


def _check(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not get_settings().path_is_allowed(p):
        raise PermissionError(f"path outside allowed roots: {p}")
    return p


@tool(
    name="fs.read",
    description="Read a UTF-8 text file. Path must be inside allowed roots.",
    risk="low",
)
async def fs_read(path: str, max_bytes: int = 65536) -> dict[str, Any]:
    p = _check(path)
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {p}"}
    data = p.read_bytes()[: max(1, max_bytes)]
    return {
        "ok": True,
        "path": str(p),
        "size": p.stat().st_size,
        "truncated": p.stat().st_size > len(data),
        "content": data.decode("utf-8", errors="replace"),
    }


@tool(
    name="fs.write",
    description=(
        "Write a UTF-8 text file. Path must be inside allowed roots. "
        "Refuses to overwrite an existing file unless overwrite=true."
    ),
    risk="med",
)
async def fs_write(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    p = _check(path)
    if p.exists() and not overwrite:
        return {"ok": False, "error": f"file exists; pass overwrite=true to replace: {p}"}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "size": p.stat().st_size}


@tool(
    name="fs.list",
    description="List entries of a directory. Path must be inside allowed roots.",
    risk="low",
)
async def fs_list(path: str) -> dict[str, Any]:
    p = _check(path)
    if not p.is_dir():
        return {"ok": False, "error": f"not a directory: {p}"}
    entries = []
    for child in sorted(p.iterdir()):
        try:
            st = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            )
        except OSError:
            continue
    return {"ok": True, "path": str(p), "entries": entries}


@tool(
    name="fs.search",
    description=(
        "Search file contents using ripgrep across allowed roots. " "Returns at most 50 matches."
    ),
    risk="low",
)
async def fs_search(pattern: str, root: str = "", max_matches: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if root:
        roots = [_check(root)]
    else:
        roots = list(settings.allowed_roots)

    if not roots:
        return {"ok": False, "error": "no allowed roots configured"}

    args = [
        "rg",
        "--json",
        "--max-count",
        str(max_matches),
        "--no-heading",
        "--with-filename",
        "--line-number",
        "--",
        pattern,
        *[str(r) for r in roots],
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    if proc.returncode not in (0, 1):
        return {"ok": False, "error": stderr_b.decode("utf-8", errors="replace")[:500]}
    # ripgrep --json emits one JSON object per line; we just return the
    # raw newline-delimited output so the LLM can scan it.
    return {
        "ok": True,
        "pattern": pattern,
        "matches": stdout_b.decode("utf-8", errors="replace"),
    }
