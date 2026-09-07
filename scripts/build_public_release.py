#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path
from repo_common import ROOT, export_tree, write_manifest, sha256

KEEP_DOCS = {
    'INSTRUCTIONS_RU.md',
    'INSTRUCTIONS_EN.md',
    'EMERGENCY_URSUSBOOT_RU.md',
    'CHANGELOG_RU.md',
}


def prune_public_tree(root: Path) -> None:
    # Developer/test utilities are not needed to flash a router.
    shutil.rmtree(root / 'tools', ignore_errors=True)

    # Lab-only host script: not referenced by ONE-CLICK/EXPERT production paths.
    lab = root / 'data' / 'alpha4_hwfix_test.py'
    if lab.exists():
        lab.unlink()

    # Keep the static runtime helper, omit its C source from the public bundle.
    helper_src = root / 'data' / 'payloads' / 'md' / 'ursusboot' / 'ursus-mtd-raw.c'
    if helper_src.exists():
        helper_src.unlink()

    doc = root / 'doc'
    if doc.is_dir():
        for p in list(doc.iterdir()):
            if p.is_file() and p.name not in KEEP_DOCS:
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)

    # Rebuild payload and complete package checksums after deliberate pruning.
    payload_rows = []
    payload_root = root / 'data' / 'payloads'
    for p in sorted(payload_root.rglob('*')):
        if p.is_file():
            payload_rows.append(f'{sha256(p)}  {p.relative_to(root).as_posix()}')
    (root / 'PAYLOAD_SHA256SUMS.txt').write_text('\n'.join(payload_rows) + '\n', encoding='utf-8')

    (root / 'PUBLIC_TEST_RELEASE.txt').write_text(
        'UrsusFlasher public test release for Nokia XG-040G-MD\n'
        'Contains the runnable flasher, required boot/recovery payloads, OpenWrt sysupgrade images, and user documentation.\n'
        'Excluded: repository sources, SDK/toolchains/GCC, build trees, QA archives, self-test tools, internal engineering documents, and helper C source.\n'
        'FUDAN1 hardware status remains HW_TEST_REQUIRED until dedicated hardware acceptance is complete.\n',
        encoding='utf-8',
    )
    write_manifest(root)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='dist-public')
    ap.add_argument('--version', default=None)
    args = ap.parse_args()

    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if args.version and args.version != version:
        raise SystemExit(f'version must match repository VERSION ({version})')

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f'UrsusFlasher-{version}-PUBLIC-TEST'

    with tempfile.TemporaryDirectory() as td:
        tree = export_tree(Path(td) / name)
        prune_public_tree(tree)
        zpath = out / f'{name}.zip'
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(tree.rglob('*')):
                if p.is_file():
                    z.write(p, p.relative_to(tree.parent))
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        (out / f'{name}.zip.sha256.txt').write_text(f'{digest}  {zpath.name}\n', encoding='utf-8')
        print(zpath)


if __name__ == '__main__':
    main()
