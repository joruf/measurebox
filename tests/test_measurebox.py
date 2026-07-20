"""Automated baseline tests for MeasureBox helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF

from measurebox import AppConfig, AutostartManager, ConfigManager, normalize_rect
from measurebox.bootstrap import should_show_install_gui
from measurebox.geometry import compute_resized_scene_rect
from measurebox.install_progress_gui import map_installer_line_to_status


def test_normalize_rect_orders_points_correctly() -> None:
    """normalize_rect should always return positive width and height."""
    rect = normalize_rect(QPointF(120.0, 80.0), QPointF(20.0, 10.0))
    assert rect.x() == 20.0
    assert rect.y() == 10.0
    assert rect.width() == 100.0
    assert rect.height() == 70.0


def test_config_manager_roundtrip(tmp_path: Path) -> None:
    """ConfigManager should persist and restore all fields."""
    manager = ConfigManager(tmp_path / "config.json")
    expected = AppConfig(
        line_rgba=(10, 20, 30, 40),
        fill_rgba=(50, 60, 70, 80),
        autostart_enabled=True,
    )
    manager.save(expected)
    loaded = manager.load()
    assert loaded == expected


def test_autostart_manager_enable_disable(tmp_path: Path) -> None:
    """AutostartManager should create and remove desktop entry."""
    desktop_file = tmp_path / "autostart" / "measurebox.desktop"
    manager = AutostartManager(desktop_file)
    command = "/usr/bin/python3 /tmp/measurebox.py"

    manager.enable(command)
    assert manager.is_enabled() is True
    content = desktop_file.read_text(encoding="utf-8")
    assert "Name=MeasureBox" in content
    assert f"Exec={command}" in content

    manager.disable()
    assert manager.is_enabled() is False


def test_compute_resized_scene_rect_keeps_opposite_anchor() -> None:
    """Resizing from one handle should keep the opposite edge anchored."""
    resized = compute_resized_scene_rect(
        left=100.0,
        top=100.0,
        right=200.0,
        bottom=200.0,
        handle="bottom_left",
        scene_x=50.0,
        scene_y=250.0,
        min_size=6.0,
    )
    assert resized.left() == 50.0
    assert resized.top() == 100.0
    assert resized.right() == 200.0
    assert resized.bottom() == 250.0

    shrunk = compute_resized_scene_rect(
        left=100.0,
        top=100.0,
        right=200.0,
        bottom=200.0,
        handle="left",
        scene_x=199.0,
        scene_y=150.0,
        min_size=6.0,
    )
    assert shrunk.right() == 200.0
    assert shrunk.width() == 6.0
    assert shrunk.left() == 194.0


def test_map_installer_line_to_status() -> None:
    """Installer log lines should map to readable setup status messages."""
    assert map_installer_line_to_status("MeasureBox installer: creating virtual environment...") == (
        "Creating Python virtual environment..."
    )
    assert map_installer_line_to_status("MeasureBox installer: done.") == (
        "Installation complete. Starting MeasureBox..."
    )
    assert map_installer_line_to_status("") is None


def test_should_show_install_gui_respects_display_and_env(monkeypatch) -> None:
    """Install GUI should only activate when enabled and a display is present."""
    monkeypatch.delenv("MEASUREBOX_INSTALL_GUI", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    assert should_show_install_gui() is True

    monkeypatch.setenv("MEASUREBOX_INSTALL_GUI", "0")
    assert should_show_install_gui() is False

    monkeypatch.delenv("MEASUREBOX_INSTALL_GUI", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert should_show_install_gui() is False

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert should_show_install_gui() is True


def test_launcher_imports_work_without_pyqt6() -> None:
    """Entry scripts must bootstrap before importing PyQt6-dependent modules."""
    project_root = Path(__file__).resolve().parent.parent
    script = """
import sys

sys.path.insert(0, %r)
blocked = type(sys)("PyQt6")
sys.modules["PyQt6"] = blocked
from measurebox.bootstrap import ensure_runtime_dependencies, detect_missing_dependencies
from measurebox.config import AppConfig
from measurebox.autostart import AutostartManager
print("launcher-import-ok")
""" % str(project_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "launcher-import-ok" in result.stdout
