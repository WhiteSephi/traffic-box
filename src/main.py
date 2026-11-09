"""Entry point for the cross-platform Fritz!Box Live Traffic Widget."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys

from PySide6.QtWidgets import QApplication

from src.config import AppConfig
from src.ui.widget import TrafficBox


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Fritz!Box Live Traffic Desktop Widget (UPnP & Fritz!OS)"
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default="",
        help="Optional working directory (used by autostart entry).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="",
        help="Override Fritz!Box IP or hostname (default: fritz.box).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a short headless verification of UI & UPnP client and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Launch the TrafficBox application."""
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.workdir:
        target_dir = Path(args.workdir)
        if target_dir.is_dir():
            os.chdir(target_dir)

    if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"

    app = QApplication(sys.argv)
    app.setApplicationName("TrafficBox")
    app.setDesktopFileName("trafficbox")
    app.setQuitOnLastWindowClosed(False)

    config = AppConfig.load()
    if args.host:
        config.fritzbox_host = args.host.strip()

    widget = TrafficBox(config)
    widget.show()

    def _handle_terminate_signal(_signum: int, _frame: object) -> None:
        widget.quit_application()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handle_terminate_signal)
            except (OSError, ValueError):
                pass

    if args.self_test:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, widget.quit_application)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
