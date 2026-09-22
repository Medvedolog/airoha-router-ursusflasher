#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import os
import shutil
import tempfile
import json
import zipfile
from pathlib import Path
from repo_common import ROOT, export_tree, write_manifest, sha256
from apply_ursusboot_release import apply_release

KEEP_DOCS = {
    'INSTRUCTIONS_RU.md',
    'INSTRUCTIONS_EN.md',
    'EMERGENCY_URSUSBOOT_RU.md',
    'CHANGELOG_RU.md',
    'TEST63_TEST_RU.md',
}


def public_name(version: str) -> str:
    """User-facing package name: the release number, not the build identity.

    VERSION carries the full build string (feature flags and all). It belongs
    inside the kit, where tooling reads it, and not in a filename someone has
    to type, quote in a bug report or read out loud.
    """
    return f'UrsusFlasher-{version.split("-", 1)[0]}-PUBLIC-TEST'


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
    for p in sorted(payload_root.rglob('*'), key=lambda item: item.relative_to(payload_root).as_posix()):
        if p.is_file():
            payload_rows.append(f'{sha256(p)}  {p.relative_to(root).as_posix()}')
    (root / 'PAYLOAD_SHA256SUMS.txt').write_text(
        '\n'.join(payload_rows) + '\n', encoding='utf-8', newline='\n'
    )

    rel_path = root / 'data' / 'URSUSBOOT_RELEASE.json'
    rel = json.loads(rel_path.read_text(encoding='utf-8')) if rel_path.is_file() else None
    lines = [
        'UrsusFlasher public test release for Nokia XG-040G-MD and XG-040G-MF',
        'Contains the runnable flasher, required boot/recovery payloads, OpenWrt sysupgrade images, and user documentation.',
        'Excluded: repository sources, SDK/toolchains/GCC, build trees, QA archives, self-test tools, internal engineering documents, and helper C source.',
    ]
    if rel:
        lines.append(f"UrsusBoot {rel['version']} from {rel['repo']}@{rel['commit']} (MD and MF, fast-scan UBI BL2).")
        for board, info in sorted(rel['boards'].items()):
            lines.append(f"{board}: ubi_preloader_sha256={info['ubi_preloader_sha256']} ubi_bl2_image_sha256={info['ubi_bl2_image_sha256']}")
    (root / 'PUBLIC_TEST_RELEASE.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    write_manifest(root)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='dist-public')
    ap.add_argument('--version', default=None)
    ap.add_argument('--target', choices=('all','md'), default='all')
    ap.add_argument('--ursusboot-md', default=None, help='airoha-ursusboot dist/xg040-md')
    ap.add_argument('--ursusboot-mf', default=None, help='airoha-ursusboot dist/xg040-mf')
    ap.add_argument('--ursusboot-pin', default=str(ROOT / 'config' / 'URSUSBOOT_PIN.json'))
    args = ap.parse_args()

    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if args.version and args.version != version:
        raise SystemExit(f'version must match repository VERSION ({version})')

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = public_name(version)

    with tempfile.TemporaryDirectory() as td:
        tree = export_tree(Path(td) / name, target=args.target)
        if args.target == 'all':
            # MD and MF are equal targets: both UrsusBoot builds from the one pinned commit.
            if not (args.ursusboot_md and args.ursusboot_mf):
                raise SystemExit('--target all needs --ursusboot-md and --ursusboot-mf (airoha-ursusboot release dist dirs)')
            apply_release(tree, Path(args.ursusboot_md), Path(args.ursusboot_mf), Path(args.ursusboot_pin))
        elif args.ursusboot_md or args.ursusboot_mf:
            raise SystemExit('an airoha-ursusboot release is packaged only into the two-target kit (--target all)')
        prune_public_tree(tree)
        zpath = out / f'{name}.zip'
        # Deterministic ZIP metadata. Files generated in the temporary export tree
        # (SHA256SUMS, PUBLIC_TEST_RELEASE.txt, etc.) would otherwise inherit the
        # wall-clock mtime of this packaging run and make byte-identical rebuilds
        # impossible even when payload content is unchanged.
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1788888600'))
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        # ZIP timestamps have 2-second granularity and no timezone field.
        zip_dt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second - (dt.second % 2))
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(tree.rglob('*'), key=lambda item: item.relative_to(tree).as_posix()):
                if not p.is_file():
                    continue
                arcname = p.relative_to(tree.parent).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=zip_dt)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100644 << 16)
                z.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        (out / f'{name}.zip.sha256.txt').write_text(
            f'{digest}  {zpath.name}\n', encoding='utf-8', newline='\n'
        )
        print(zpath)


if __name__ == '__main__':
    main()
