"""Memory tools exposed to the LLM."""

from __future__ import annotations

from typing import Any

from jarvis.memory.store import default_store
from jarvis.tools.registry import tool


@tool(
    name="memory.save",
    description=(
        "Persist a fact, preference, or note in long-term semantic memory. "
        "Use this whenever the user shares something that should be remembered "
        "across sessions (names, project details, preferences)."
    ),
    risk="low",
)
async def memory_save(text: str, tags: str = "") -> dict[str, Any]:
    store = default_store()
    mid = await store.add_semantic(
        text=text, tags=[t.strip() for t in tags.split(",") if t.strip()]
    )
    return {"ok": True, "id": mid}


@tool(
    name="memory.query",
    description="Vector-search long-term memory and return the top K matching snippets.",
    risk="low",
)
async def memory_query(query: str, k: int = 6) -> dict[str, Any]:
    store = default_store()
    hits = await store.search(query=query, k=k)
    return {"ok": True, "query": query, "results": hits}
