"""Cross-platform autostart integration for Windows (Registry) and Linux/CachyOS (XDG)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

APP_NAME = "TrafficBox"
DESKTOP_FILENAME = "trafficbox.desktop"


def get_project_root() -> Path:
    """Return the root directory of the project."""
    return Path(__file__).resolve().parent.parent


def _get_linux_autostart_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / DESKTOP_FILENAME


def is_autostart_enabled() -> bool:
    """Check whether autostart is currently configured on the current OS."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except OSError:
            return False
    else:
        return _get_linux_autostart_file().is_file()


def set_autostart(enabled: bool) -> bool:
    """Enable or disable application autostart on Windows or Linux."""
    project_root = get_project_root()
    python_exe = Path(sys.executable)
    is_frozen = getattr(sys, "frozen", False)

    if sys.platform == "win32":
        try:
            import winreg

            if is_frozen:
                cmd = f'"{python_exe}"'
            else:
                pythonw = python_exe.with_name("pythonw.exe")
                exe_to_use = pythonw if pythonw.is_file() else python_exe
                cmd = f'"{exe_to_use}" -m src.main --workdir "{project_root}"'

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except OSError as exc:
            if sys.stderr is not None:
                print(f"[WARN] Windows-Autostart konnte nicht gesetzt werden: {exc}", file=sys.stderr)
            return False
    else:
        desktop_file = _get_linux_autostart_file()
        try:
            if enabled:
                desktop_file.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=TrafficBox\n"
                    "Comment=Live Traffic Monitor Widget\n"
                    f"Path={project_root}\n"
                    f"Exec={python_exe} -m src.main\n"
                    "Icon=network-workgroup\n"
                    "Terminal=false\n"
                    "Categories=Network;Monitor;Qt;\n"
                    "X-KDE-autostart-after=panel\n"
                )
                desktop_file.write_text(content, encoding="utf-8")
            else:
                if desktop_file.is_file():
                    desktop_file.unlink()
            return True
        except OSError as exc:
            if sys.stderr is not None:
                print(f"[WARN] Linux-Autostart konnte nicht gesetzt werden: {exc}", file=sys.stderr)
            return False
