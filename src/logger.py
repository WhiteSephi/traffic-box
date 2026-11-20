"""Privacy-preserving rotating file logging and GitHub issue diagnostics helper."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from PySide6.QtCore import QtMsgType, qInstallMessageHandler, qVersion

from src import __version__
from src.config import get_config_dir

if TYPE_CHECKING:
    from src.config import AppConfig

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 2
MAX_ISSUE_BODY_CHARS = 3800

_SAFE_IPS = frozenset({"127.0.0.1", "0.0.0.0", "192.168.178.1", "1.1.1.1", "8.8.8.8", "9.9.9.9"})
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_SECRET_RE = re.compile(
    r"(?i)\b(sid|password|passwd|pwd|fritz_password|token|secret|authorization)\s*([=:])\s*([^\s&\"',;]+)"
)

_qt_handler_installed = False
_excepthooks_installed = False
_previous_qt_handler = None


def redact_sensitive_text(text: str) -> str:
    """Mask user home paths, non-standard IPv4 addresses, and credential parameters."""
    if not text:
        return ""

    home_str = str(Path.home())
    if home_str:
        text = text.replace(home_str, "~")
        home_posix = home_str.replace("\\", "/")
        if home_posix != home_str:
            text = text.replace(home_posix, "~")

    def _replace_ip(match: re.Match[str]) -> str:
        ip = match.group(0)
        return ip if ip in _SAFE_IPS else "<IP>"

    text = _IPV4_RE.sub(_replace_ip, text)
    text = _SECRET_RE.sub(r"\1\2***", text)
    return text


class PrivacyRedactionFilter(logging.Filter):
    """Logging filter that redacts sensitive paths, IPs, and secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            redacted = redact_sensitive_text(rendered)
            if redacted != rendered:
                record.msg = redacted
                record.args = ()
        except Exception:
            pass
        return True


def get_log_dir() -> Path:
    """Return platform-specific log directory inside the active config directory."""
    log_dir = get_config_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return log_dir


def get_log_file() -> Path:
    """Return the main rotating log file path."""
    return get_log_dir() / "trafficbox.log"


def _install_qt_message_handler() -> None:
    """Forward Qt warnings and critical errors into Python logging."""
    global _qt_handler_installed, _previous_qt_handler
    if _qt_handler_installed:
        return

    qt_logger = logging.getLogger("trafficbox.qt")

    def _qt_msg_handler(mode: QtMsgType, _context: object, message: str) -> None:
        if mode == QtMsgType.QtDebugMsg:
            return
        if mode == QtMsgType.QtInfoMsg:
            qt_logger.debug(message)
        elif mode == QtMsgType.QtWarningMsg:
            qt_logger.warning(message)
        elif mode == QtMsgType.QtCriticalMsg:
            qt_logger.error(message)
        elif mode == QtMsgType.QtFatalMsg:
            qt_logger.critical(message)

    _previous_qt_handler = qInstallMessageHandler(_qt_msg_handler)
    _qt_handler_installed = True


