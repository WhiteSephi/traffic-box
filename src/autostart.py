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


def get_windows_autostart_cmd(project_root: Path | None = None) -> str:
    """Generate the Windows command string for autostart."""
    if project_root is None:
        project_root = get_project_root()
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        return f'"{sys.executable}"'
    vbs_script = project_root / "start_windows.vbs"
    if vbs_script.is_file():
        return f'wscript.exe "{vbs_script}"'
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    exe_to_use = pythonw if pythonw.is_file() else python_exe
    return (
        f'"{exe_to_use}" -c "import sys, os; '
        f'sys.path.insert(0, r\'{project_root}\'); '
        f'os.chdir(r\'{project_root}\'); '
        f'from src.main import main; sys.exit(main())"'
    )


def get_linux_autostart_cmd(project_root: Path | None = None) -> str:
    """Generate the Linux Exec command string for autostart."""
    if project_root is None:
        project_root = get_project_root()
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        exe = str(sys.executable)
        return f'"{exe}"' if " " in exe else exe
    sh_script = project_root / "start_linux.sh"
    if sh_script.is_file():
        script_str = str(sh_script)
        return f'"{script_str}"' if " " in script_str else script_str
    python_exe = str(sys.executable)
    exe_str = f'"{python_exe}"' if " " in python_exe else python_exe
    return f"{exe_str} -m src.main"


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

            cmd = get_windows_autostart_cmd(project_root)

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
                exec_cmd = get_linux_autostart_cmd(project_root)
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=TrafficBox\n"
                    "Comment=Live Traffic Monitor Widget\n"
                    f"Path={project_root}\n"
                    f"Exec={exec_cmd}\n"
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


def sync_kwin_position_rule(x: int, y: int) -> bool:
    """Register or update a KWin window rule on KDE Plasma to enforce window position under Wayland."""
    if sys.platform != "linux":
        return False

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    kwinrules = config_home / "kwinrulesrc"

    rule_name = "TrafficBox-Position"
    rule_section = (
        f"[{rule_name}]\n"
        "Description=TrafficBox Placement\n"
        f"position={x},{y}\n"
        "positionrule=2\n"
        "wmclass=trafficbox\n"
        "wmclassmatch=1\n"
    )

    try:
        content = kwinrules.read_text(encoding="utf-8") if kwinrules.is_file() else "[General]\nrules=\n"
    except OSError:
        content = "[General]\nrules=\n"

    import re

    pattern = rf"\[{re.escape(rule_name)}\].*?(?=\n\[|\Z)"
    if re.search(pattern, content, flags=re.DOTALL):
        new_content = re.sub(pattern, rule_section.strip(), content, flags=re.DOTALL)
    else:
        new_content = content.rstrip() + "\n\n" + rule_section

    m = re.search(r"(\[General\][^\[]*?rules=)([^\n]*)", new_content)
    if m:
        prefix, existing_rules = m.group(1), m.group(2)
        rule_list = [r.strip() for r in existing_rules.split(",") if r.strip()]
        if rule_name not in rule_list:
            rule_list.append(rule_name)
            new_rules_line = f"{prefix}{','.join(rule_list)}"
            new_content = new_content[:m.start()] + new_rules_line + new_content[m.end():]
    else:
        if "[General]" in new_content:
            new_content = re.sub(r"\[General\]", f"[General]\nrules={rule_name}", new_content, count=1)
        else:
            new_content = f"[General]\nrules={rule_name}\n\n" + new_content

    try:
        kwinrules.write_text(new_content, encoding="utf-8")
    except OSError:
        return False

    import shutil
    import subprocess

    qdbus_bin = shutil.which("qdbus6") or shutil.which("qdbus")
    if qdbus_bin:
        try:
            subprocess.run(
                [qdbus_bin, "org.kde.KWin", "/KWin", "reconfigure"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
            )
        except Exception:
            pass

    return True
