#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
RELEASE = VERSION.split('-', 1)[0]
MANIFEST = json.loads((ROOT / 'config/MANIFEST.json').read_text(encoding='utf-8'))
BOOT = MANIFEST['ursusboot']['version']

assert RELEASE == '0.2.80', RELEASE
assert VERSION == '0.2.80-dev', VERSION
assert BOOT == '0.1.0-alpha5-t80', BOOT

ru = (ROOT / 'README.md').read_text(encoding='utf-8')
en = (ROOT / 'docs/README_EN.md').read_text(encoding='utf-8')
ru_i = (ROOT / 'docs/INSTRUCTIONS_RU.md').read_text(encoding='utf-8')
en_i = (ROOT / 'docs/INSTRUCTIONS_EN.md').read_text(encoding='utf-8')
em = (ROOT / 'docs/EMERGENCY_URSUSBOOT_RU.md').read_text(encoding='utf-8')
rel_ru = (ROOT / 'ursusflasher/release/README.md').read_text(encoding='utf-8')
workflow = (ROOT / '.github/workflows/public-test-release.yml').read_text(encoding='utf-8')

for text in (ru, en):
    assert 'releases/latest' not in text
    assert '0.2.80-dev' in text
    assert '0.1.0-alpha5-t80' in text
    assert 'HW_PENDING' in text

assert 'Python 3.12+' in ru
assert 'Python **3.12+**' in en

assert ru_i.startswith('# UrsusFlasher 0.2.80-dev / UrsusBoot t80')
assert en_i.startswith('# UrsusFlasher 0.2.80-dev / UrsusBoot t80')
for text in (ru_i, en_i):
    assert '0x60000' in text and '0x7ffff' in text
    assert 'OPENWRT_STOCK_LAYOUT' in text
    assert 'OPENWRT_UBI' in text
    assert 'HW_PENDING' in text
assert 'новый `OPENWRT_STOCK_LAYOUT`' in ru_i
assert 'stock-layout OpenWrt is retired as a normal write target' in en_i

assert 'alpha3 lineage' in em
assert '0.1.0-alpha5-t80' in em
assert '0.2.80-dev' in em
assert 'HW_PENDING' in em

assert rel_ru.startswith('# UrsusFlasher 0.2.80-dev')
assert 'UrsusBoot-MD T80' in rel_ru
assert 'UrsusBoot-MF T80' in rel_ru
assert 'HW_PENDING' in rel_ru
assert 'Python 3.12+' in rel_ru

assert 'hardware_passed' in workflow
assert 'Require hardware acceptance' in workflow

print('DOCS_IDENTITY_QA=PASS release=0.2.80-dev boot=t80 stock_layout_target=retired')
