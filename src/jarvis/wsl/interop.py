"""Helpers for the WSL ↔ Windows interop bridge."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def is_wsl() -> bool:
    """True iff we're running inside WSL (any version)."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def wslpath_to_windows(path: str | Path) -> str:
    """Convert a Linux path to a Windows path via ``wslpath -w``."""
    if not is_wsl():
        return str(path)
    return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()


def wslpath_from_windows(path: str) -> str:
    """Convert a Windows path to a Linux path via ``wslpath -u``."""
    if not is_wsl():
        return str(path)
    return subprocess.check_output(["wslpath", "-u", path], text=True).strip()


def windows_username() -> str | None:
    """Return the Windows-side username, or None if not in WSL."""
    if not is_wsl() or not shutil.which("cmd.exe"):
        return None
    try:
        out = (
            subprocess.check_output(
                ["cmd.exe", "/c", "echo", "%USERNAME%"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            .strip()
            .replace("\r", "")
        )
        return out or None
    except (subprocess.SubprocessError, OSError):
        return None


def windows_home() -> Path | None:
    user = windows_username()
    if not user:
        return None
    return Path(f"/mnt/c/Users/{user}")
