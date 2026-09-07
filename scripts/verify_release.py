#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, tempfile, zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

ap = argparse.ArgumentParser()
ap.add_argument('dist', nargs='?', default='dist')
a = ap.parse_args()
dist = Path(a.dist)
version = (Path(__file__).resolve().parents[1] / 'VERSION').read_text(encoding='utf-8').strip()
base = f'UrsusFlasher-{version}.zip'
zpath = dist / base
side = dist / f'{base}.sha256.txt'
assert zpath.is_file(), zpath
assert side.is_file(), side
expected = side.read_text(encoding='utf-8').split()[0]
actual = sha256(zpath)
assert actual == expected, (actual, expected)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(td)
    root = td / f'UrsusFlasher-{version}'
    manifest = root / 'SHA256SUMS'
    assert manifest.is_file()
    checked = 0
    for row in manifest.read_text(encoding='utf-8').splitlines():
        if not row.strip():
            continue
        expected_hash, name = row.split(None, 1)
        p = root / name.strip()
        assert p.is_file(), name
        assert sha256(p) == expected_hash, name
        checked += 1
    assert not list(root.rglob('__pycache__'))
    assert not list(root.rglob('*.pyc'))
print(f'RELEASE_ZIP_QA=PASS files={checked}')
