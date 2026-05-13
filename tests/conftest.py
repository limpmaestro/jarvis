"""Shared test fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _env_overrides(tmp_path, monkeypatch):
    """Ensure tests never touch real state or Ollama."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:19999")
    # Clear any cached settings.
    from jarvis.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
