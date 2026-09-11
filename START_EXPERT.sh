#!/bin/sh
cd "$(dirname "$0")" || exit 1
entry=data/expert_multi.py
[ -f "$entry" ] || entry=ursusflasher/src/expert_multi.py
python3 "$entry" "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
    printf '\nPress Enter to close / Нажмите Enter для закрытия...'
    IFS= read -r _ || true
fi
exit "$rc"
