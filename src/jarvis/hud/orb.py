"""PyQt6 floating HUD orb.

The orb is a frameless, always-on-top, transparent window with a single
QWidget that paints a circular gradient. Its colour and pulse rate map
to the core state stream.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from pathlib import Path

from jarvis.utils.logging import configure_logging, get_logger

log = get_logger("hud.orb")

STATE_COLORS = {
    "idle": (90, 90, 110),
    "listening": (60, 160, 220),
    "thinking": (190, 140, 40),
    "speaking": (60, 200, 110),
    "error": (210, 60, 60),
}


def _runtime_socket() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "jarvis" / "core.sock"


def main() -> int:
    configure_logging("INFO")
    try:
        from PyQt6.QtCore import QPointF, Qt, QTimer
        from PyQt6.QtGui import QColor, QPainter, QRadialGradient
        from PyQt6.QtWidgets import QApplication, QWidget
    except ImportError as exc:
        print(f"PyQt6 is required for the HUD: {exc}", file=sys.stderr)
        return 2

    class Orb(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.resize(96, 96)
            self._state = "idle"
            self._phase = 0.0
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(33)  # ~30 fps
            self._drag_pos: QPointF | None = None
            self._move_to_top_right()

        def _move_to_top_right(self) -> None:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 24, screen.top() + 48)

        def set_state(self, state: str) -> None:
            self._state = state if state in STATE_COLORS else "idle"
            self.update()

        def _tick(self) -> None:
            self._phase = (self._phase + 0.08) % (2 * math.pi)
            self.update()

        def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt API)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r, g, b = STATE_COLORS[self._state]
            pulse = 0.5 + 0.5 * math.sin(self._phase)
            center = QPointF(self.width() / 2, self.height() / 2)
            gradient = QRadialGradient(center, self.width() * 0.5 * (0.8 + 0.2 * pulse))
            gradient.setColorAt(0.0, QColor(r, g, b, 230))
            gradient.setColorAt(0.6, QColor(r, g, b, 90))
            gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(self.rect())

        def mousePressEvent(self, ev) -> None:  # noqa: N802
            if ev.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = ev.globalPosition() - QPointF(self.frameGeometry().topLeft())

        def mouseMoveEvent(self, ev) -> None:  # noqa: N802
            if self._drag_pos is not None and (ev.buttons() & Qt.MouseButton.LeftButton):
                self.move((ev.globalPosition() - self._drag_pos).toPoint())

        def mouseReleaseEvent(self, _ev) -> None:  # noqa: N802
            self._drag_pos = None

    app = QApplication(sys.argv)
    orb = Orb()
    orb.show()

    async def _subscribe() -> None:
        sock = _runtime_socket()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock))
        except FileNotFoundError:
            log.warning("core_not_running", path=str(sock))
            return
        writer.write(b'{"method":"subscribe","params":{}}\n')
        await writer.drain()
        await reader.readline()  # subscribed ack
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "state":
                orb.set_state(str(msg.get("state", "idle")))

    # Drive the asyncio loop alongside Qt via a 50 ms timer.
    loop = asyncio.new_event_loop()
    sub_task = loop.create_task(_subscribe())

    def _pump() -> None:
        loop.call_soon(loop.stop)
        loop.run_forever()

    pump = QTimer()
    pump.timeout.connect(_pump)
    pump.start(50)

    code = app.exec()
    sub_task.cancel()
    return code


if __name__ == "__main__":
    sys.exit(main())
