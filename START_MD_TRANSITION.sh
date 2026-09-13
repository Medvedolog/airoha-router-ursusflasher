#!/bin/sh
cd "$(dirname "$0")" || exit 1
entry=data/stock_ab_transition.py
[ -f "$entry" ] || entry=ursusflasher/src/stock_ab_transition.py
python3 "$entry" "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
    printf '\nPress Enter to close / Нажмите Enter для закрытия...'
    IFS= read -r _ || true
fi
exit "$rc"
