#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from repo_common import ROOT, export_tree, sha256

VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

# Importing repo_common may create a local interpreter cache before QA starts.
# Remove interpreter-generated caches first; repository sources must remain cache-free.
for _d in list(ROOT.rglob('__pycache__')):
    shutil.rmtree(_d)
EXPECTED = {
    'ursusboot/artifacts/u-boot.bin': 'a41a81a011e19d1498d5ff0773dfd6bf9bd4c56beb3e7a46ce4622a643a30703',
    'ursusboot/artifacts/u-boot.lzma': '450add116075477311cbf794da2541ddbdb33fb0c9eade39a47cf8d1fc0a81b7',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip': 'ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600',
    'ursusboot/source/ursusboot-0.1.0-alpha4-FUDAN1-source.tar.zst': 'a8229334d7ef23ef196f6f5e90283196fd117d22083bd0d5709587ea124c04c5',
    'ursusboot/upstream/u-boot-2026.07.tar.bz2': '78e8bfc382fe388f9b55aa1daf8c563522a037779b5d4c349d1415e381f1243e',
    'openwrt/source/openwrt-3d1645ee26d6a2e20be71d7fa1716721bac78e53.zip': '648ed194e7de773c4c5eb7cfbac545d2d38569dba94da1873954a859897f715b',
    'openwrt/patches/24025.patch': 'a3e843e60c7efdf6f103c04153c40b711a369962a533f370ffbc38aa0dcf314e',
}

# Repository sources and documentation must remain cache-free.
for p in ROOT.rglob('*'):
    if not p.is_file():
        continue
    assert p.suffix != '.pyc', p
    assert '__pycache__' not in p.parts, p

assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == VERSION
for n in ('START_ONECLICK.cmd','START_ONECLICK.sh','START_EXPERT.cmd','START_EXPERT.sh'):
    assert (ROOT / n).is_file(), n
assert not (ROOT / 'START.cmd').exists()
assert not (ROOT / 'START.sh').exists()

for rel, expected in EXPECTED.items():
    actual = sha256(ROOT / rel)
    assert actual == expected, (rel, actual, expected)

# GitHub-safe SDK parts and exact reconstructed bundle hash contract.
parts = sorted((ROOT / 'toolchains/openwrt-sdk-r35906/parts').glob('openwrt-sdk-r35906.tar.zst.part*'))
assert len(parts) == 2, parts
assert all(p.stat().st_size < 100_000_000 for p in parts), [(p.name, p.stat().st_size) for p in parts]
h = hashlib.sha256()
for p in parts:
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
assert h.hexdigest() == '6ec133d3810812111d719b53c37dcd83501fe534a8d5f149d5f91e0a657991ac'

# Verify repository SHA256 closure when present.
repo_manifest = ROOT / 'SHA256SUMS'
if repo_manifest.is_file():
    for row in repo_manifest.read_text(encoding='utf-8').splitlines():
        if not row.strip():
            continue
        expected, name = row.split(None, 1)
        name = name.strip()
        target = ROOT / name
        assert target.is_file(), name
        actual = sha256(target)
        assert actual == expected, (name, actual, expected)

m = json.loads((ROOT / 'config/MANIFEST.json').read_text(encoding='utf-8'))
assert m['version'] == VERSION
assert 'FUDAN1' in (ROOT / 'README.md').read_text(encoding='utf-8')
assert '0.1.0-alpha4-FUDAN1' in (ROOT / 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-BUILD_INFO.txt').read_text(encoding='utf-8')
subprocess.run([sys.executable, str(ROOT / 'scripts/verify_readme_ru.py')], cwd=ROOT, check=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})

# Runtime syntax and current package self-tests. Compile in-process so QA does not
# spawn one interpreter per source file on slow/shared filesystems.
env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE'] = '1'
for p in list(sorted((ROOT / 'ursusflasher/src').glob('*.py'))) + list(sorted((ROOT / 'ursusflasher/tools').glob('*.py'))):
    compile(p.read_text(encoding='utf-8'), str(p), 'exec')
for d in ROOT.rglob('__pycache__'):
    shutil.rmtree(d)

with tempfile.TemporaryDirectory() as td:
    rel = export_tree(Path(td) / 'release')
    tests = [p.name for p in sorted((rel / 'tools').glob('selftest_*.py'))]
    tests.append('verify_manifest_closure.py')
    for test in tests:
        subprocess.run([sys.executable, str(rel / 'tools' / test)], cwd=rel, check=True, env=env)

    # Compare exported release content to the SHA256 manifest from the actual
    # current package that this roll-up was made from.
    expected_rows = (ROOT / 'ursusflasher/release/SHA256SUMS.expected').read_text(encoding='utf-8').splitlines()
    for row in expected_rows:
        if not row.strip():
            continue
        expected, name = row.split(None, 1)
        name = name.strip()
        p = rel / name
        assert p.is_file(), name
        actual = sha256(p)
        assert actual == expected, (name, actual, expected)

print('GITHUB_ROLLUP_REPO_QA=PASS')
