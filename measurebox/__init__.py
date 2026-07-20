"""MeasureBox for Linux X11 desktop measurements."""

from __future__ import annotations

from typing import Any

from measurebox.autostart import AutostartManager
from measurebox.config import AppConfig, ConfigManager

__all__ = [
    "AppConfig",
    "AutostartManager",
    "ConfigManager",
    "main",
    "normalize_rect",
    "run",
]


def __getattr__(name: str) -> Any:
    """Lazy-load symbols that require optional runtime dependencies.

    :param name: Requested attribute name.
    :return: Loaded symbol.
    """
    if name == "normalize_rect":
        from measurebox.geometry import normalize_rect

        return normalize_rect
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    from measurebox.bootstrap import ensure_runtime_dependencies

    ensure_runtime_dependencies()
    from measurebox.app import main as _run_main

    return _run_main()
