#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 data/one_key.py "$@"
rc=$?
printf '\nPress Enter to close / Нажмите Enter для закрытия...'
IFS= read -r _ || true
exit "$rc"
