#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
manifest = ROOT / 'SHA256SUMS'
listed = set()
for raw in manifest.read_text(encoding='utf-8').splitlines():
    if not raw.strip():
        continue
    try:
        _, rel = raw.split('  ', 1)
    except ValueError:
        raise SystemExit(f'bad SHA256SUMS line: {raw!r}')
    listed.add(rel)
actual = {
    p.relative_to(ROOT).as_posix()
    for p in ROOT.rglob('*')
    if p.is_file() and p != manifest
}
missing = sorted(actual - listed)
stale = sorted(listed - actual)
if missing or stale:
    if missing:
        print('UNMANIFESTED_FILES:')
        for x in missing:
            print(x)
    if stale:
        print('STALE_MANIFEST_ENTRIES:')
        for x in stale:
            print(x)
    raise SystemExit(1)
print(f'MANIFEST_CLOSURE_QA=PASS files={len(actual)}')
