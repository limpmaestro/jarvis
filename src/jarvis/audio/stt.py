"""Speech-to-text using faster-whisper.

The model is loaded lazily on first transcription so importing this
module is cheap (and safe in test environments that have no GPU).
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvis.config import Settings, get_settings
from jarvis.utils.logging import get_logger
from jarvis.utils.perf import stopwatch

log = get_logger("audio.stt")


@dataclass(slots=True)
class Transcript:
    text: str
    language: str
    confidence: float
    duration_sec: float


class Transcriber:
    """Faster-whisper wrapper with auto device/compute-type selection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        # Lazy import keeps the rest of the package importable on machines
        # without CUDA / ctranslate2.
        from faster_whisper import WhisperModel

        device = self._settings.stt_device
        compute_type = self._settings.stt_compute_type
        if device == "auto":
            device, compute_type = self._auto_device()

        log.info(
            "stt_loading",
            model=self._settings.stt_model,
            device=device,
            compute_type=compute_type,
        )
        self._model = WhisperModel(
            self._settings.stt_model,
            device=device,
            compute_type=compute_type,
        )

    def _auto_device(self) -> tuple[str, str]:
        try:
            import torch  # type: ignore[import-untyped]

            if torch.cuda.is_available():
                return "cuda", "float16"
        except Exception:  # noqa: BLE001
            pass
        return "cpu", "int8"

    def _confidence(self, segments: list) -> float:
        if not segments:
            return 0.0
        # Whisper reports avg_logprob per segment; convert to a [0,1] score.
        avg = sum(getattr(s, "avg_logprob", 0.0) for s in segments) / len(segments)
        return float(math.exp(avg))

    async def transcribe_array(self, pcm: np.ndarray, sr: int = 16000) -> Transcript:
        """Transcribe a 1-D float32 PCM array at *sr* Hz."""
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        if sr != 16000:
            raise ValueError("STT expects 16 kHz mono input")

        def _run() -> Transcript:
            self._load_model()
            with stopwatch("stt") as bag:
                segments_iter, info = self._model.transcribe(
                    pcm,
                    language=None if self._settings.language == "auto" else self._settings.language,
                    vad_filter=False,
                    beam_size=1,
                )
                segments = list(segments_iter)
            bag["audio_sec"] = round(pcm.size / sr, 3)
            text = " ".join(s.text.strip() for s in segments).strip()
            return Transcript(
                text=text,
                language=info.language,
                confidence=self._confidence(segments),
                duration_sec=info.duration,
            )

        return await asyncio.to_thread(_run)

    async def transcribe_file(self, path: str | Path) -> Transcript:
        path = Path(path)
        import soundfile as sf

        def _read() -> tuple[np.ndarray, int]:
            data, sr = sf.read(str(path), dtype="float32", always_2d=False)
            if data.ndim == 2:
                data = data.mean(axis=1)
            return data, sr

        data, sr = await asyncio.to_thread(_read)
        if sr != 16000:
            # Cheap polyphase resample via scipy if available, else error.
            try:
                from math import gcd

                from scipy.signal import resample_poly  # type: ignore[import-untyped]

                g = gcd(sr, 16000)
                data = resample_poly(data, 16000 // g, sr // g).astype(np.float32)
                sr = 16000
            except ImportError:
                raise RuntimeError("Need 16 kHz audio or scipy installed for resampling")
        return await self.transcribe_array(data, sr=sr)
