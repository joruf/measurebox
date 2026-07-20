"""Automated baseline tests for MeasureBox helpers."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF

from measurebox import AppConfig, AutostartManager, ConfigManager, normalize_rect
from measurebox.bootstrap import should_show_install_gui
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
