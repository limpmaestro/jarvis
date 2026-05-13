"""Tiny synchronous-feeling client to the core IPC socket."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


def socket_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "jarvis" / "core.sock"


class CoreClient:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or socket_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(str(self._path))

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        assert self._writer and self._reader, "call connect() first"
        self._writer.write(
            (json.dumps({"method": method, "params": params}) + "\n").encode("utf-8")
        )
        await self._writer.drain()
        line = await self._reader.readline()
        return json.loads(line)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        assert self._writer and self._reader, "call connect() first"
        self._writer.write(b'{"method":"subscribe","params":{}}\n')
        await self._writer.drain()
        # First reply: {"ok":true,"subscribed":true}
        await self._reader.readline()
        while True:
            line = await self._reader.readline()
            if not line:
                return
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
