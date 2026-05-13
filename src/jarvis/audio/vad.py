"""Voice Activity Detection (silero-vad)."""

from __future__ import annotations

import numpy as np

from jarvis.utils.logging import get_logger

log = get_logger("audio.vad")


class SileroVAD:
    """Wraps silero-vad ONNX model. Lazy-loaded on first call."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5) -> None:
        self._sr = sample_rate
        self._threshold = threshold
        self._model = None
        self._utils = None

    def _ensure(self) -> None:
        if self._model is not None:
            return
        # silero-vad 5.x ships its own loader.
        from silero_vad import load_silero_vad  # type: ignore[import-untyped]

        self._model = load_silero_vad(onnx=True)

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Return True if the chunk is judged speech.

        ``chunk`` must be float32 PCM at 16 kHz, 512 samples (32 ms).
        """
        self._ensure()
        import torch  # type: ignore[import-untyped]

        if chunk.dtype != np.float32:
            chunk = chunk.astype(np.float32)
        tensor = torch.from_numpy(chunk)
        prob = float(self._model(tensor, self._sr).item())
        return prob >= self._threshold
