#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import tempfile
import zipfile
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('dist', nargs='?', default='dist-public')
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    version = (repo / 'VERSION').read_text(encoding='utf-8').strip()
    name = f'UrsusFlasher-{version.split("-", 1)[0]}-PUBLIC-TEST'
    dist = Path(args.dist)
    zpath = dist / f'{name}.zip'
    side = dist / f'{name}.zip.sha256.txt'
    assert zpath.is_file(), zpath
    assert side.is_file(), side
    assert side.read_text(encoding='utf-8').split()[0] == sha256(zpath)

    forbidden_fragments = (
        '/.github/', '/scripts/', '/tools/', '/openwrt/source/', '/openwrt/sdk/',
        '/toolchain/', '/gcc/', 'QA_REPORT_', 'ARCHITECTURE.md',
        'BACKUP_RESTORE_AUDIT', 'alpha4_hwfix_test.py',
        'ursus-mtd-raw.c', '.tar.zst', '.tar.xz', '.tar.gz',
    )
    required_suffixes = (
        '/START_ONECLICK.cmd', '/START_EXPERT.cmd', '/README.md', '/VERSION',
        '/data/one_key.py', '/data/expert.py', '/data/proven_backend.py',
        '/data/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip',
        '/data/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-ram-installer.fip',
        '/data/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-bl2.bin',
        '/data/payloads/md/bootrom-backup/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-bl31-uboot-ethfix.fip',
        '/data/payloads/md/bootrom-backup/nokia-xg040gmd-stock-recovery-initramfs.itb',
        '/fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin',
        '/fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb',
        '/doc/INSTRUCTIONS_RU.md', '/doc/EMERGENCY_URSUSBOOT_RU.md',
        '/PUBLIC_TEST_RELEASE.txt', '/SHA256SUMS', '/PAYLOAD_SHA256SUMS.txt',
    )

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            z.extractall(td)
        assert names, 'empty archive'
        normalized = ['/' + n.replace('\\', '/') for n in names]
        for frag in forbidden_fragments:
            assert not any(frag.lower() in n.lower() for n in normalized), f'forbidden public-release content: {frag}'
        for suffix in required_suffixes:
            assert any(n.endswith(suffix) for n in normalized), f'missing required public-release file: {suffix}'

        roots = {n.split('/', 2)[1] for n in normalized if n.count('/') >= 2}
        assert roots == {name}, roots
        root = td / name
        manifest = root / 'SHA256SUMS'
        checked = 0
        for row in manifest.read_text(encoding='utf-8').splitlines():
            if not row.strip():
                continue
            expected, rel = row.split(None, 1)
            p = root / rel.strip()
            assert p.is_file(), rel
            assert sha256(p) == expected, rel
            checked += 1
        assert not list(root.rglob('__pycache__'))
        assert not list(root.rglob('*.pyc'))

        # Syntax-check every shipped runtime Python file without creating .pyc.
        for py in sorted((root / 'data').rglob('*.py')):
            compile(py.read_text(encoding='utf-8'), str(py), 'exec')

        # Exercise the bootloader installer package contract on the pruned tree.
        subprocess.run(
            [sys.executable, str(root / 'data' / 'ursusboot_install.py'), '--selftest'],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    print(f'PUBLIC_RELEASE_QA=PASS files={checked}')


if __name__ == '__main__':
    main()
