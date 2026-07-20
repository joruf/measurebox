"""Application entry point for MeasureBox."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from measurebox.bootstrap import ensure_runtime_dependencies, ensure_system_runtime_dependencies
from measurebox.controller import MeasureBoxController


def run() -> int:
    """Run MeasureBox desktop application.

    :return: Process exit code.
    """
    ensure_system_runtime_dependencies()
    app = QApplication(sys.argv)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "MeasureBox", "System tray is not available on this desktop session.")
        return 1

    app.setQuitOnLastWindowClosed(False)
    controller = MeasureBoxController(app)
    controller.start()
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


def main() -> int:
    """Bootstrap dependencies and run MeasureBox.

    :return: Process exit code.
    """
    ensure_runtime_dependencies()
    return run()
