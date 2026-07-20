"""Main controller wiring overlay, tray, config, and hotkeys."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from shutil import which
from time import monotonic

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from measurebox.autostart import AutostartManager
from measurebox.bootstrap import PROJECT_ROOT
from measurebox.config import AppConfig, ConfigManager
from measurebox.hotkeys import GlobalCtrlClickListener, GlobalHotkeyBridge, GlobalHotkeyListener
from measurebox.overlay_view import OverlayView


class MeasureBoxController(QObject):
    """Main controller that wires overlay, tray, config, and hotkeys."""

    def __init__(self, app: QApplication) -> None:
        """Initialize full application state.

        :param app: Running Qt application.
        """
        super().__init__()
        self.app = app
        config_dir = Path.home() / ".config" / "measurebox"
        self.config_manager = ConfigManager(config_dir / "config.json")
        self.autostart_manager = AutostartManager(Path.home() / ".config" / "autostart" / "measurebox.desktop")
        self.config = self.config_manager.load()
        if self.autostart_manager.is_enabled():
            self.config.autostart_enabled = True
        self.status_notifications_enabled = self.config.status_notifications_enabled
        self.ruler_enabled = self.config.ruler_enabled
        self.ruler_outside = self.config.ruler_outside
        self.line_color = QColor(*self.config.line_rgba)
        self.fill_color = QColor(*self.config.fill_rgba)
        self.overlay = OverlayView(self.line_color, self.fill_color)
        self.overlay.set_ruler_options(self.ruler_enabled, self.ruler_outside)
        self.hotkey_bridge = GlobalHotkeyBridge()
        self.hotkey_bridge.draw_mode_requested.connect(self.activate_draw_mode)
        self.hotkey_bridge.passthrough_mode_requested.connect(self.activate_passthrough_mode)
        self.hotkey_bridge.clear_requested.connect(self.handle_esc_pressed)
        self.hotkey_bridge.ctrl_click_requested.connect(self.handle_ctrl_click_activation)
        self.hotkey_bridge.ctrl_state_changed.connect(self.handle_ctrl_state_changed)
        self.hotkey_bridge.color_pick_requested.connect(self.handle_color_pick_at)
        self.draw_mode_hotkey_listener_primary = GlobalHotkeyListener(
            "<ctrl>+<shift>+d",
            self.hotkey_bridge.draw_mode_requested.emit,
        )
        self.draw_mode_hotkey_listener_fallback = GlobalHotkeyListener(
            "<ctrl>+<shift>+r",
            self.hotkey_bridge.draw_mode_requested.emit,
        )
        self.passthrough_hotkey_listener_primary = GlobalHotkeyListener(
            "<ctrl>+<shift>+p",
            self.hotkey_bridge.passthrough_mode_requested.emit,
        )
        self.passthrough_hotkey_listener_fallback = GlobalHotkeyListener(
            "<ctrl>+<shift>+s",
            self.hotkey_bridge.passthrough_mode_requested.emit,
        )
        self.clear_hotkey_listener = GlobalHotkeyListener("<esc>", self.hotkey_bridge.clear_requested.emit)
        self.ctrl_click_listener = GlobalCtrlClickListener(
            self.hotkey_bridge.ctrl_click_requested.emit,
            self.hotkey_bridge.ctrl_state_changed.emit,
            self.hotkey_bridge.color_pick_requested.emit,
        )
        self.tray_icon = self._build_tray()
        self.edit_mode_enabled = True
        self.interaction_locked = True
        self._esc_quit_window_seconds = 1.5
        self._esc_press_times: list[float] = []
        self.passthrough_refresh_timer = QTimer(self)
        self.passthrough_refresh_timer.setInterval(1000)
        self.passthrough_refresh_timer.timeout.connect(self.refresh_passthrough_mode)

    def start(self) -> None:
        """Start tray visibility and global listener.

        :return: None.
        """
        self.tray_icon.show()
        self.draw_mode_hotkey_listener_primary.start()
        self.draw_mode_hotkey_listener_fallback.start()
        self.passthrough_hotkey_listener_primary.start()
        self.passthrough_hotkey_listener_fallback.start()
        self.clear_hotkey_listener.start()
        self.ctrl_click_listener.start()
        self.passthrough_refresh_timer.start()
        self.activate_passthrough_mode(show_message=False)
        QTimer.singleShot(0, self._stabilize_draw_mode_after_start)
        QTimer.singleShot(250, self._stabilize_draw_mode_after_start)
        self._show_message(
            "MeasureBox active",
            "Hold Ctrl + mouse for draw/edit | Esc: Clear all.",
        )

    def shutdown(self) -> None:
        """Persist configuration and stop background listeners.

        :return: None.
        """
        self.draw_mode_hotkey_listener_primary.stop()
        self.draw_mode_hotkey_listener_fallback.stop()
        self.passthrough_hotkey_listener_primary.stop()
        self.passthrough_hotkey_listener_fallback.stop()
        self.clear_hotkey_listener.stop()
        self.ctrl_click_listener.stop()
        self.passthrough_refresh_timer.stop()
        self._save_config()

    def activate_draw_mode(self, show_message: bool = True) -> None:
        """Activate draw mode so overlay captures interactions.

        :param show_message: True to show tray notification.
        :return: None.
        """
        self.edit_mode_enabled = True
        self.interaction_locked = True
        self.overlay.set_interaction_lock(True)
        self.overlay.set_edit_mode(self.edit_mode_enabled)
        self.overlay.reapply_interaction_state()
        self.overlay.ensure_visible_foreground()
        self.overlay.set_interaction_lock(True)
        self.draw_mode_action.setChecked(True)
        self.passthrough_mode_action.setChecked(False)
        if show_message:
            self._show_message("MeasureBox", "Mode: DRAW")

    def activate_passthrough_mode(self, show_message: bool = True) -> None:
        """Activate pass-through mode so background apps receive input.

        :param show_message: True to show tray notification.
        :return: None.
        """
        self.edit_mode_enabled = True
        self.interaction_locked = False
        self.overlay.set_interaction_lock(False)
        self.overlay.set_edit_mode(self.edit_mode_enabled)
        self.overlay.ensure_visible_foreground()
        self.draw_mode_action.setChecked(False)
        self.passthrough_mode_action.setChecked(True)
        if show_message:
            self._show_message("MeasureBox", "Mode: PASS-THROUGH")

    def handle_ctrl_click_activation(self, x: int, y: int) -> None:
        """Activate draw interaction when Ctrl+LeftClick hits rectangle.

        :param x: Global X coordinate.
        :param y: Global Y coordinate.
        :return: None.
        """
        if self.overlay.try_activate_interaction_at_global(x, y):
            self.interaction_locked = True
            self.draw_mode_action.setChecked(True)
            self.passthrough_mode_action.setChecked(False)

    def handle_ctrl_state_changed(self, pressed: bool) -> None:
        """Switch between pass-through and draw interaction by Ctrl state.

        :param pressed: True while Ctrl is pressed.
        :return: None.
        """
        if pressed:
            self.activate_draw_mode(show_message=False)
            return
        self.activate_passthrough_mode(show_message=False)

    def handle_color_pick_at(self, x: int, y: int) -> None:
        """Pick color at global screen coordinates and copy it to clipboard.

        :param x: Global X coordinate.
        :param y: Global Y coordinate.
        :return: None.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        sample = screen.grabWindow(0, x, y, 1, 1)
        image = sample.toImage()
        if image.isNull() or image.width() < 1 or image.height() < 1:
            return

        color = image.pixelColor(0, 0)
        color_hex = color.name(QColor.NameFormat.HexRgb).upper()
        clipboard = self.app.clipboard()
        clipboard.setText(color_hex)
        self.overlay.set_active_pick_result(color_hex, x, y)
        self._show_message("MeasureBox", f"Color {color_hex} copied to clipboard.", desktop_notification=True)

    def refresh_passthrough_mode(self) -> None:
        """Re-apply pass-through mode every second when currently active.

        :return: None.
        """
        if self.interaction_locked:
            return
        self.overlay.ensure_visible_foreground()
        self.activate_passthrough_mode(show_message=False)

    def _stabilize_draw_mode_after_start(self) -> None:
        """Stabilize initial draw mode by forcing a fresh input-state apply.

        :return: None.
        """
        if not self.edit_mode_enabled or not self.interaction_locked:
            return
        self.overlay.reapply_interaction_state()
        self.overlay.raise_()

    def choose_line_color(self) -> None:
        """Open color picker for border color.

        :return: None.
        """
        selected = QColorDialog.getColor(
            initial=self.line_color,
            parent=None,
            title="Select line color (with alpha)",
            options=QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not selected.isValid():
            return
        self.line_color = selected
        self.overlay.set_line_color(self.line_color)
        self._save_config()

    def choose_fill_color(self) -> None:
        """Open color picker for fill color.

        :return: None.
        """
        selected = QColorDialog.getColor(
            initial=self.fill_color,
            parent=None,
            title="Select fill color (with alpha)",
            options=QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not selected.isValid():
            return
        self.fill_color = selected
        self.overlay.set_fill_color(self.fill_color)
        self._save_config()

    def clear_all_rectangles(self) -> None:
        """Delete all rectangles from overlay scene.

        :return: None.
        """
        self.overlay.clear_all()
        self.activate_draw_mode(show_message=False)
        self._show_message("MeasureBox", "All rectangles cleared.")

    def handle_esc_pressed(self) -> None:
        """Clear overlay and quit when Esc is pressed three times quickly.

        :return: None.
        """
        now = monotonic()
        self._esc_press_times = [
            timestamp
            for timestamp in self._esc_press_times
            if now - timestamp <= self._esc_quit_window_seconds
        ]
        self._esc_press_times.append(now)

        if len(self._esc_press_times) >= 3:
            self._show_message("MeasureBox", "Esc x3 detected. Exiting MeasureBox.")
            self.quit_application()
            return

        self.clear_all_rectangles()

    def toggle_autostart(self, checked: bool) -> None:
        """Enable or disable Linux desktop autostart.

        :param checked: Action checked state.
        :return: None.
        """
        if checked:
            self.autostart_manager.enable(self._build_exec_command())
            self._show_message("MeasureBox", "Autostart enabled.")
        else:
            self.autostart_manager.disable()
            self._show_message("MeasureBox", "Autostart disabled.")
        self.config.autostart_enabled = checked
        self._save_config()

    def toggle_status_notifications(self, checked: bool) -> None:
        """Enable or disable status notifications.

        :param checked: Action checked state.
        :return: None.
        """
        self.status_notifications_enabled = checked
        self.config.status_notifications_enabled = checked
        self._save_config()

    def toggle_ruler_enabled(self, checked: bool) -> None:
        """Enable or disable pixel ruler rendering.

        :param checked: Action checked state.
        :return: None.
        """
        self.ruler_enabled = checked
        self.overlay.set_ruler_options(self.ruler_enabled, self.ruler_outside)
        self.ruler_outside_action.setEnabled(checked)
        self.config.ruler_enabled = checked
        self._save_config()

    def toggle_ruler_outside(self, checked: bool) -> None:
        """Set whether ruler is drawn outside rectangle bounds.

        :param checked: Action checked state.
        :return: None.
        """
        self.ruler_outside = checked
        self.overlay.set_ruler_options(self.ruler_enabled, self.ruler_outside)
        self.config.ruler_outside = checked
        self._save_config()

    def quit_application(self) -> None:
        """Exit the application cleanly.

        :return: None.
        """
        self.shutdown()
        self.app.quit()

    def show_about_dialog(self) -> None:
        """Show About dialog with project and maintainer information.

        :return: None.
        """
        QMessageBox.information(
            None,
            "About MeasureBox",
            (
                "MeasureBox\n"
                "X11 overlay ruler with Ctrl-to-edit and pass-through mode.\n\n"
                "Joachim Ruf\n"
                "Loresoft\n"
                "https://www.loresoft.de\n"
                "https://github.com/joruf/"
            ),
        )

    def _build_shortcuts_menu(self, parent_menu: QMenu) -> QMenu:
        """Build a read-only menu section listing all shortcuts and controls.

        :param parent_menu: Parent tray menu.
        :return: Configured shortcuts submenu.
        """
        shortcuts_menu = QMenu("Shortcuts & Controls", parent_menu)
        entries = [
            "Hold Ctrl + Drag: Draw rectangle",
            "Hold Ctrl + Click rectangle: Move/Resize",
            "Ctrl + Left Double Click: Pick color to clipboard",
            "Esc: Clear all rectangles",
            "Esc x3 quickly: Quit MeasureBox",
            "Ctrl+Shift+D or Ctrl+Shift+R: Force Draw Mode",
            "Ctrl+Shift+P or Ctrl+Shift+S: Force Pass-through Mode",
        ]
        for label in entries:
            action = QAction(label, shortcuts_menu)
            action.setEnabled(False)
            shortcuts_menu.addAction(action)
        return shortcuts_menu

    def _build_tray(self) -> QSystemTrayIcon:
        """Create tray icon and context menu.

        :return: Configured tray icon.
        """
        tray_icon = QSystemTrayIcon(self._create_icon())
        tray_icon.setToolTip("MeasureBox")

        menu = QMenu()

        self.mode_action_group = QActionGroup(menu)
        self.mode_action_group.setExclusive(True)

        self.draw_mode_action = QAction("Draw Mode (Ctrl+Shift+D)", menu)
        self.draw_mode_action.setCheckable(True)
        self.draw_mode_action.setChecked(True)
        self.draw_mode_action.triggered.connect(self.activate_draw_mode)
        self.mode_action_group.addAction(self.draw_mode_action)
        menu.addAction(self.draw_mode_action)

        self.passthrough_mode_action = QAction("Pass-through Mode (Ctrl+Shift+P)", menu)
        self.passthrough_mode_action.setCheckable(True)
        self.passthrough_mode_action.setChecked(False)
        self.passthrough_mode_action.triggered.connect(self.activate_passthrough_mode)
        self.mode_action_group.addAction(self.passthrough_mode_action)
        menu.addAction(self.passthrough_mode_action)

        menu.addSeparator()

        line_action = QAction("Line Color...", menu)
        line_action.triggered.connect(self.choose_line_color)
        menu.addAction(line_action)

        fill_action = QAction("Fill Color...", menu)
        fill_action.triggered.connect(self.choose_fill_color)
        menu.addAction(fill_action)

        menu.addSeparator()

        clear_action = QAction("Clear All Rectangles (Esc)", menu)
        clear_action.triggered.connect(self.clear_all_rectangles)
        menu.addAction(clear_action)

        self.autostart_action = QAction("Enable Autostart", menu)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self.config.autostart_enabled)
        self.autostart_action.toggled.connect(self.toggle_autostart)
        menu.addAction(self.autostart_action)

        self.status_notifications_action = QAction("Show Status Notifications", menu)
        self.status_notifications_action.setCheckable(True)
        self.status_notifications_action.setChecked(self.status_notifications_enabled)
        self.status_notifications_action.toggled.connect(self.toggle_status_notifications)
        menu.addAction(self.status_notifications_action)

        self.ruler_enabled_action = QAction("Show Pixel Ruler (px)", menu)
        self.ruler_enabled_action.setCheckable(True)
        self.ruler_enabled_action.setChecked(self.ruler_enabled)
        self.ruler_enabled_action.toggled.connect(self.toggle_ruler_enabled)
        menu.addAction(self.ruler_enabled_action)

        self.ruler_outside_action = QAction("Ruler Outside Rectangle", menu)
        self.ruler_outside_action.setCheckable(True)
        self.ruler_outside_action.setChecked(self.ruler_outside)
        self.ruler_outside_action.setEnabled(self.ruler_enabled)
        self.ruler_outside_action.toggled.connect(self.toggle_ruler_outside)
        menu.addAction(self.ruler_outside_action)

        menu.addSeparator()
        menu.addMenu(self._build_shortcuts_menu(menu))
        menu.addSeparator()

        about_action = QAction("About", menu)
        about_action.triggered.connect(self.show_about_dialog)
        menu.addAction(about_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_application)
        menu.addAction(quit_action)

        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(self._on_tray_activated)
        return tray_icon

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Activate draw mode on tray icon double click.

        :param reason: Tray activation reason.
        :return: None.
        """
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.activate_draw_mode()

    def _create_icon(self) -> QIcon:
        """Create simple tray icon when no theme icon is available.

        :return: Generated icon.
        """
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.line_color, 2))
        painter.setBrush(self.fill_color)
        painter.drawRect(4, 4, 16, 16)
        painter.end()
        return QIcon(pixmap)

    def _build_exec_command(self) -> str:
        """Build shell-safe command for autostart desktop entry.

        :return: Escaped command line.
        """
        script_path = PROJECT_ROOT / "start_measurebox_desktop.sh"
        return f"bash {shlex.quote(str(script_path))}"

    def _show_message(self, title: str, message: str, desktop_notification: bool = False) -> None:
        """Show tray notification and optional desktop notification.

        :param title: Notification title.
        :param message: Notification message text.
        :param desktop_notification: True to force Linux desktop notification.
        :return: None.
        """
        if not self.status_notifications_enabled:
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 2200)
        if not desktop_notification:
            return
        notify_send = which("notify-send")
        if notify_send is None:
            return
        subprocess.run(
            [notify_send, "--app-name", "MeasureBox", title, message],
            check=False,
        )

    def _save_config(self) -> None:
        """Persist current mutable settings.

        :return: None.
        """
        self.config.line_rgba = (
            self.line_color.red(),
            self.line_color.green(),
            self.line_color.blue(),
            self.line_color.alpha(),
        )
        self.config.fill_rgba = (
            self.fill_color.red(),
            self.fill_color.green(),
            self.fill_color.blue(),
            self.fill_color.alpha(),
        )
        self.config.autostart_enabled = self.autostart_action.isChecked()
        self.config.status_notifications_enabled = self.status_notifications_enabled
        self.config.ruler_enabled = self.ruler_enabled
        self.config.ruler_outside = self.ruler_outside
        self.config_manager.save(self.config)