def _install_excepthooks() -> None:
    """Capture uncaught main-thread and worker-thread exceptions into the log."""
    global _excepthooks_installed
    if _excepthooks_installed:
        return

    crash_logger = logging.getLogger("trafficbox.crash")
    orig_sys_hook = sys.excepthook
    orig_thread_hook = getattr(threading, "excepthook", None)

    def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            crash_logger.critical(
                "Uncaught exception in main thread",
                exc_info=(exc_type, exc_value, exc_tb),
            )
        orig_sys_hook(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not None and not issubclass(args.exc_type, SystemExit):
            thread_name = args.thread.name if args.thread else "unknown"
            crash_logger.critical(
                "Uncaught exception in thread %s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        if orig_thread_hook is not None:
            orig_thread_hook(args)

    sys.excepthook = _sys_excepthook
    if orig_thread_hook is not None:
        threading.excepthook = _thread_excepthook
    _excepthooks_installed = True


def setup_logging(debug: bool = False) -> Path:
    """Initialize rotating file logging for TrafficBox and return the log file path."""
    log_file = get_log_file()
    app_logger = logging.getLogger("trafficbox")
    app_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    app_logger.propagate = False

    has_file_handler = any(
        isinstance(h, RotatingFileHandler) for h in app_logger.handlers
    )
    if not has_file_handler:
        try:
            handler = RotatingFileHandler(
                log_file,
                maxBytes=MAX_LOG_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
            handler.addFilter(PrivacyRedactionFilter())
            app_logger.addHandler(handler)
        except OSError:
            pass

    _install_excepthooks()
    _install_qt_message_handler()

    is_frozen = getattr(sys, "frozen", False)
    app_logger.info(
        "TrafficBox v%s started | OS=%s %s (%s) | Python=%s | Qt=%s | Build=%s | Debug=%s",
        __version__,
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.python_version(),
        qVersion(),
        "Binary" if is_frozen else "Source",
        debug,
    )
    return log_file


def set_debug_logging(enabled: bool) -> None:
    """Toggle debug logging level at runtime without restarting the app."""
    app_logger = logging.getLogger("trafficbox")
    target_level = logging.DEBUG if enabled else logging.INFO
    if app_logger.level != target_level:
        app_logger.setLevel(target_level)
        app_logger.info("Debug logging %s", "enabled" if enabled else "disabled")


def read_recent_logs(max_lines: int = 120) -> str:
    """Read and redact the tail of the current log file."""
    log_file = get_log_file()
    if not log_file.is_file():
        return "(Noch keine Log-Einträge vorhanden.)"
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(Log-Datei konnte nicht gelesen werden: {redact_sensitive_text(str(exc))})"

    if not lines:
        return "(Log-Datei ist leer.)"

    tail = lines[-max_lines:]
    return redact_sensitive_text("\n".join(tail))


def collect_diagnostics_report(
    config: AppConfig,
    qt_version: str = "",
    max_log_lines: int = 120,
) -> str:
    """Build a privacy-safe markdown diagnostics report for GitHub bug reports."""
    is_frozen = getattr(sys, "frozen", False)
    cfg_dir = get_config_dir()
    storage_mode = "Portabel (local/)" if cfg_dir.name.lower() == "local" else "Systemprofil"
    qt_ver = qt_version or qVersion()
    custom_host = (config.fritzbox_host or "").strip().lower() not in ("", "fritz.box")

    lines = [
        "### Problembeschreibung",
        "<!-- Bitte beschreibe hier kurz, was passiert ist und wie man den Fehler reproduzieren kann: -->",
        "",
        "",
        "### System-Diagnose (anonymisiert)",
        f"- **App:** TrafficBox v{__version__} ({'Binary' if is_frozen else 'Source'}, {storage_mode})",
        f"- **OS:** {platform.system()} {platform.release()} ({platform.machine()})",
        f"- **Runtime:** Python {platform.python_version()} • Qt {qt_ver}",
        (
            f"- **Konfiguration:** Intervall={config.refresh_interval_sec}s, "
            f"Custom-Host={custom_host}, UPnP-Port={config.upnp_port}, "
            f"Gast-Monitor={config.enable_guest_monitor}, "
            f"Local-PC={config.enable_local_traffic_monitor}, "
            f"Health={config.enable_internet_health}, "
            f"Scale={config.ui_scale_percent}%, "
            f"Debug-Log={config.debug_logging}"
        ),
        "",
        f"### Letzte Log-Einträge (max. {max_log_lines} Zeilen)",
        "```log",
        read_recent_logs(max_lines=max_log_lines),
        "```",
    ]
    return "\n".join(lines)


def build_github_issue_url(report: str, base_issues_url: str) -> tuple[str, bool]:
    """Build a pre-filled GitHub New Issue URL, truncating the body if needed for URL limits."""
    new_issue_base = base_issues_url.rstrip("/") + "/new"
    body = report
    truncated = False
    if len(body) > MAX_ISSUE_BODY_CHARS:
        body = (
            body[: MAX_ISSUE_BODY_CHARS - 140]
            + "\n```\n\n*(Log gekürzt – vollständiger Diagnose-Bericht wurde in die Zwischenablage kopiert; bitte hier mit Strg+V einfügen.)*"
        )
        truncated = True

    params = urlencode({"title": "[Bug]: ", "body": body})
    return f"{new_issue_base}?{params}", truncated
