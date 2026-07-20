"""MeasureBox for Linux X11 desktop measurements."""

from __future__ import annotations

from measurebox.autostart import AutostartManager
from measurebox.config import AppConfig, ConfigManager
from measurebox.geometry import normalize_rect

__all__ = [
    "AppConfig",
    "AutostartManager",
    "ConfigManager",
    "main",
    "normalize_rect",
    "run",
]


def run() -> int:
    """Run MeasureBox desktop application.

    :return: Process exit code.
    """
    from measurebox.app import run as _run

    return _run()


def main() -> int:
    """Bootstrap dependencies and run MeasureBox.

    :return: Process exit code.
    """
    from measurebox.app import main as _main

    return _main()
