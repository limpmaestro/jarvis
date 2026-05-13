"""Tiny perf timing helpers."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from jarvis.utils.logging import get_logger

log = get_logger("perf")


@contextmanager
def stopwatch(label: str) -> Iterator[dict[str, float]]:
    """Context manager that logs elapsed time on exit.

    Yields a dict that the caller can extend with extra fields; they are
    logged together with ``elapsed_ms`` on exit.
    """
    extra: dict[str, float] = {}
    start = time.perf_counter()
    try:
        yield extra
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        log.info("perf", label=label, elapsed_ms=round(elapsed_ms, 2), **extra)
