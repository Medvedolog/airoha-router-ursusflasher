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
    'ursusboot/artifacts/u-boot.TEST61.bin': '43296d98686ada9e4e13c5a5a49430372abf45e9bd0fc8eae837920e8ba5224d',
    'ursusboot/artifacts/u-boot.TEST61.lzma': 'bec245ab0b10e3fffcc2f0a482c2c3b97b03577b4a03c436857243cd68ff9d29',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip': '3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea',
    'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst': '69b699b27700e06442fde86ff8d70c806118f3cc8f6ae37eac777225784cea29',
    'ursusboot/artifacts/u-boot.TEST60.bin': '4679214615c5b53d67173a31ff9203b834a880e9b1f407b10fcc9cda8e2d32d1',
    'ursusboot/artifacts/u-boot.TEST60.lzma': '335d92d42b63677e2d471c675cdab3867a062380919a207e407c8b074df168a9',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip': 'c0e88d734a33a72ef0ca002860eaf7ff6c7fa7cc856de3f781371259d013d9bb',
    'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST60-source.tar.zst': '1409036a6fdffe387c9532093e08efb10609a79b1f05207d66af6ed6f4801187',
    'ursusboot/artifacts/u-boot.bin': '06397f68ba876e01ba6a07ebbdbbcfac1e5341b9d82926fd6b4a54ae1bf7e552',
    'ursusboot/artifacts/u-boot.lzma': '648fe1e12616068a99305645b34bee74d669ee9219f51c26ddd0b6b5003e0b1f',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip': '548c446555231ee1b6ec4666000831226e0749c576d702c06dc5f501a6f510db',
    'ursusboot/artifacts/u-boot.TEST59.bin': 'e2e98b1da4f757065346b05aa0c004fe359e687d99209a4601fed0bf90d166ab',
    'ursusboot/artifacts/u-boot.TEST59.lzma': '1e729eee0daca21fdf77a4ac9dab57566351768a77e8712beb7f55e2b4038967',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST59-update.fip': 'e6fef3f64fe119994704812a6f2f0138bacfdf34705e5e8ed4933647b540e1b8',
    'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST59-source.tar.zst': 'fcd6a921094017bfed285c5d3a414618e4dfd183ea6a38a4a72d1234eb596654',
    'ursusboot/artifacts/u-boot.TEST58.bin': '38bf03eb725bb3c16dc311adc6d65ff8c3592714fd29ba35f141ec9dbe18facc',
    'ursusboot/artifacts/u-boot.TEST58.lzma': '445c94a8e59a026565378277e04518428d191aeec1c4bf9f0a795050e6665e68',
    'ursusboot/artifacts/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST58-update.fip': 'c6ccd1e69bfe64c39d7f261b7b3b2ec902f1f225f8f8fb35d9d928483d2a5598',
    'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST58-source.tar.zst': '13cf16ae7810ea19cb5a8a692e12917e2b381772fb012084d5760de15ea47344',
    'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst': '57736bb74e2efd198e56e687dba50b945c160ada8ee9a3f25e3534842aa7f8c3',
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

# Source snapshot must be physically readable, not merely hash-pinned.
_test61_source = ROOT / 'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst'
subprocess.run(['zstd', '-t', str(_test61_source)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
subprocess.run(['tar', '--zstd', '-tf', str(_test61_source)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

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
assert '0.2.61' in (ROOT / 'README.md').read_text(encoding='utf-8')
assert 'TEST61' in (ROOT / 'README.md').read_text(encoding='utf-8')
assert '0.1.0-alpha5-UBIUX1' in (ROOT / 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-BUILD_INFO.txt').read_text(encoding='utf-8')
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
