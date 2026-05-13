"""Thin async client around the Ollama HTTP API.

We do not depend on the ``ollama`` Python package at import time so the
module is importable even when Ollama isn't installed (useful for tests).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from jarvis.utils.logging import get_logger

log = get_logger("agent.llm")


@dataclass(slots=True)
class ChatChunk:
    """Streaming chat response chunk."""

    content: str
    done: bool
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None


class OllamaClient:
    """Async Ollama client supporting /api/chat streaming + tool calls."""

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=self._host, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def list_models(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/tags")
        r.raise_for_status()
        return r.json().get("models", [])

    async def has_model(self, name: str) -> bool:
        # Ollama returns names like "qwen2.5:14b-instruct-q4_K_M" but also
        # accepts the short tag (e.g. "jarvis"); we accept either form.
        try:
            models = await self.list_models()
        except httpx.HTTPError:
            return False
        return any(
            m.get("name", "").split(":")[0] == name.split(":", maxsplit=1)[0] for m in models
        )

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatChunk]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options

        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                msg = data.get("message") or {}
                yield ChatChunk(
                    content=msg.get("content", ""),
                    done=bool(data.get("done")),
                    tool_calls=msg.get("tool_calls") or None,
                    raw=data,
                )

    async def embed(self, model: str, text: str) -> list[float]:
        r = await self._client.post("/api/embeddings", json={"model": model, "prompt": text})
        r.raise_for_status()
        return r.json()["embedding"]

    async def ask_once(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Convenience: non-streaming single-turn chat → final text."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        out: list[str] = []
        async for chunk in self.chat(model, messages, options=options, stream=True):
            out.append(chunk.content)
            if chunk.done:
                break
        return "".join(out).strip()
