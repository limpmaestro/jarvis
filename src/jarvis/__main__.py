"""Allow `python -m jarvis ...`."""

from __future__ import annotations

from jarvis.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
