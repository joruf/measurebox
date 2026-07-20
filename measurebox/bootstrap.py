"""Runtime dependency detection and virtual-environment bootstrap."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from ctypes.util import find_library
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

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


def should_show_install_gui() -> bool:
    """Check whether a graphical install progress dialog should be shown.

    :return: True when GUI install feedback is enabled and a display is available.
    """
    if os.environ.get("MEASUREBOX_INSTALL_GUI", "1") != "1":
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_dependency_installer() -> int:
    """Execute the local dependency installer script.

    :return: Installer process exit code.
    """
    script_path = PROJECT_ROOT / "install_dependencies.py"
    if not script_path.exists():
        print("MeasureBox error: installer script not found at install_dependencies.py")
        return 1

    if should_show_install_gui():
        try:
            from measurebox.install_progress_gui import run_installer_with_progress_gui

            return run_installer_with_progress_gui()
        except Exception as error:
            print(f"MeasureBox: install GUI unavailable ({error}), continuing in terminal...")

    command = [sys.executable, str(script_path)]
    result = subprocess.run(command, check=False, cwd=str(PROJECT_ROOT))
    return result.returncode


def maybe_restart_using_venv_python() -> None:
    """Restart this application with project venv Python if available.

    :return: None.
    """
    venv_root = (PROJECT_ROOT / ".venv").resolve()
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    current_prefix = Path(sys.prefix).resolve()
    if not venv_python.exists():
        return
    if current_prefix == venv_root:
        return
    print("MeasureBox: restarting with project virtual environment...")
    result = subprocess.run(
        [str(venv_python), "-m", "measurebox", *sys.argv[1:]],
        check=False,
        cwd=str(PROJECT_ROOT),
    )
    raise SystemExit(result.returncode)


def venv_python_exists() -> bool:
    """Check whether the project virtual environment Python exists.

    :return: True when .venv Python exists.
    """
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
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
