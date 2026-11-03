#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m src.main "$@"
else
    exec python3 -m src.main "$@"
fi
