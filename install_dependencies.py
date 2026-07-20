#!/usr/bin/env python3
"""Install MeasureBox dependencies in a local virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
from ctypes.util import find_library
from pathlib import Path
from shutil import which

SYSTEM_PACKAGE_MAP: dict[str, list[str]] = {
    "apt-get": ["libxcb-cursor0"],
    "dnf": ["xcb-util-cursor"],
    "pacman": ["xcb-util-cursor"],
    "zypper": ["libxcb-cursor0"],
}


def run_command(command: list[str], cwd: Path) -> int:
    """Run a command and return its exit code.

    :param command: Command list to execute.
    :param cwd: Working directory for command execution.
    :return: Process exit code.
    """
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def detect_missing_system_dependencies() -> list[str]:
    """Detect missing Qt/X11 runtime libraries.

    :return: List of missing library keys.
    """
    missing: list[str] = []
    if find_library("xcb-cursor") is None:
        missing.append("xcb-cursor")
    return missing


def detect_package_manager() -> str | None:
    """Detect supported Linux package manager available in PATH.

    :return: Package manager executable name or None.
    """
    for manager in ("apt-get", "dnf", "pacman", "zypper"):
        if which(manager) is not None:
            return manager
    return None


def with_privilege(command: list[str]) -> list[str] | None:
    """Add privilege escalation when current user is not root.

    :param command: Command to run with privileges.
    :return: Privileged command or None if impossible.
    """
    if os.geteuid() == 0:
        return command
    if which("sudo") is not None:
        return ["sudo", *command]
    return None


def install_system_dependencies(project_dir: Path) -> int:
    """Install required Linux system dependencies for Qt/X11.

    :param project_dir: Root path of MeasureBox project.
    :return: Exit code for system dependency installation.
    """
    missing = detect_missing_system_dependencies()
    if not missing:
        return 0

    package_manager = detect_package_manager()
    if package_manager is None:
        print("MeasureBox installer warning: no supported package manager found.")
        print("Please install xcb cursor runtime manually for your distro.")
        return 0

    packages = SYSTEM_PACKAGE_MAP[package_manager]
    print(f"MeasureBox installer: installing system dependencies via {package_manager}...")

    commands: list[list[str]]
    if package_manager == "apt-get":
        commands = [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", *packages],
        ]
    elif package_manager == "dnf":
        commands = [["dnf", "install", "-y", *packages]]
    elif package_manager == "pacman":
        commands = [["pacman", "-Sy", "--noconfirm", *packages]]
    else:
        commands = [["zypper", "--non-interactive", "install", *packages]]

    for command in commands:
        privileged = with_privilege(command)
        if privileged is None:
            print("MeasureBox installer error: root/sudo permissions are required for system packages.")
            print(f"Please install manually: {' '.join(command)}")
            return 1
        command_code = run_command(privileged, project_dir)
        if command_code != 0:
            print("MeasureBox installer error: failed to install system packages.")
            print(f"Please run manually: {' '.join(privileged)}")
            return command_code

    still_missing = detect_missing_system_dependencies()
    if still_missing:
        print("MeasureBox installer error: system dependency installation did not resolve all libraries.")
        return 1
    return 0


def ensure_venv(project_dir: Path, python_bin: str) -> int:
    """Create a virtual environment if it does not exist.

    :param project_dir: Root path of MeasureBox project.
    :param python_bin: Python binary used to create venv.
    :return: Exit code of venv creation command.
    """
    venv_dir = project_dir / ".venv"
    if venv_dir.exists():
        return 0
    print("MeasureBox installer: creating virtual environment...")
    return run_command([python_bin, "-m", "venv", str(venv_dir)], project_dir)


def install_packages(project_dir: Path) -> int:
    """Install or update dependencies in the project virtual environment.

    :param project_dir: Root path of MeasureBox project.
    :return: Exit code of package installation sequence.
    """
    venv_python = project_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print("MeasureBox installer error: .venv Python executable not found.")
        return 1

    print("MeasureBox installer: installing dependencies...")
    upgrade_code = run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], project_dir)
    if upgrade_code != 0:
        return upgrade_code

    install_code = run_command([str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"], project_dir)
    return install_code


def main() -> int:
    """Run the full MeasureBox dependency installation flow.

    :return: Process exit code.
    """
    project_dir = Path(__file__).resolve().parent

    system_code = install_system_dependencies(project_dir)
    if system_code != 0:
        return system_code

    create_code = ensure_venv(project_dir, sys.executable)
    if create_code != 0:
        return create_code

    install_code = install_packages(project_dir)
    if install_code != 0:
        return install_code

    print("MeasureBox installer: done.")
    print("Start command: .venv/bin/python -m measurebox")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
