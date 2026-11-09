#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Prefer XCB (XWayland/X11) for precise desktop widget positioning and taskbar exclusion
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb;wayland}"

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m src.main "$@"
else
    exec python3 -m src.main "$@"
fi
