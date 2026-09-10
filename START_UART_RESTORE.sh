#!/bin/sh
cd "$(dirname "$0")" || exit 1
entry=data/uart_bootarea_restore.py
[ -f "$entry" ] || entry=ursusflasher/src/uart_bootarea_restore.py
exec python3 "$entry" "$@"
