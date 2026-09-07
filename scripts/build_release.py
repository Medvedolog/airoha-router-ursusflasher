#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, tempfile, zipfile
from pathlib import Path
from repo_common import ROOT, export_tree

ap = argparse.ArgumentParser()
ap.add_argument('--out-dir', default='dist')
ap.add_argument('--version', default=None)
a = ap.parse_args()
version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
if a.version and a.version != version:
    raise SystemExit(f'version must match repository VERSION ({version})')
out = Path(a.out_dir)
out.mkdir(parents=True, exist_ok=True)
name = f'UrsusFlasher-{version}'
with tempfile.TemporaryDirectory() as td:
    root = export_tree(Path(td) / name)
    zpath = out / f'{name}.zip'
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(root.parent))
    sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (out / f'{name}.zip.sha256.txt').write_text(f'{sha}  {zpath.name}\n', encoding='utf-8')
    print(zpath)
