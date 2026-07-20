#!/usr/bin/env python3
"""MeasureBox for Linux X11 desktop measurements."""

from __future__ import annotations

import json
import importlib.util
import os
import shlex
import subprocess
import sys
import threading
from ctypes.util import find_library
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

REQUIRED_PACKAGES: dict[str, str] = {
    "PyQt6": "PyQt6",
    "pynput": "pynput",
}
REQUIRED_SYSTEM_LIBRARIES: dict[str, str] = {
    "xcb-cursor": "libxcb-cursor0 (or distro equivalent)",
}


def detect_missing_dependencies() -> list[str]:
    """Detect which required Python packages are currently missing.

    :return: List of missing package names.
    """
    missing: list[str] = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return missing


def detect_missing_system_dependencies() -> list[str]:
    """Detect missing Linux runtime dependencies for Qt/X11 startup.

    :return: List of missing system package hints.
    """
    missing: list[str] = []
    for library_name, package_hint in REQUIRED_SYSTEM_LIBRARIES.items():
        if find_library(library_name) is None:
            missing.append(package_hint)
    return missing


def run_dependency_installer() -> int:
    """Execute the local dependency installer script.

    :return: Installer process exit code.
    """
    script_path = Path(__file__).resolve().parent / "install_dependencies.py"
    if not script_path.exists():
        print("MeasureBox error: installer script not found at install_dependencies.py")
        return 1
    command = [sys.executable, str(script_path)]
    result = subprocess.run(command, check=False)
    return result.returncode


def maybe_restart_using_venv_python() -> None:
    """Restart this script with project venv Python if available.

    :return: None.
    """
    script_dir = Path(__file__).resolve().parent
    venv_root = (script_dir / ".venv").resolve()
    venv_python = script_dir / ".venv" / "bin" / "python"
    current_prefix = Path(sys.prefix).resolve()
    if not venv_python.exists():
        return
    if current_prefix == venv_root:
        return
    print("MeasureBox: restarting with project virtual environment...")
    result = subprocess.run(
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        check=False,
    )
    raise SystemExit(result.returncode)


def venv_python_exists() -> bool:
    """Check whether the project virtual environment Python exists.

    :return: True when .venv Python exists.
    """
    venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
    return venv_python.exists()


def ensure_runtime_dependencies() -> None:
    """Ensure required dependencies are present, auto-install when missing.

    :return: None.
    """
    if venv_python_exists():
        maybe_restart_using_venv_python()

    missing_python = detect_missing_dependencies()
    if not missing_python:
        return

    print(f"MeasureBox: missing Python dependencies detected: {', '.join(missing_python)}")

    auto_install_enabled = os.environ.get("MEASUREBOX_AUTO_INSTALL", "1") == "1"
    if not auto_install_enabled:
        print("MeasureBox: automatic install disabled. Run python3 install_dependencies.py manually.")
        raise SystemExit(1)

    print("MeasureBox: running dependency installer...")
    exit_code = run_dependency_installer()
    if exit_code != 0:
        print("MeasureBox: dependency installer failed.")
        raise SystemExit(exit_code)

    maybe_restart_using_venv_python()
    missing_python_after = detect_missing_dependencies()
    if missing_python_after:
        print(f"MeasureBox: Python dependencies still missing: {', '.join(missing_python_after)}")
        raise SystemExit(1)


ensure_runtime_dependencies()

from pynput import keyboard, mouse
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)


def ensure_system_runtime_dependencies() -> None:
    """Ensure Linux system runtime dependencies for Qt/X11 are installed.

    :return: None.
    """
    missing_system = detect_missing_system_dependencies()
    if not missing_system:
        return

    print(f"MeasureBox: missing system dependencies detected: {', '.join(missing_system)}")
    auto_install_enabled = os.environ.get("MEASUREBOX_AUTO_INSTALL", "1") == "1"
    if not auto_install_enabled:
        print("MeasureBox: automatic install disabled. Run python3 install_dependencies.py manually.")
        raise SystemExit(1)

    print("MeasureBox: running dependency installer...")
    exit_code = run_dependency_installer()
    if exit_code != 0:
        print("MeasureBox: dependency installer failed.")
        raise SystemExit(exit_code)

    maybe_restart_using_venv_python()
    missing_system_after = detect_missing_system_dependencies()
    if missing_system_after:
        print(f"MeasureBox: system dependencies still missing: {', '.join(missing_system_after)}")
        raise SystemExit(1)


