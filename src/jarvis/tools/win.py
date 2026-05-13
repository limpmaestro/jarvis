"""Windows automation tools — proxied through the Windows bridge."""

from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256
from typing import Any

import httpx

from jarvis.config import get_settings
from jarvis.tools.registry import tool
from jarvis.utils.logging import get_logger

log = get_logger("tools.win")


def _sign(method: str, path: str, body: bytes, nonce: str, ts: str) -> str:
    settings = get_settings()
    key = settings.bridge_hmac.encode("utf-8")
    msg = b"\n".join([method.encode(), path.encode(), body, nonce.encode(), ts.encode()])
    return hmac.new(key, msg, sha256).hexdigest()


async def _call(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.bridge_hmac:
        return {"ok": False, "error": "bridge HMAC not configured; run install.sh"}

    nonce = secrets.token_hex(8)
    ts = str(int(time.time()))
    body = httpx.Request("POST", "http://x", json=payload).content
    sig = _sign("POST", path, body, nonce, ts)

    url = f"http://{settings.bridge_host}:{settings.bridge_port}{path}"
    headers = {
        "X-Jarvis-Nonce": nonce,
        "X-Jarvis-Ts": ts,
        "X-Jarvis-Sig": sig,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, content=body, headers=headers)
        if r.status_code != 200:
            return {"ok": False, "error": f"bridge {r.status_code}: {r.text[:300]}"}
        return r.json()
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"bridge unreachable: {exc}"}


@tool(
    name="win.click",
    description=(
        "Move the mouse to (x, y) on the primary Windows monitor and click. "
        "Coordinates are absolute physical pixels."
    ),
    risk="high",
)
async def win_click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    return await _call("/click", {"x": x, "y": y, "button": button, "clicks": clicks})


@tool(
    name="win.type",
    description="Type a UTF-8 string into the currently focused Windows window.",
    risk="high",
)
async def win_type(text: str, interval_ms: int = 15) -> dict[str, Any]:
    return await _call("/type", {"text": text, "interval_ms": interval_ms})


@tool(
    name="win.focus",
    description=(
        "Focus a Windows window whose title matches the given regex. "
        "Returns the focused window title."
    ),
    risk="med",
)
async def win_focus(title_regex: str) -> dict[str, Any]:
    return await _call("/focus", {"title_regex": title_regex})


@tool(
    name="win.screenshot",
    description=(
        "Capture the Windows primary monitor and save it under "
        "$JARVIS_STATE_DIR/screenshots/. Returns the path."
    ),
    risk="low",
)
async def win_screenshot() -> dict[str, Any]:
    return await _call("/screenshot", {})


@tool(
    name="win.windows",
    description="List visible top-level Windows windows.",
    risk="low",
)
async def win_windows() -> dict[str, Any]:
    return await _call("/windows", {})
