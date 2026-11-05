#!/bin/sh
# Runs Pelagic from source on Linux (needs Python 3.10+ and `pip install -r requirements.txt`).
# Set PELAGIC_PYTHON to use a particular Python, for example a virtual environment's.
cd "$(dirname "$0")" || exit 1
PY="${PELAGIC_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi
exec "$PY" -m atlasbrowser "$@"
