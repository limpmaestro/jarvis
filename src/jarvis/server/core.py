"""The Jarvis core service.

Runs the agent loop, exposes a minimal newline-delimited-JSON RPC over
a unix socket, and broadcasts status events to subscribers (the HUD).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from jarvis.agent import AgentLoop, OllamaClient
from jarvis.config import get_settings
from jarvis.memory import default_store
from jarvis.tools import build_default_registry
from jarvis.utils.logging import configure_logging, get_logger

log = get_logger("server.core")


def _socket_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    p = runtime / "jarvis"
    p.mkdir(parents=True, exist_ok=True)
    return p / "core.sock"


class JarvisCore:
    """Owns the agent loop and broadcasts status events."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm = OllamaClient(host=self._settings.ollama_host)
        self._tools = build_default_registry()
        self._memory = default_store()
        self._agent = AgentLoop(
            llm=self._llm,
            tools=self._tools,
            memory_retriever=self._memory.retrieve_context,
            settings=self._settings,
        )
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._state = "idle"

    # ----------------------- status broadcast ----------------------- #

    async def _broadcast(self, **event: Any) -> None:
        for q in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                q.put_nowait(event)

    async def _set_state(self, state: str) -> None:
        self._state = state
        await self._broadcast(type="state", state=state)

    # ----------------------- rpc handlers ----------------------- #

    async def _handle_ask(self, params: dict[str, Any]) -> dict[str, Any]:
        text = str(params.get("text", "")).strip()
        language = str(params.get("language", "en"))
        if not text:
            return {"ok": False, "error": "empty text"}

        await self._set_state("thinking")
        try:
            turn = await self._agent.run_turn(text, language=language)
        finally:
            await self._set_state("idle")

        # Save episodic memory (best-effort).
        try:
            summary = f"User: {text}\nAssistant: {turn.assistant_text}"
            await self._memory.add_episodic(summary, metadata={"language": language})
        except Exception as exc:  # noqa: BLE001
            log.warning("memory_save_failed", error=str(exc))

        return {
            "ok": True,
            "text": turn.assistant_text,
            "tool_calls": turn.tool_calls,
            "language": language,
        }

    async def _handle_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "state": self._state,
            "model": self._settings.model,
            "tools": self._tools.names(),
        }

    async def _handle_subscribe(self, _params: dict[str, Any]) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.add(q)
        return q

    # ----------------------- transport ----------------------- #

    async def _serve_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        log.info("client_connected", peer=peer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    writer.write(b'{"ok":false,"error":"invalid json"}\n')
                    await writer.drain()
                    continue
                method = msg.get("method")
                params = msg.get("params") or {}

                if method == "ask":
                    res = await self._handle_ask(params)
                    writer.write((json.dumps(res) + "\n").encode("utf-8"))
                    await writer.drain()
                elif method == "status":
                    res = await self._handle_status(params)
                    writer.write((json.dumps(res) + "\n").encode("utf-8"))
                    await writer.drain()
                elif method == "subscribe":
                    q = await self._handle_subscribe(params)
                    writer.write(b'{"ok":true,"subscribed":true}\n')
                    await writer.drain()
                    try:
                        while True:
                            event = await q.get()
                            writer.write((json.dumps(event) + "\n").encode("utf-8"))
                            await writer.drain()
                    finally:
                        self._subscribers.discard(q)
                else:
                    writer.write(b'{"ok":false,"error":"unknown method"}\n')
                    await writer.drain()
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            log.info("client_disconnected", peer=peer)

    async def serve(self) -> None:
        configure_logging(self._settings.log_level)
        path = _socket_path()
        if path.exists():
            path.unlink()
        server = await asyncio.start_unix_server(self._serve_client, path=str(path))
        os.chmod(path, 0o600)
        log.info(
            "core_listening",
            path=str(path),
            model=self._settings.model,
            tools=self._tools.names(),
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

        async with server:
            await stop.wait()

        log.info("core_shutting_down")
        await self._llm.aclose()


def main() -> None:
    asyncio.run(JarvisCore().serve())


if __name__ == "__main__":
    sys.exit(main())
