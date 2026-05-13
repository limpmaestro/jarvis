"""Windows-side HMAC-signed automation bridge.

Run on the Windows host (not inside WSL). Listens on 127.0.0.1:48219
and accepts signed requests from the Jarvis core running in WSL. All
calls are dispatched to PyAutoGUI / pywinauto / mss.

Build as standalone exe:
    pip install pyinstaller
    pyinstaller --onefile bridge.py --name jarvis-bridge
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import pyautogui
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

app = FastAPI(title="Jarvis Windows Bridge")

# The HMAC key is loaded from %LOCALAPPDATA%\jarvis\bridge.key.
_BRIDGE_KEY: bytes = b""
_MAX_SKEW = 5  # seconds


def _load_key() -> bytes:
    kp = Path(os.environ.get("LOCALAPPDATA", "")) / "jarvis" / "bridge.key"
    if not kp.exists():
        raise RuntimeError(f"bridge.key not found at {kp}. Run install.ps1.")
    return kp.read_bytes().strip()


def _verify(request: Request, body: bytes) -> None:
    """Verify HMAC signature. Raises 403 on failure."""
    nonce = request.headers.get("X-Jarvis-Nonce", "")
    ts = request.headers.get("X-Jarvis-Ts", "")
    sig = request.headers.get("X-Jarvis-Sig", "")
    if not nonce or not ts or not sig:
        raise HTTPException(403, "missing auth headers")
    if abs(time.time() - int(ts)) > _MAX_SKEW:
        raise HTTPException(403, "timestamp skew too large")
    msg = b"\n".join(
        [b"POST", request.url.path.encode(), body, nonce.encode(), ts.encode()]
    )
    expected = hmac.new(_BRIDGE_KEY, msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(403, "invalid signature")


# ─── Routes ───

class ClickReq(BaseModel):
    x: int
    y: int
    button: str = "left"
    clicks: int = 1

@app.post("/click")
async def click(req: ClickReq, raw: Request) -> dict[str, Any]:
    _verify(raw, await raw.body())
    pyautogui.click(req.x, req.y, clicks=req.clicks, button=req.button)
    return {"ok": True}


class TypeReq(BaseModel):
    text: str
    interval_ms: int = 15

@app.post("/type")
async def type_text(req: TypeReq, raw: Request) -> dict[str, Any]:
    _verify(raw, await raw.body())
    pyautogui.typewrite(req.text, interval=req.interval_ms / 1000.0)
    return {"ok": True}


class FocusReq(BaseModel):
    title_regex: str

@app.post("/focus")
async def focus(req: FocusReq, raw: Request) -> dict[str, Any]:
    _verify(raw, await raw.body())
    try:
        import pygetwindow as gw  # type: ignore[import-untyped]
    except ImportError:
        raise HTTPException(500, "pygetwindow not installed")
    pattern = re.compile(req.title_regex, re.IGNORECASE)
    wins = [w for w in gw.getAllWindows() if pattern.search(w.title)]
    if not wins:
        return {"ok": False, "error": f"no window matching /{req.title_regex}/"}
    wins[0].activate()
    return {"ok": True, "title": wins[0].title}


@app.post("/screenshot")
async def screenshot(raw: Request) -> dict[str, Any]:
    _verify(raw, await raw.body())
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    out = Path(os.environ.get("LOCALAPPDATA", ".")) / "jarvis" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    fname = out / f"screenshot_{int(time.time())}.png"
    img.save(str(fname))
    return {"ok": True, "path": str(fname)}


@app.post("/windows")
async def list_windows(raw: Request) -> dict[str, Any]:
    _verify(raw, await raw.body())
    try:
        import pygetwindow as gw
    except ImportError:
        raise HTTPException(500, "pygetwindow not installed")
    wins = [
        {"title": w.title, "left": w.left, "top": w.top, "width": w.width, "height": w.height}
        for w in gw.getAllWindows()
        if w.title.strip()
    ]
    return {"ok": True, "windows": wins}


def main() -> None:
    global _BRIDGE_KEY
    _BRIDGE_KEY = _load_key()
    uvicorn.run(app, host="127.0.0.1", port=48219, log_level="info")


if __name__ == "__main__":
    main()
