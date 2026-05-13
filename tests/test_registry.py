"""Tool registry tests."""

from __future__ import annotations

import pytest

from jarvis.tools.registry import ToolRegistry, tool


@tool(name="test.echo", description="Echo back args.", risk="low")
async def echo_tool(message: str) -> dict:
    return {"echo": message}


def test_register_and_invoke():
    reg = ToolRegistry()
    reg.register(echo_tool)
    assert "test.echo" in reg.names()
    schema = reg.openai_schema()
    assert len(schema) == 1
    assert schema[0]["function"]["name"] == "test.echo"


@pytest.mark.asyncio
async def test_invoke():
    reg = ToolRegistry()
    reg.register(echo_tool)
    result = await reg.invoke("test.echo", {"message": "hi"})
    assert result == {"echo": "hi"}


def test_unknown_tool():
    reg = ToolRegistry()
    with pytest.raises(KeyError, match="unknown tool"):
        reg.get("nonexistent")
