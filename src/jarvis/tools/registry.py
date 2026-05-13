"""Lightweight tool registry.

Each tool is a coroutine. We register them with a JSON Schema describing
the arguments so the LLM can call them with structured args.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from jarvis.utils.logging import get_logger

log = get_logger("tools.registry")

ToolFn = Callable[..., Awaitable[Any]]

_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    fn: ToolFn
    parameters: dict[str, Any]
    risk: str = "low"  # "low" | "med" | "high"
    requires_confirmation: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _infer_schema(fn: ToolFn) -> dict[str, Any]:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        hint = hints.get(name, str)
        json_type = _PY_TO_JSON.get(hint, "string")
        props[name] = {"type": json_type}
        if param.default is inspect._empty:  # noqa: SLF001
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def tool(
    *,
    name: str,
    description: str,
    risk: str = "low",
    requires_confirmation: bool = False,
    parameters: dict[str, Any] | None = None,
    tags: tuple[str, ...] = (),
) -> Callable[[ToolFn], ToolFn]:
    """Decorator: attach tool metadata to a coroutine function."""

    def wrap(fn: ToolFn) -> ToolFn:
        fn.__jarvis_tool__ = ToolSpec(  # type: ignore[attr-defined]
            name=name,
            description=description,
            fn=fn,
            parameters=parameters or _infer_schema(fn),
            risk=risk,
            requires_confirmation=requires_confirmation,
            tags=tags,
        )
        return fn

    return wrap


class ToolRegistry:
    """Holds the set of tools available to the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, fn: ToolFn) -> None:
        spec = getattr(fn, "__jarvis_tool__", None)
        if spec is None:
            raise ValueError(f"{fn!r} is not a @tool-decorated function")
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec

    def register_module(self, module: Any) -> None:
        for attr in vars(module).values():
            if callable(attr) and hasattr(attr, "__jarvis_tool__"):
                self.register(attr)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def openai_schema(self) -> list[dict[str, Any]]:
        return [spec.to_openai_schema() for spec in self._tools.values()]

    async def invoke(self, name: str, args: dict[str, Any]) -> Any:
        spec = self.get(name)
        log.debug("tool_invoke", tool=name, args=args)
        return await spec.fn(**args)


def build_default_registry() -> ToolRegistry:
    """Construct the registry with every bundled tool registered."""
    # Imports inside the function avoid circular imports at module load.
    from jarvis.tools import fs as fs_tools
    from jarvis.tools import memory as mem_tools
    from jarvis.tools import shell as shell_tools
    from jarvis.tools import web as web_tools
    from jarvis.tools import win as win_tools

    reg = ToolRegistry()
    for module in (shell_tools, fs_tools, web_tools, win_tools, mem_tools):
        reg.register_module(module)
    return reg
