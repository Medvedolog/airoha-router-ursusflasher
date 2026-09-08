#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
RELEASE = VERSION.split('-', 1)[0]
MANIFEST = json.loads((ROOT / 'config/MANIFEST.json').read_text(encoding='utf-8'))
BOOT = MANIFEST['ursusboot']['version']

assert RELEASE == '0.2.61', RELEASE
assert BOOT == '0.1.0-alpha5-UBIUX1-TEST61', BOOT

ru = (ROOT / 'README.md').read_text(encoding='utf-8')
en = (ROOT / 'docs/README_EN.md').read_text(encoding='utf-8')
ru_i = (ROOT / 'docs/INSTRUCTIONS_RU.md').read_text(encoding='utf-8')
en_i = (ROOT / 'docs/INSTRUCTIONS_EN.md').read_text(encoding='utf-8')
em = (ROOT / 'docs/EMERGENCY_URSUSBOOT_RU.md').read_text(encoding='utf-8')
rel_ru = (ROOT / 'ursusflasher/release/README.md').read_text(encoding='utf-8')
workflow = (ROOT / '.github/workflows/public-test-release.yml').read_text(encoding='utf-8')

for text in (ru, en):
    assert 'releases/latest' not in text

assert f'UrsusFlasher-{RELEASE}' in ru
assert 'TEST61' in ru and 'полного аппаратного прогона' in ru
assert 'Python 3.12+' in ru
assert 'пропустить полный `mtd0..mtd16` backup' in ru
assert 'один `[y/N]`' in ru

assert f'UrsusFlasher-{RELEASE}' in en
assert 'TEST61' in en and 'hardware safety regression' in en
assert 'Python **3.12+**' in en
assert 'MTD, UBI and UBIFS' not in en
assert 'UBIFS filesystem commands' in en
assert '75-second reconnect grace' in en

assert ru_i.startswith('# UrsusFlasher 0.2.61 / TEST61')
assert 'Python 3.12+' in ru_i
assert 'live-capture текущего `mtd0`' in ru_i
assert 'ONE-CLICK не запускает self-update' in ru_i

assert en_i.startswith('# UrsusFlasher 0.2.61 / TEST61')
assert 'Python 3.12+' in en_i
assert '75-second reconnect grace' in en_i
assert 'ONE-CLICK never performs an automatic self-update' in en_i
assert 'COMPLETE/FAILED state remains visible as history' in en_i

assert 'alpha3 lineage' in em
assert '0.1.0-alpha5-UBIUX1-TEST61' in em
assert 'раздельные manifest/hash поля' in em

assert 'Python 3.12+' in rel_ru
assert 'Python 3.12+' in workflow
assert 'hardware safety regression TEST61' in workflow

print('DOCS_IDENTITY_QA=PASS')