def normalize_rect(start: QPointF, end: QPointF) -> QRectF:
    """Create a normalized rectangle from two points.

    :param start: First point.
    :param end: Second point.
    :return: Normalized rectangle in scene coordinates.
    """
    return QRectF(start, end).normalized()


@dataclass(slots=True)
class AppConfig:
    """Application configuration state."""

    line_rgba: tuple[int, int, int, int] = (0, 255, 0, 179)
    fill_rgba: tuple[int, int, int, int] = (0, 255, 0, 51)
    autostart_enabled: bool = False


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
        return AppConfig(
            line_rgba=line_rgba,
            fill_rgba=fill_rgba,
            autostart_enabled=autostart_enabled,
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


class GlobalHotkeyBridge(QObject):
    """Bridge callbacks from pynput thread to Qt main thread."""

    draw_mode_requested = pyqtSignal()
    passthrough_mode_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    ctrl_click_requested = pyqtSignal(int, int)
    ctrl_state_changed = pyqtSignal(bool)


class GlobalHotkeyListener:
    """Listen for global hotkey events using pynput."""

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        """Store hotkey binding and callback.

        :param hotkey: Pynput hotkey pattern.
        :param on_toggle: Callback fired for hotkey activation.
        """
        self.hotkey = hotkey
        self.on_toggle = on_toggle
        self.listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        """Start global hotkey listener in background thread.

        :return: None.
        """
        self.listener = keyboard.GlobalHotKeys({self.hotkey: self.on_toggle})
        self.listener.start()

    def stop(self) -> None:
        """Stop global hotkey listener.

        :return: None.
        """
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


class GlobalCtrlClickListener:
    """Listen for global Ctrl+LeftClick to enter edit mode."""

    def __init__(
        self,
        on_ctrl_click: Callable[[int, int], None],
        on_ctrl_state_changed: Callable[[bool], None],
    ) -> None:
        """Store callback and initialize input listeners.

        :param on_ctrl_click: Callback receiving global click coordinates.
        :param on_ctrl_state_changed: Callback for Ctrl pressed/released state.
        """
        self.on_ctrl_click = on_ctrl_click
        self.on_ctrl_state_changed = on_ctrl_state_changed
        self._ctrl_down = False
        self._lock = threading.Lock()
        self.keyboard_listener: keyboard.Listener | None = None
        self.mouse_listener: mouse.Listener | None = None

    def start(self) -> None:
        """Start global keyboard and mouse listeners.

        :return: None.
        """
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.mouse_listener = mouse.Listener(on_click=self._on_click)
        self.keyboard_listener.start()
        self.mouse_listener.start()

    def stop(self) -> None:
        """Stop global keyboard and mouse listeners.

        :return: None.
        """
        if self.keyboard_listener is not None:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        if self.mouse_listener is not None:
            self.mouse_listener.stop()
            self.mouse_listener = None

    def _on_key_press(self, key) -> None:
        """Track Ctrl key down state.

        :param key: Pressed key event.
        :return: None.
        """
        if key in {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}:
            emit_change = False
            with self._lock:
                if not self._ctrl_down:
                    self._ctrl_down = True
                    emit_change = True
            if emit_change:
                self.on_ctrl_state_changed(True)

    def _on_key_release(self, key) -> None:
        """Track Ctrl key release state.

        :param key: Released key event.
        :return: None.
        """
        if key in {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}:
            emit_change = False
            with self._lock:
                if self._ctrl_down:
                    self._ctrl_down = False
                    emit_change = True
            if emit_change:
                self.on_ctrl_state_changed(False)

    def _on_click(self, x: float, y: float, button, pressed: bool) -> None:
        """Emit callback when Ctrl+LeftClick is detected.

        :param x: Global X coordinate.
        :param y: Global Y coordinate.
        :param button: Mouse button.
        :param pressed: True on press, False on release.
        :return: None.
        """
        if not pressed or button != mouse.Button.left:
            return
        with self._lock:
            ctrl_down = self._ctrl_down
        if ctrl_down:
            self.on_ctrl_click(int(x), int(y))


class ResizableRectItem(QGraphicsRectItem):
    """Draggable and resizable rectangle with 8 resize handles."""

    HANDLE_SIZE = 8.0
    MIN_SIZE = 6.0

    def __init__(self, scene_rect: QRectF, line_color: QColor, fill_color: QColor) -> None:
        """Create a new rectangle item.

        :param scene_rect: Initial geometry in scene coordinates.
        :param line_color: Border color.
        :param fill_color: Fill color.
        """
        super().__init__(QRectF(0.0, 0.0, scene_rect.width(), scene_rect.height()))
        self.setPos(scene_rect.topLeft())
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self._line_color = QColor(line_color)
        self._fill_color = QColor(fill_color)
        self._active_handle: str | None = None
        self._is_resizing = False
        self._label_item = QGraphicsSimpleTextItem("", self)
        self._label_item.setBrush(QColor(255, 255, 255, 235))
        self._label_item.setZValue(2)
        self._apply_style()
        self._update_measure_label()

    def set_colors(self, line_color: QColor, fill_color: QColor) -> None:
        """Update line and fill colors for this rectangle.

        :param line_color: New border color.
        :param fill_color: New fill color.
        :return: None.
        """
        self._line_color = QColor(line_color)
        self._fill_color = QColor(fill_color)
        self._apply_style()
        self.update()

    def boundingRect(self) -> QRectF:
        """Return item bounds including handle area.

        :return: Expanded bounding rectangle.
        """
        margin = self.HANDLE_SIZE
        return self.rect().adjusted(-margin, -margin, margin, margin)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        """Paint rectangle and resize handles when selected.

        :param painter: Active painter.
        :param option: Style option.
        :param widget: Optional paint widget.
        :return: None.
        """
        super().paint(painter, option, widget)
        if not self.isSelected():
            return
        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.setBrush(QColor(30, 30, 30, 220))
        for handle_rect in self._handle_rects().values():
            painter.drawRect(handle_rect)
        painter.restore()

    def hoverMoveEvent(self, event) -> None:  # type: ignore[override]
        """Set cursor shape according to active handle.

        :param event: Hover event.
        :return: None.
        """
        handle = self._handle_at(event.pos())
        self._set_cursor_for_handle(handle)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        """Restore cursor when leaving item bounds.

        :param event: Hover leave event.
        :return: None.
        """
        QApplication.restoreOverrideCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Start resizing if a handle is pressed.

        :param event: Mouse press event.
        :return: None.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._handle_at(event.pos())
            if handle is not None:
                self._active_handle = handle
                self._is_resizing = True
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Resize item while dragging a handle.

        :param event: Mouse move event.
        :return: None.
        """
        if self._is_resizing and self._active_handle is not None:
            self._resize_from_handle(self._active_handle, event.scenePos())
            self._update_measure_label()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Finish resize operation and refresh label.

        :param event: Mouse release event.
        :return: None.
        """
        if self._is_resizing:
            self._is_resizing = False
            self._active_handle = None
            self._update_measure_label()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._update_measure_label()

    def itemChange(self, change, value):  # type: ignore[override]
        """Update measure label after item movement.

        :param change: Change type.
        :param value: Proposed value.
        :return: Result passed to Qt.
        """
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._update_measure_label()
        return result

    def _apply_style(self) -> None:
        """Apply pen and brush styles.

        :return: None.
        """
        self.setPen(QPen(self._line_color, 2))
        self.setBrush(self._fill_color)

    def _scene_rect(self) -> QRectF:
        """Return current geometry in scene coordinates.

        :return: Scene rectangle.
        """
        local = self.rect()
        top_left = self.mapToScene(local.topLeft())
        bottom_right = self.mapToScene(local.bottomRight())
        return normalize_rect(top_left, bottom_right)

    def _update_measure_label(self) -> None:
        """Refresh dimensions label text and position.

        :return: None.
        """
        scene_rect = self._scene_rect()
        self._label_item.setText(
            f"x:{int(scene_rect.x())} y:{int(scene_rect.y())}  "
            f"w:{int(scene_rect.width())} h:{int(scene_rect.height())}"
        )
        self._label_item.setPos(QPointF(6.0, 4.0))

    def _set_cursor_for_handle(self, handle: str | None) -> None:
        """Set resize/move cursor based on handle identifier.

        :param handle: Handle key.
        :return: None.
        """
        cursor_map = {
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
        }
        cursor_shape = cursor_map.get(handle, Qt.CursorShape.SizeAllCursor)
        QApplication.setOverrideCursor(QCursor(cursor_shape))

    def _handle_rects(self) -> dict[str, QRectF]:
        """Compute all resize handle rectangles.

        :return: Mapping of handle name to local rect.
        """
        rect = self.rect()
        s = self.HANDLE_SIZE
        x_mid = rect.width() / 2.0
        y_mid = rect.height() / 2.0
        return {
            "top_left": QRectF(0 - s / 2.0, 0 - s / 2.0, s, s),
            "top": QRectF(x_mid - s / 2.0, 0 - s / 2.0, s, s),
            "top_right": QRectF(rect.width() - s / 2.0, 0 - s / 2.0, s, s),
            "right": QRectF(rect.width() - s / 2.0, y_mid - s / 2.0, s, s),
            "bottom_right": QRectF(rect.width() - s / 2.0, rect.height() - s / 2.0, s, s),
            "bottom": QRectF(x_mid - s / 2.0, rect.height() - s / 2.0, s, s),
            "bottom_left": QRectF(0 - s / 2.0, rect.height() - s / 2.0, s, s),
            "left": QRectF(0 - s / 2.0, y_mid - s / 2.0, s, s),
        }

    def _handle_at(self, local_pos: QPointF) -> str | None:
        """Find handle under local mouse position.

        :param local_pos: Mouse position in item coordinates.
        :return: Handle identifier or None.
        """
        for name, handle_rect in self._handle_rects().items():
            if handle_rect.contains(local_pos):
                return name
        return None

    def is_point_on_border(self, scene_pos: QPointF, tolerance: float = 6.0) -> bool:
        """Check whether a scene point is on the visible rectangle border area.

        :param scene_pos: Point in scene coordinates.
        :param tolerance: Border hit tolerance in pixels.
        :return: True if the point is on border/handle area.
        """
        local_pos = self.mapFromScene(scene_pos)
        if self._handle_at(local_pos) is not None:
            return True

        rect = self.rect()
        outer = rect.adjusted(-tolerance, -tolerance, tolerance, tolerance)
        inner = rect.adjusted(tolerance, tolerance, -tolerance, -tolerance)
        if not outer.contains(local_pos):
            return False
        if inner.width() <= 0 or inner.height() <= 0:
            return True
        return not inner.contains(local_pos)

    def _resize_from_handle(self, handle: str, scene_pos: QPointF) -> None:
        """Resize item from a specific handle using scene coordinates.

        :param handle: Handle identifier.
        :param scene_pos: Current mouse scene position.
        :return: None.
        """
        current = self._scene_rect()
        left = current.left()
        right = current.right()
        top = current.top()
        bottom = current.bottom()

        if handle in {"top_left", "left", "bottom_left"}:
            left = scene_pos.x()
        if handle in {"top_right", "right", "bottom_right"}:
            right = scene_pos.x()
        if handle in {"top_left", "top", "top_right"}:
            top = scene_pos.y()
        if handle in {"bottom_left", "bottom", "bottom_right"}:
            bottom = scene_pos.y()

        new_rect = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        if new_rect.width() < self.MIN_SIZE:
            new_rect.setWidth(self.MIN_SIZE)
        if new_rect.height() < self.MIN_SIZE:
            new_rect.setHeight(self.MIN_SIZE)
        self.setPos(new_rect.topLeft())
        self.setRect(QRectF(0.0, 0.0, new_rect.width(), new_rect.height()))
        self.update()


class OverlayView(QGraphicsView):
    """Transparent always-on-top overlay for drawing and editing rectangles."""

    def __init__(self, line_color: QColor, fill_color: QColor) -> None:
        """Build overlay scene and configure window flags.

        :param line_color: Initial border color.
        :param fill_color: Initial fill color.
        """
        self.scene = QGraphicsScene()
        super().__init__(self.scene)
        self._line_color = QColor(line_color)
        self._fill_color = QColor(fill_color)
        self._edit_mode_enabled = False
        self._drawing_active = False
        self._draw_start: QPointF | None = None
        self._preview_item: ResizableRectItem | None = None
        self._items: list[ResizableRectItem] = []
        # Keep it configurable for future re-enabling multi-rectangle mode.
        self._max_rectangles = 1
        self._interaction_locked = True
        self._auto_interaction_enabled = False
        self._border_activation_tolerance = 10.0
        self._body_activation_padding = 4.0
        self._transparent_state_applied: bool | None = None
        self._mouse_controller = mouse.Controller()
        self._forwarding_wheel = False
        self._wheel_angle_remainder_x = 0
        self._wheel_angle_remainder_y = 0
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(60)
        self._hover_timer.timeout.connect(self._sync_auto_interaction_mode)
        self._foreground_timer = QTimer(self)
        self._foreground_timer.setInterval(400)
        self._foreground_timer.timeout.connect(self._ensure_overlay_foreground)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")
        self._draw_window_flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self._passthrough_window_flags = (
            self._draw_window_flags
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(self._draw_window_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_virtual_geometry()
        self.show()
        self.set_edit_mode(False)
        self._hover_timer.start()
        self._foreground_timer.start()

    def set_line_color(self, color: QColor) -> None:
        """Set border color for new and existing rectangles.

        :param color: New border color.
        :return: None.
        """
        self._line_color = QColor(color)
        for item in self._items:
            item.set_colors(self._line_color, self._fill_color)

    def set_fill_color(self, color: QColor) -> None:
        """Set fill color for new and existing rectangles.

        :param color: New fill color.
        :return: None.
        """
        self._fill_color = QColor(color)
        for item in self._items:
            item.set_colors(self._line_color, self._fill_color)

    def set_edit_mode(self, enabled: bool) -> None:
        """Enable or disable interactive editing mode.

        :param enabled: True to capture mouse interactions.
        :return: None.
        """
        self._edit_mode_enabled = enabled
        self._apply_mouse_transparency()
        if enabled:
            self.raise_()
            if self._interaction_locked:
                self.activateWindow()
                self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        else:
            self.clear_selection()

    def set_interaction_lock(self, locked: bool) -> None:
        """Set whether overlay should capture interactions in edit mode.

        :param locked: True to capture input, False for click/scroll-through.
        :return: None.
        """
        self._interaction_locked = locked
        self._apply_mouse_transparency()

    def set_auto_interaction(self, enabled: bool) -> None:
        """Enable or disable automatic draw/pass-through switching.

        :param enabled: True to use automatic switching.
        :return: None.
        """
        self._auto_interaction_enabled = enabled

    def is_interaction_locked(self) -> bool:
        """Return whether overlay currently captures pointer input.

        :return: True when interaction is locked for editing.
        """
        return self._interaction_locked

    def is_cursor_in_active_item_area(self) -> bool:
        """Check whether the cursor is over the active rectangle interaction area.

        :return: True when cursor is over active rectangle interaction bounds.
        """
        if not self._items:
            return False
        active_item = self._items[-1]
        if active_item.scene() is None:
            return False
        cursor_pos_global = QCursor.pos()
        local_pos = self.mapFromGlobal(cursor_pos_global)
        scene_pos = self.mapToScene(local_pos)
        interaction_area = active_item.sceneBoundingRect().adjusted(
            -self._border_activation_tolerance,
            -self._border_activation_tolerance,
            self._border_activation_tolerance,
            self._border_activation_tolerance,
        )
        return interaction_area.contains(scene_pos)

    def try_activate_interaction_at_global(self, x: int, y: int) -> bool:
        """Enable edit interaction when a global point hits the active rectangle.

        :param x: Global X coordinate.
        :param y: Global Y coordinate.
        :return: True if interaction was activated.
        """
        if not self._items:
            return False
        active_item = self._items[-1]
        if active_item.scene() is None:
            self.scene.addItem(active_item)
        local_pos = self.mapFromGlobal(QPointF(float(x), float(y)).toPoint())
        scene_pos = self.mapToScene(local_pos)
        if not self._is_point_interacting_with_item(scene_pos, active_item):
            return False
        self.set_interaction_lock(True)
        self.clear_selection()
        active_item.setSelected(True)
        active_item.setFocus()
        self.raise_()
        return True

    def reapply_interaction_state(self) -> None:
        """Force a full re-application of current interaction flags.

        :return: None.
        """
        self._transparent_state_applied = None
        self._apply_mouse_transparency()

    def ensure_visible_foreground(self) -> None:
        """Ensure overlay and rectangle stay visible in the foreground.

        :return: None.
        """
        if not self._items:
            return
        self.show()
        self._ensure_scene_items_present()
        self.raise_()
        self.viewport().update()

    def clear_selection(self) -> None:
        """Unselect all rectangles.

        :return: None.
        """
        for item in self._items:
            item.setSelected(False)

    def clear_all(self) -> None:
        """Remove all rectangles from the overlay.

        :return: None.
        """
        for item in list(self._items):
            self.scene.removeItem(item)
        self._items.clear()
        self._preview_item = None

    def delete_selected(self) -> None:
        """Delete currently selected rectangles.

        :return: None.
        """
        for item in list(self._items):
            if item.isSelected():
                self.scene.removeItem(item)
                self._items.remove(item)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle local shortcuts in edit mode.

        :param event: Key event.
        :return: None.
        """
        if event.key() == Qt.Key.Key_Escape and self._drawing_active:
            self._cancel_drawing()
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin drawing rectangle in empty scene area.

        :param event: Mouse press event.
        :return: None.
        """
        if not self._edit_mode_enabled or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        target = self.itemAt(event.position().toPoint())
        active_item = self._items[-1] if self._items else None
        if target is None and active_item is not None:
            if self._is_point_interacting_with_item(scene_pos, active_item):
                target = active_item
                if not self._interaction_locked:
                    self.set_interaction_lock(True)
                self.clear_selection()
                active_item.setSelected(True)
                active_item.setFocus()

        if target is None:
            # With Ctrl/draw interaction active, empty-space click starts a new
            # rectangle (single-rectangle mode replaces the old one).
            if self._interaction_locked:
                self.clear_selection()
                self._drawing_active = True
                self._draw_start = scene_pos
                self._prepare_slot_for_new_rectangle()
                start_rect = QRectF(scene_pos, scene_pos)
                self._preview_item = ResizableRectItem(start_rect, self._line_color, self._fill_color)
                self.scene.addItem(self._preview_item)
                self._items.append(self._preview_item)
                self._preview_item.setSelected(True)
                event.accept()
                return

            # In pass-through mode, clicking outside keeps background interaction.
            if self._items:
                self.clear_selection()
                self.set_interaction_lock(False)
                event.accept()
                return
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update preview rectangle while drawing.

        :param event: Mouse move event.
        :return: None.
        """
        if self._drawing_active and self._draw_start is not None and self._preview_item is not None:
            current = self.mapToScene(event.position().toPoint())
            rect = normalize_rect(self._draw_start, current)
            self._preview_item.setPos(rect.topLeft())
            self._preview_item.setRect(0.0, 0.0, max(rect.width(), 1.0), max(rect.height(), 1.0))
            self._preview_item.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finalize rectangle drawing when mouse is released.

        :param event: Mouse release event.
        :return: None.
        """
        if self._drawing_active and event.button() == Qt.MouseButton.LeftButton:
            created_rectangle = False
            if self._preview_item is not None:
                rect = self._preview_item.rect()
                if rect.width() < 2.0 or rect.height() < 2.0:
                    self.scene.removeItem(self._preview_item)
                    self._items.remove(self._preview_item)
                else:
                    created_rectangle = True
            self._drawing_active = False
            self._draw_start = None
            self._preview_item = None
            if created_rectangle:
                self.clear_selection()
                self.set_interaction_lock(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Forward wheel scrolling so underlying apps keep scrolling.

        :param event: Wheel event.
        :return: None.
        """
        if not self._edit_mode_enabled or not self._interaction_locked:
            super().wheelEvent(event)
            return
        if self._forwarding_wheel:
            event.accept()
            return

        angle_x = event.angleDelta().x()
        angle_y = event.angleDelta().y()
        pixel_x = event.pixelDelta().x()
        pixel_y = event.pixelDelta().y()

        self._wheel_angle_remainder_x += angle_x
        self._wheel_angle_remainder_y += angle_y

        horizontal_steps = int(self._wheel_angle_remainder_x / 120)
        vertical_steps = int(self._wheel_angle_remainder_y / 120)

        self._wheel_angle_remainder_x -= horizontal_steps * 120
        self._wheel_angle_remainder_y -= vertical_steps * 120

        if horizontal_steps == 0 and angle_x == 0 and pixel_x != 0:
            horizontal_steps = 1 if pixel_x > 0 else -1
        if vertical_steps == 0 and angle_y == 0 and pixel_y != 0:
            vertical_steps = 1 if pixel_y > 0 else -1

        if vertical_steps == 0 and horizontal_steps == 0:
            event.accept()
            return

        self._forwarding_wheel = True
        try:
            if vertical_steps != 0:
                self._mouse_controller.scroll(0, vertical_steps)
            if horizontal_steps != 0:
                self._mouse_controller.scroll(horizontal_steps, 0)
        finally:
            self._forwarding_wheel = False
        event.accept()

    def _cancel_drawing(self) -> None:
        """Abort active drawing preview and remove temporary shape.

        :return: None.
        """
        if self._preview_item is not None and self._preview_item in self._items:
            self.scene.removeItem(self._preview_item)
            self._items.remove(self._preview_item)
        self._drawing_active = False
        self._draw_start = None
        self._preview_item = None

    def _prepare_slot_for_new_rectangle(self) -> None:
        """Enforce maximum rectangle count before creating a new one.

        :return: None.
        """
        while len(self._items) >= self._max_rectangles:
            oldest = self._items.pop(0)
            self.scene.removeItem(oldest)

    def _is_point_interacting_with_item(self, scene_pos: QPointF, item: ResizableRectItem) -> bool:
        """Check if a scene point should count as rectangle interaction.

        :param scene_pos: Point in scene coordinates.
        :param item: Active rectangle item.
        :return: True when point is on border/handles or inside item area.
        """
        if item.scene() is None:
            return False
        if item.is_point_on_border(scene_pos, self._border_activation_tolerance):
            return True
        local_point = item.mapFromScene(scene_pos)
        interaction_rect = item.rect().adjusted(
            -self._body_activation_padding,
            -self._body_activation_padding,
            self._body_activation_padding,
            self._body_activation_padding,
        )
        return interaction_rect.contains(local_point)

    def _apply_mouse_transparency(self) -> None:
        """Apply click-through behavior based on mode and interaction lock.

        :return: None.
        """
        transparent = not self._edit_mode_enabled or not self._interaction_locked
        if self._transparent_state_applied == transparent:
            return
        previous_transparent = self._transparent_state_applied
        self._transparent_state_applied = transparent
        # Use dedicated window flag profiles per mode. In pass-through we add
        # an X11 WM bypass hint so the visible overlay is less likely to be
        # pushed behind other windows after background clicks.
        if transparent:
            window_flags = self._passthrough_window_flags | Qt.WindowType.WindowTransparentForInput
        else:
            window_flags = self._draw_window_flags
        if self.windowFlags() != window_flags:
            self.setWindowFlags(window_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        self.show()
        self._apply_virtual_geometry()
        self._ensure_scene_items_present()
        self.raise_()

    def _sync_auto_interaction_mode(self) -> None:
        """Auto-switch between draw and pass-through based on pointer position.

        :return: None.
        """
        if not self._auto_interaction_enabled or not self._edit_mode_enabled:
            return
        if self._drawing_active:
            if not self._interaction_locked:
                self.set_interaction_lock(True)
            return
        if not self._items:
            if not self._interaction_locked:
                self.set_interaction_lock(True)
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return

        cursor_pos_global = QCursor.pos()
        local_pos = self.mapFromGlobal(cursor_pos_global)
        scene_pos = self.mapToScene(local_pos)
        active_item = self._items[-1]
        if active_item.scene() is None:
            self.scene.addItem(active_item)
        interaction_area = active_item.sceneBoundingRect().adjusted(
            -self._border_activation_tolerance,
            -self._border_activation_tolerance,
            self._border_activation_tolerance,
            self._border_activation_tolerance,
        )
        in_interaction_area = interaction_area.contains(scene_pos)

        # Automatic re-entry: while in pass-through, require an active left click
        # inside the rectangle area before switching back to draw interaction.
        left_pressed = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        if in_interaction_area and not self._interaction_locked and left_pressed:
            self.set_interaction_lock(True)
            active_item.setSelected(True)
            active_item.setFocus()
            return
        if self._interaction_locked and in_interaction_area and not active_item.isSelected():
            active_item.setSelected(True)

    def _ensure_overlay_foreground(self) -> None:
        """Keep overlay visible above desktop when rectangles exist.

        :return: None.
        """
        if not self._edit_mode_enabled:
            return
        if not self._items:
            return
        self.raise_()

    def _ensure_scene_items_present(self) -> None:
        """Re-attach tracked rectangle items if compositor remaps the window.

        :return: None.
        """
        for item in self._items:
            if item.scene() is None:
                self.scene.addItem(item)

    def _apply_virtual_geometry(self) -> None:
        """Resize overlay to span all X11 screens.

        :return: None.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.virtualGeometry()
        self.setGeometry(geometry)
        self.scene.setSceneRect(QRectF(geometry))


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
        self.line_color = QColor(*self.config.line_rgba)
        self.fill_color = QColor(*self.config.fill_rgba)
        self.overlay = OverlayView(self.line_color, self.fill_color)
        self.hotkey_bridge = GlobalHotkeyBridge()
        self.hotkey_bridge.draw_mode_requested.connect(self.activate_draw_mode)
        self.hotkey_bridge.passthrough_mode_requested.connect(self.activate_passthrough_mode)
        self.hotkey_bridge.clear_requested.connect(self.handle_esc_pressed)
        self.hotkey_bridge.ctrl_click_requested.connect(self.handle_ctrl_click_activation)
        self.hotkey_bridge.ctrl_state_changed.connect(self.handle_ctrl_state_changed)
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
        # Default to pass-through so normal clicks reach background apps.
        self.activate_passthrough_mode(show_message=False)
        # Re-apply draw readiness after event loop starts. Some X11 compositors
        # can ignore the first transparent-input flag transition at startup.
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
        # Defensive re-apply in case a compositor ignores a prior flag toggle.
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
        # After clearing, always return to draw-ready state.
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

    def quit_application(self) -> None:
        """Exit the application cleanly.

        :return: None.
        """
        self.shutdown()
        self.app.quit()

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

        menu.addSeparator()

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
        script_path = Path(__file__).resolve().parent / "start_measurebox_desktop.sh"
        return f"bash {shlex.quote(str(script_path))}"

    def _show_message(self, title: str, message: str) -> None:
        """Show tray notification if system tray is available.

        :param title: Notification title.
        :param message: Notification message text.
        :return: None.
        """
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 2200)

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
        self.config_manager.save(self.config)


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


if __name__ == "__main__":
    raise SystemExit(run())
