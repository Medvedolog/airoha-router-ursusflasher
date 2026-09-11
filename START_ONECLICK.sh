#!/bin/sh
cd "$(dirname "$0")" || exit 1
entry=data/one_key_v63.py
[ -f "$entry" ] || entry=ursusflasher/src/one_key_v63.py
python3 "$entry" "$@"
rc=$?
printf '\nPress Enter to close / Нажмите Enter для закрытия...'
IFS= read -r _ || true
exit "$rc"
