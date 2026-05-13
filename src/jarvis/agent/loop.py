"""The Jarvis agent loop.

A single explicit state machine. We deliberately avoid LangChain-style
frameworks: their abstractions hide the very latency we are trying to
optimize, and our flow is small enough to read top-to-bottom.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.agent.llm import OllamaClient
from jarvis.config import Settings, get_settings
from jarvis.tools.registry import ToolRegistry
from jarvis.utils.audit import write as audit
from jarvis.utils.logging import get_logger

log = get_logger("agent.loop")

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@dataclass
class Turn:
    """One user→assistant turn with all intermediate state."""

    user_text: str
    language: str = "en"
    assistant_text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


SpeakChunk = Callable[[str], Awaitable[None]]


class AgentLoop:
    """Drive an Ollama model through tool-using multi-turn conversations.

    The loop maintains a short rolling context window (the last
    ``history_max`` user/assistant pairs) plus the retrieved memory chunks
    that the caller injects per-turn.
    """

    def __init__(
        self,
        *,
        llm: OllamaClient,
        tools: ToolRegistry,
        memory_retriever: Callable[[str, str], Awaitable[list[str]]] | None = None,
        settings: Settings | None = None,
        history_max: int = 8,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._retrieve = memory_retriever
        self._settings = settings or get_settings()
        self._history_max = history_max
        self._history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # System prompt
    # ------------------------------------------------------------------ #

    def _system_prompt(self, language: str) -> str:
        fname = "system.sv.txt" if language.startswith("sv") else "system.en.txt"
        path = PROMPTS_DIR / fname
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return (
            "You are Jarvis, a proactive, witty, and highly capable local "
            "system administrator AI. Be concise. Use tools when needed."
        )

    # ------------------------------------------------------------------ #
    # Memory
    # ------------------------------------------------------------------ #

    async def _memory_context(self, query: str, language: str) -> str:
        if not self._retrieve:
            return ""
        try:
            chunks = await self._retrieve(query, language)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory_retrieve_failed", error=str(exc))
            return ""
        if not chunks:
            return ""
        return "Relevant memories:\n" + "\n".join(f"- {c}" for c in chunks)

    # ------------------------------------------------------------------ #
    # Tool dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch_tool(self, call: dict[str, Any]) -> dict[str, Any]:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments", {})
        args: dict[str, Any]
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
        else:
            args = dict(raw_args)

        audit("tool_call", tool=name, args=args)
        try:
            result = await self._tools.invoke(name, args)
            audit("tool_result", tool=name, ok=True)
            return {"name": name, "ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            audit("tool_result", tool=name, ok=False, error=str(exc))
            log.warning("tool_error", tool=name, error=str(exc))
            return {"name": name, "ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ #
    # Main entrypoint
    # ------------------------------------------------------------------ #

    async def run_turn(
        self,
        user_text: str,
        *,
        language: str = "en",
        on_sentence: SpeakChunk | None = None,
        max_tool_rounds: int = 4,
    ) -> Turn:
        """Drive one user→assistant turn.

        If ``on_sentence`` is provided it is awaited for every completed
        sentence in the assistant's reply, so a TTS engine can speak
        sentence-by-sentence while the LLM is still generating.
        """
        turn = Turn(user_text=user_text, language=language)
        sys_prompt = self._system_prompt(language)
        mem = await self._memory_context(user_text, language)
        if mem:
            sys_prompt = f"{sys_prompt}\n\n{mem}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}]
        messages.extend(self._history[-self._history_max * 2 :])
        messages.append({"role": "user", "content": user_text})

        tool_specs = self._tools.openai_schema()
        ollama_options = {
            "temperature": self._settings.temperature,
            "num_ctx": self._settings.num_ctx,
        }

        for round_no in range(max_tool_rounds + 1):
            assistant_buf: list[str] = []
            pending_tool_calls: list[dict[str, Any]] = []
            sent_buf = ""

            async for chunk in self._llm.chat(
                model=self._settings.model,
                messages=messages,
                tools=tool_specs,
                options=ollama_options,
                stream=True,
            ):
                if chunk.tool_calls:
                    pending_tool_calls.extend(chunk.tool_calls)
                if chunk.content:
                    assistant_buf.append(chunk.content)
                    sent_buf += chunk.content
                    if on_sentence:
                        sentences, sent_buf = _split_sentences(sent_buf)
                        for sentence in sentences:
                            await on_sentence(sentence)
                if chunk.done:
                    break

            # Flush any trailing partial-sentence text.
            if on_sentence and sent_buf.strip():
                await on_sentence(sent_buf.strip())
                sent_buf = ""

            text = "".join(assistant_buf).strip()
            messages.append(
                {"role": "assistant", "content": text, "tool_calls": pending_tool_calls}
            )

            if not pending_tool_calls or round_no == max_tool_rounds:
                turn.assistant_text = text
                break

            turn.tool_calls.extend(pending_tool_calls)
            for call in pending_tool_calls:
                result = await self._dispatch_tool(call)
                turn.tool_results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "name": result["name"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # Update rolling history.
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": turn.assistant_text})
        if len(self._history) > self._history_max * 2:
            self._history = self._history[-self._history_max * 2 :]

        return turn


# ---------------------------------------------------------------------- #
# Sentence splitting (streaming)
# ---------------------------------------------------------------------- #

_SENTENCE_END = (".", "!", "?", "…", "。", "！", "？", "\n")


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """Split *buf* into completed sentences and a trailing remainder.

    Returns ``([sentence, ...], remainder)``. The remainder is whatever
    came after the last sentence-ending punctuation; it should be carried
    into the next call.
    """
    sentences: list[str] = []
    start = 0
    for i, ch in enumerate(buf):
        if ch in _SENTENCE_END:
            chunk = buf[start : i + 1].strip()
            if chunk:
                sentences.append(chunk)
            start = i + 1
    remainder = buf[start:]
    return sentences, remainder
