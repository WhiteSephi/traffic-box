"""Cross-platform autostart integration for Windows (Registry) and Linux/CachyOS (XDG)."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import tempfile

APP_NAME = "TrafficBox"
DESKTOP_FILENAME = "trafficbox.desktop"
_DESKTOP_EXEC_SPECIAL_CHARS = set(" \t\"'><~|&;$*?()`") | {"`"} | ({"\\"} if os.sep != "\\" else set())


def _escape_desktop_exec_arg(arg: str) -> str:
    """Escape a single executable path/argument according to the XDG Desktop Entry spec."""
    cleaned = arg.replace("\r", "").replace("\n", "").replace("%", "%%")
    if not cleaned:
        return '""'
    if any(ch in _DESKTOP_EXEC_SPECIAL_CHARS for ch in cleaned):
        escaped = cleaned
        if os.sep != "\\":
            escaped = escaped.replace("\\", "\\\\")
        escaped = (
            escaped.replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$")
        )
        return f'"{escaped}"'
    return cleaned


def _sanitize_desktop_path(path: Path) -> str:
    """Strip CR/LF characters before embedding a directory path in a .desktop file."""
    return str(path).replace("\r", "").replace("\n", "")


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
        wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
        return f'"{wscript}" "{vbs_script}"'
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    exe_to_use = pythonw if pythonw.is_file() else python_exe
    b64_root = base64.b64encode(str(project_root).encode("utf-8")).decode("ascii")
    return (
        f'"{exe_to_use}" -c "import base64, os, sys; '
        f"p = base64.b64decode('{b64_root}').decode('utf-8'); "
        f'sys.path.insert(0, p); os.chdir(p); '
        f'from src.main import main; sys.exit(main())"'
    )


def get_linux_autostart_cmd(project_root: Path | None = None) -> str:
    """Generate the Linux Exec command string for autostart."""
    if project_root is None:
        project_root = get_project_root()
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        return _escape_desktop_exec_arg(str(sys.executable))
    sh_script = project_root / "start_linux.sh"
    if sh_script.is_file():
        return _escape_desktop_exec_arg(str(sh_script))
    return f"{_escape_desktop_exec_arg(str(sys.executable))} -m src.main"


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
                    f"Path={_sanitize_desktop_path(project_root)}\n"
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
    """Register or update a KWin window rule on KDE Plasma to enforce window position and hide from taskbar."""
    if sys.platform != "linux":
        return False

    x, y = int(x), int(y)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    kwinrules = config_home / "kwinrulesrc"

    rule_name = "TrafficBox-Position"
    rule_section = (
        f"[{rule_name}]\n"
        "Description=TrafficBox Placement\n"
        f"position={x},{y}\n"
        "positionrule=3\n"
        "wmclass=.*[Tt]raffic[Bb]ox.*\n"
        "wmclassmatch=3\n"
        "wmclasscomplete=false\n"
        "skiptaskbar=true\n"
        "skiptaskbarrule=2\n"
        "skipswitcher=true\n"
        "skipswitcherrule=2\n"
    )

    try:
        content = kwinrules.read_text(encoding="utf-8") if kwinrules.is_file() else "[General]\ncount=0\nrules=\nOrder=\n"
    except OSError:
        content = "[General]\ncount=0\nrules=\nOrder=\n"

    import re

    pattern = rf"\[{re.escape(rule_name)}\].*?(?=\n\[|\Z)"
    if re.search(pattern, content, flags=re.DOTALL):
        content = re.sub(pattern, rule_section.strip(), content, flags=re.DOTALL)
    else:
        content = content.rstrip() + "\n\n" + rule_section.strip()

    # Ensure [General] section exists and contains count, rules, and Order keys
    gen_match = re.search(r"\[General\](.*?)(?=\n\[|\Z)", content, flags=re.DOTALL)
    if gen_match:
        gen_body = gen_match.group(1)
        r_m = re.search(r"rules=([^\n]*)", gen_body)
        rules_list = [r.strip() for r in r_m.group(1).split(",") if r.strip()] if r_m else []
        if rule_name not in rules_list:
            rules_list.append(rule_name)

        o_m = re.search(r"Order=([^\n]*)", gen_body)
        order_list = [r.strip() for r in o_m.group(1).split(",") if r.strip()] if o_m else []
        if rule_name not in order_list:
            order_list.append(rule_name)

        count_val = max(len(rules_list), len(order_list), 1)

        lines = [l for l in gen_body.split("\n") if not l.startswith(("rules=", "Order=", "count="))]
        lines = [l for l in lines if l.strip()]
        new_gen = "\n[General]\n" + "\n".join(
            lines
            + [
                f"count={count_val}",
                f"rules={','.join(rules_list)}",
                f"Order={','.join(order_list)}",
            ]
        ) + "\n"
        content = content[:gen_match.start()] + new_gen.lstrip() + content[gen_match.end():]
    else:
        content = f"[General]\ncount=1\nrules={rule_name}\nOrder={rule_name}\n\n" + content

    tmp_path: Path | None = None
    try:
        kwinrules.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".kwinrulesrc_", suffix=".tmp", dir=kwinrules.parent)
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content.strip() + "\n")
        os.replace(tmp_path, kwinrules)
        tmp_path = None
    except OSError:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
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
