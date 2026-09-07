#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 data/expert.py "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
    printf '\nPress Enter to close / Нажмите Enter для закрытия...'
    IFS= read -r _ || true
fi
exit "$rc"
