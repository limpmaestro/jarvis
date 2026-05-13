"""Wake-word detection using openwakeword."""

from __future__ import annotations

import numpy as np

from jarvis.config import get_settings
from jarvis.utils.logging import get_logger

log = get_logger("audio.wake")


class WakeWordDetector:
    """Detects 'hey jarvis' (or another preset) in a streaming PCM buffer.

    Designed to consume 80 ms frames at 16 kHz mono (1280 samples each),
    matching openwakeword's native chunk size.
    """

    def __init__(self, name: str | None = None) -> None:
        self._name = name or get_settings().wake_word
        self._model = None

    def enabled(self) -> bool:
        return bool(self._name)

    def _ensure(self) -> None:
        if self._model is not None:
            return
        from openwakeword.model import Model  # type: ignore[import-untyped]

        log.info("wake_loading", model=self._name)
        self._model = Model(wakeword_models=[self._name])

    def predict(self, pcm: np.ndarray) -> dict[str, float]:
        """Return {wake_name: score} from one 80 ms frame of int16 PCM."""
        if not self.enabled():
            return {}
        self._ensure()
        if pcm.dtype != np.int16:
            pcm = (pcm * 32767.0).astype(np.int16)
        return dict(self._model.predict(pcm))

    def triggered(self, scores: dict[str, float], threshold: float = 0.5) -> bool:
        return any(v >= threshold for v in scores.values())
