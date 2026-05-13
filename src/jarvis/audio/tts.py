"""Text-to-speech using Piper (low-latency, CPU, multilingual).

Piper exposes a tiny Python API; we wrap it so the rest of the codebase
only sees ``await tts.speak(text, language)``. The voice files are
downloaded by ``scripts/install.sh`` into ``assets/voices/``.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import numpy as np

from jarvis.config import Settings, get_settings
from jarvis.utils.logging import get_logger
from jarvis.utils.perf import stopwatch

log = get_logger("audio.tts")

VOICES_DIR = Path(__file__).resolve().parents[3] / "assets" / "voices"


class PiperEngine:
    """Wrap Piper voices and stream PCM to the default sound device."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._voices: dict[str, object] = {}

    def _voice_path(self, language: str) -> Path:
        name = self._settings.voice_for(language)
        return VOICES_DIR / f"{name}.onnx"

    def _load(self, language: str):
        from piper import PiperVoice  # type: ignore[import-untyped]

        key = "sv" if language.startswith("sv") else "en"
        if key in self._voices:
            return self._voices[key]
        path = self._voice_path(key)
        if not path.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {path}. Run scripts/install.sh to download it."
            )
        voice = PiperVoice.load(str(path), config_path=str(path) + ".json", use_cuda=False)
        self._voices[key] = voice
        return voice

    async def synthesize(self, text: str, language: str = "en") -> tuple[np.ndarray, int]:
        """Synthesize *text* → (int16 PCM, sample_rate)."""

        def _run() -> tuple[np.ndarray, int]:
            voice = self._load(language)
            with stopwatch("tts") as bag:
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wav:
                    voice.synthesize(text, wav)
                buf.seek(0)
                with wave.open(buf, "rb") as wav:
                    sr = wav.getframerate()
                    frames = wav.readframes(wav.getnframes())
                pcm = np.frombuffer(frames, dtype=np.int16)
            bag["chars"] = len(text)
            return pcm, sr

        return await asyncio.to_thread(_run)

    async def speak(self, text: str, language: str = "en") -> None:
        """Synthesize and play *text* through the default audio device."""
        if not text.strip():
            return
        pcm, sr = await self.synthesize(text, language=language)

        def _play() -> None:
            import sounddevice as sd

            sd.play(pcm, sr, blocking=True)
            sd.wait()

        await asyncio.to_thread(_play)

    async def to_file(self, text: str, path: str | Path, language: str = "en") -> Path:
        pcm, sr = await self.synthesize(text, language=language)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            with wave.open(str(out), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sr)
                wav.writeframes(pcm.tobytes())

        await asyncio.to_thread(_write)
        return out
