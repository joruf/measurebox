"""Application configuration model and persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    """Application configuration state."""

    line_rgba: tuple[int, int, int, int] = (0, 255, 0, 179)
    fill_rgba: tuple[int, int, int, int] = (0, 255, 0, 51)
    autostart_enabled: bool = False
    status_notifications_enabled: bool = True
    ruler_enabled: bool = False
    ruler_outside: bool = False


class ConfigManager:
    """Read and write MeasureBox configuration."""

    def __init__(self, config_path: Path) -> None:
        """Initialize the manager with a target config path.

        :param config_path: Path to JSON config file.
        """
        self.config_path = config_path

    def load(self) -> AppConfig:
        """Load app configuration from disk.

        :return: Loaded config or defaults if file is missing/invalid.
        """
        if not self.config_path.exists():
            return AppConfig()

        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppConfig()

        line_rgba = self._as_rgba(payload.get("line_rgba"), (0, 255, 0, 179))
        fill_rgba = self._as_rgba(payload.get("fill_rgba"), (0, 255, 0, 51))
        autostart_enabled = bool(payload.get("autostart_enabled", False))
        status_notifications_enabled = bool(payload.get("status_notifications_enabled", True))
        ruler_enabled = bool(payload.get("ruler_enabled", False))
        ruler_outside = bool(payload.get("ruler_outside", False))
        return AppConfig(
            line_rgba=line_rgba,
            fill_rgba=fill_rgba,
            autostart_enabled=autostart_enabled,
            status_notifications_enabled=status_notifications_enabled,
            ruler_enabled=ruler_enabled,
            ruler_outside=ruler_outside,
        )

    def save(self, config: AppConfig) -> None:
        """Save app configuration to disk.

        :param config: Configuration model to persist.
        :return: None.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "line_rgba": list(config.line_rgba),
            "fill_rgba": list(config.fill_rgba),
            "autostart_enabled": config.autostart_enabled,
            "status_notifications_enabled": config.status_notifications_enabled,
            "ruler_enabled": config.ruler_enabled,
            "ruler_outside": config.ruler_outside,
        }
        self.config_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    @staticmethod
    def _as_rgba(value: object, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Validate and normalize RGBA values from JSON.

        :param value: Unknown JSON value.
        :param fallback: Fallback RGBA tuple.
        :return: Valid RGBA tuple.
        """
        if not isinstance(value, list) or len(value) != 4:
            return fallback
        try:
            r, g, b, a = (int(channel) for channel in value)
        except (TypeError, ValueError):
            return fallback
        channels = (r, g, b, a)
        if any(channel < 0 or channel > 255 for channel in channels):
            return fallback
        return channels
