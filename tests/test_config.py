"""Config / settings tests."""

from __future__ import annotations

from pathlib import Path

from jarvis.config import get_settings


def test_defaults():
    s = get_settings()
    assert s.log_level == "DEBUG"  # overridden by conftest
    assert s.model == "jarvis"
    assert s.temperature == 0.4
    assert s.bridge_port == 48219


def test_path_allowed(tmp_path):
    s = get_settings()
    # tmp_path is unlikely to be inside allowed_roots, so this should be False.
    assert s.path_is_allowed("/root/super-secret") is False


def test_voice_for():
    s = get_settings()
    assert "sv" in s.voice_for("sv")
    assert "en" in s.voice_for("en")
    assert "en" in s.voice_for("de")  # fallback
