"""ChromaDB-backed memory store with per-collection decay.

We use Ollama's embedding API (``nomic-embed-text`` by default) so the
vector space matches whatever Ollama serves.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from jarvis.agent.llm import OllamaClient
from jarvis.config import Settings, get_settings
from jarvis.utils.logging import get_logger

log = get_logger("memory.store")


@dataclass
class MemoryHit:
    id: str
    text: str
    score: float
    collection: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": round(self.score, 4),
            "collection": self.collection,
            "metadata": self.metadata,
        }


class MemoryStore:
    """Persistent vector store with episodic + semantic collections."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None
        self._episodic = None
        self._semantic = None
        self._llm: OllamaClient | None = None

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        # Lazy import — chromadb is heavy.
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        path = self._settings.state_path / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._episodic = self._client.get_or_create_collection("episodic")
        self._semantic = self._client.get_or_create_collection("semantic")

    def _ensure_llm(self) -> OllamaClient:
        if self._llm is None:
            self._llm = OllamaClient(host=self._settings.ollama_host)
        return self._llm

    async def _embed(self, text: str) -> list[float]:
        llm = self._ensure_llm()
        return await llm.embed(self._settings.embed_model, text)

    async def add_episodic(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        self._ensure_client()
        vec = await self._embed(text)
        mid = uuid.uuid4().hex
        meta = {"ts": time.time(), **(metadata or {})}
        self._episodic.add(ids=[mid], embeddings=[vec], documents=[text], metadatas=[meta])
        return mid

    async def add_semantic(self, text: str, tags: list[str] | None = None) -> str:
        self._ensure_client()
        vec = await self._embed(text)
        mid = uuid.uuid4().hex
        meta = {"ts": time.time(), "tags": ",".join(tags or [])}
        self._semantic.add(ids=[mid], embeddings=[vec], documents=[text], metadatas=[meta])
        return mid

    async def search(self, query: str, k: int | None = None) -> list[dict[str, Any]]:
        self._ensure_client()
        k = k or self._settings.memory_topk
        vec = await self._embed(query)
        out: list[MemoryHit] = []

        for collection_name, coll in (("episodic", self._episodic), ("semantic", self._semantic)):
            if coll.count() == 0:
                continue
            res = coll.query(query_embeddings=[vec], n_results=max(1, k))
            ids = res["ids"][0]
            docs = res["documents"][0]
            metas = res["metadatas"][0]
            dists = res["distances"][0]
            for mid, doc, meta, dist in zip(ids, docs, metas, dists, strict=True):
                # ChromaDB cosine distance: smaller = more similar.
                sim = 1.0 - float(dist)
                if collection_name == "episodic":
                    age_days = (time.time() - float(meta.get("ts", time.time()))) / 86400.0
                    decay = math.exp(-age_days / max(0.01, self._settings.memory_half_life_days))
                    sim *= decay
                out.append(
                    MemoryHit(
                        id=mid,
                        text=doc,
                        score=sim,
                        collection=collection_name,
                        metadata=dict(meta),
                    )
                )

        out.sort(key=lambda h: h.score, reverse=True)
        return [h.to_json() for h in out[:k]]

    async def retrieve_context(self, query: str, language: str) -> list[str]:
        """Return plain text snippets for injection into the system prompt."""
        hits = await self.search(query)
        return [h["text"] for h in hits]


_DEFAULT: MemoryStore | None = None


def default_store() -> MemoryStore:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = MemoryStore()
    return _DEFAULT
