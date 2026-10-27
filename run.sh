#!/bin/sh
# Run from the checkout so output and default links.txt always live beside this file.
set -eu
cd -- "$(dirname -- "$0")"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

if [ ! -x .venv/bin/python ]; then
    ee_python=''
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
            ee_python="$candidate"
            break
        fi
    done
    if [ -z "$ee_python" ]; then
        echo 'Python 3.11+ is required; install it from https://www.python.org/downloads/ and try again.' >&2
        exit 1
    fi
    if ! "$ee_python" -m venv .venv; then
        echo 'Could not create .venv; install Python venv support (e.g. python3-venv on Debian/Ubuntu) and retry.' >&2
        exit 1
    fi
fi

if ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    echo 'The existing .venv needs Python 3.11+; rename .venv, install Python from https://www.python.org/downloads/ and retry.' >&2
    exit 1
fi
if [ ! -f .venv/.ee2kicad-ready ]; then
    if ! .venv/bin/python -m pip install -e .; then
        echo 'Setup failed; check your internet connection and Python/pip installation, then run this command again.' >&2
        exit 1
    fi
    : > .venv/.ee2kicad-ready
fi
exec .venv/bin/python -m easyeda2kicad_local "$@"
