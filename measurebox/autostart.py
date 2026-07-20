"""Linux desktop autostart integration."""

from __future__ import annotations

from pathlib import Path


class AutostartManager:
    """Handle Linux desktop autostart .desktop integration."""

    def __init__(self, desktop_path: Path) -> None:
        """Initialize with autostart desktop file path.

        :param desktop_path: Full .desktop file location.
        """
        self.desktop_path = desktop_path

    def is_enabled(self) -> bool:
        """Check whether autostart file currently exists.

        :return: True when enabled.
        """
        return self.desktop_path.exists()

    def enable(self, exec_command: str) -> None:
        """Enable autostart by writing a desktop entry.

        :param exec_command: Shell-safe command to launch MeasureBox.
        :return: None.
        """
        self.desktop_path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=MeasureBox\n"
            "Comment=Desktop overlay rectangle measurement tool\n"
            f"Exec={exec_command}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        self.desktop_path.write_text(content, encoding="utf-8")

    def disable(self) -> None:
        """Disable autostart by removing the desktop entry.

        :return: None.
        """
        if self.desktop_path.exists():
            self.desktop_path.unlink()
