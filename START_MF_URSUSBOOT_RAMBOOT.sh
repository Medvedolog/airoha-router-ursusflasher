#!/bin/sh
set -u
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 data/mf_ramboot.py
fi
printf '%s\n' '[ERROR] Python 3.12+ not found.' >&2
exit 127
