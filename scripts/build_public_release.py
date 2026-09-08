#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import os
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
    'TEST58_TEST_RU.md',
    'TEST59_TEST_RU.md',
    'TEST60_TEST_RU.md',
    'TEST61_TEST_RU.md',
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

    (root / 'PUBLIC_TEST_RELEASE.txt').write_text(
        'UrsusFlasher public test release for Nokia XG-040G-MD\n'
        'Contains the runnable flasher, required boot/recovery payloads, OpenWrt sysupgrade images, and user documentation.\n'
        'Excluded: repository sources, SDK/toolchains/GCC, build trees, QA archives, self-test tools, internal engineering documents, and helper C source.\n'
        'UrsusBoot alpha5-UBIUX1-TEST61 is a SAFETY REGRESSION public-test candidate. TEST59/60 are revoked for hardware use; historical main stock ONE-CLICK PASS remains TEST57/SkyHigh.\n'
        'TEST61 retains CONFIGTRIM1 and fixes split identity, redundant automatic FIP update, active-UBI detach, interrupted-upload recovery and stale failure-session behavior. Installed UrsusBoot updates are explicit operator actions only.\n',
        encoding='utf-8', newline='\n',
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
    name = public_name(version)

    with tempfile.TemporaryDirectory() as td:
        tree = export_tree(Path(td) / name)
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
