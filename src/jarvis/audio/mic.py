"""Microphone capture + utterance segmentation.

Streams PCM from sounddevice, runs VAD to find speech boundaries, and
returns the recorded utterance as a numpy array.
"""

from __future__ import annotations

import asyncio
import queue
import time

import numpy as np

from jarvis.audio.vad import SileroVAD
from jarvis.utils.logging import get_logger

log = get_logger("audio.mic")

FRAME_SAMPLES = 512  # 32 ms at 16 kHz
SAMPLE_RATE = 16000


def _pcm_from_indata(indata: np.ndarray) -> np.ndarray:
    if indata.ndim == 2:
        indata = indata.mean(axis=1)
    return indata.astype(np.float32).reshape(-1)


async def record_utterance(
    max_seconds: float = 15.0,
    silence_end_ms: int = 700,
    pre_roll_ms: int = 200,
) -> np.ndarray:
    """Block until the user finishes speaking, then return the audio.

    Returns a 1-D float32 numpy array at 16 kHz.
    """
    import sounddevice as sd  # local import keeps unit tests headless

    vad = SileroVAD()
    q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, frames, time_info, status):  # noqa: D401
        if status:
            log.warning("sd_status", status=str(status))
        q.put(_pcm_from_indata(indata.copy()))

    pre_roll: list[np.ndarray] = []
    pre_roll_max_frames = max(1, int(pre_roll_ms / 32))

    speaking = False
    last_speech = 0.0
    start_time = time.time()
    captured: list[np.ndarray] = []

    loop = asyncio.get_running_loop()

    with sd.InputStream(
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SAMPLES,
        dtype="float32",
        callback=_cb,
    ):
        while True:
            if time.time() - start_time > max_seconds:
                break
            frame = await loop.run_in_executor(None, q.get)
            is_speech = vad.is_speech(frame)

            if not speaking:
                pre_roll.append(frame)
                if len(pre_roll) > pre_roll_max_frames:
                    pre_roll.pop(0)
                if is_speech:
                    speaking = True
                    captured.extend(pre_roll)
                    captured.append(frame)
                    last_speech = time.time()
            else:
                captured.append(frame)
                if is_speech:
                    last_speech = time.time()
                elif (time.time() - last_speech) * 1000.0 > silence_end_ms:
                    break

    if not captured:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(captured)
