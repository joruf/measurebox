#!/usr/bin/env python3
"""Backward-compatible launcher for MeasureBox."""

from __future__ import annotations

if __name__ == "__main__":
    from measurebox.bootstrap import ensure_runtime_dependencies

    ensure_runtime_dependencies()
    from measurebox.app import main

    raise SystemExit(main())
