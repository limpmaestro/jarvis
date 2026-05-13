"""Typed settings loaded from environment + .env.

Settings are exposed through ``get_settings()`` which caches a single
instance per process. Tests can call ``get_settings.cache_clear()`` to
reset between cases.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _expand(path: str | Path) -> Path:
    return Path(str(path)).expanduser().resolve()


class Settings(BaseSettings):
    """Top-level Jarvis settings.

    Order of precedence (highest first):
        1. Real environment variables
        2. Values in ``.env`` in the project root
        3. Defaults below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="JARVIS_LOG_LEVEL"
    )
    language: Literal["auto", "sv", "en"] = Field(default="auto", alias="JARVIS_LANGUAGE")
    state_dir: Path = Field(default=Path("~/.jarvis/state"), alias="JARVIS_STATE_DIR")

    # --- Ollama ---
    ollama_host: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_HOST")
    model: str = Field(default="jarvis", alias="JARVIS_MODEL")
    embed_model: str = Field(default="nomic-embed-text:v1.5", alias="JARVIS_EMBED_MODEL")
    num_ctx: int = Field(default=8192, alias="JARVIS_NUM_CTX")
    temperature: float = Field(default=0.4, alias="JARVIS_TEMPERATURE")

    # --- STT ---
    stt_model: str = Field(default="large-v3-turbo", alias="JARVIS_STT_MODEL")
    stt_device: Literal["cuda", "cpu", "auto"] = Field(default="auto", alias="JARVIS_STT_DEVICE")
    stt_compute_type: str = Field(default="float16", alias="JARVIS_STT_COMPUTE_TYPE")
    wake_word: str = Field(default="hey_jarvis", alias="JARVIS_WAKE_WORD")
    ptt_hotkey: str = Field(default="F8", alias="JARVIS_PTT_HOTKEY")

    # --- TTS ---
    tts_voice_sv: str = Field(default="sv_SE-nst-medium", alias="JARVIS_TTS_VOICE_SV")
    tts_voice_en: str = Field(default="en_US-amy-medium", alias="JARVIS_TTS_VOICE_EN")
    tts_rate: float = Field(default=1.0, alias="JARVIS_TTS_RATE")

    # --- Tools ---
    allowed_roots_raw: str = Field(
        default="~/Documents,~/Downloads,~/Desktop,/mnt/c/Users",
        alias="JARVIS_ALLOWED_ROOTS",
    )
    tool_timeout_sec: int = Field(default=30, alias="JARVIS_TOOL_TIMEOUT_SEC")
    unattended: bool = Field(default=False, alias="JARVIS_UNATTENDED")

    # --- Windows bridge ---
    bridge_host: str = Field(default="127.0.0.1", alias="JARVIS_BRIDGE_HOST")
    bridge_port: int = Field(default=48219, alias="JARVIS_BRIDGE_PORT")
    bridge_hmac: str = Field(default="", alias="JARVIS_BRIDGE_HMAC")

    # --- HUD ---
    hud_enabled: bool = Field(default=True, alias="JARVIS_HUD_ENABLED")
    hud_position: str = Field(default="top-right", alias="JARVIS_HUD_POSITION")

    # --- Memory ---
    memory_topk: int = Field(default=6, alias="JARVIS_MEMORY_TOPK")
    memory_half_life_days: float = Field(default=14.0, alias="JARVIS_MEMORY_HALF_LIFE_DAYS")

    # --- Computed ---
    @property
    def state_path(self) -> Path:
        path = _expand(self.state_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        roots = [r.strip() for r in self.allowed_roots_raw.split(",") if r.strip()]
        return tuple(_expand(r) for r in roots)

    @field_validator("temperature")
    @classmethod
    def _check_temp(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be in [0.0, 2.0]")
        return v

    def path_is_allowed(self, p: Path | str) -> bool:
        """Return True iff *p* resolves inside one of ``allowed_roots``."""
        candidate = _expand(p)
        for root in self.allowed_roots:
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def voice_for(self, language: str) -> str:
        return self.tts_voice_sv if language.startswith("sv") else self.tts_voice_en

    def describe(self) -> Sequence[tuple[str, str]]:
        """Human-readable description of the loaded config (no secrets)."""
        return (
            ("log_level", self.log_level),
            ("language", self.language),
            ("state_dir", str(self.state_path)),
            ("ollama_host", self.ollama_host),
            ("model", self.model),
            ("embed_model", self.embed_model),
            ("stt_model", self.stt_model),
            ("stt_device", self.stt_device),
            ("tts_voice_sv", self.tts_voice_sv),
            ("tts_voice_en", self.tts_voice_en),
            ("allowed_roots", ", ".join(str(r) for r in self.allowed_roots)),
            ("bridge", f"{self.bridge_host}:{self.bridge_port}"),
            ("hud_enabled", str(self.hud_enabled)),
            ("memory_topk", str(self.memory_topk)),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
