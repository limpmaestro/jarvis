"""WSL interop tests (safe to run outside WSL)."""

from __future__ import annotations

from jarvis.wsl.interop import is_wsl


def test_is_wsl_returns_bool():
    # Just verify the function runs without error; result depends on env.
    assert isinstance(is_wsl(), bool)
