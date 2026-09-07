#!/usr/bin/env python3
from __future__ import annotations
import inspect, json, os, sys
from pathlib import Path

D = Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG', 'ru')
sys.path.insert(0, str(D / 'data'))
import alpha4_hwfix_test as h

r = h.validate_alpha4_host()
assert r == {
    'fip_size': 503808,
    'fip_sha256': 'a6d1977eed9eb08bb9960b6621322fdd20babe07fb36fdb178b61dedc09a8ad4',
    'fip_crc32': '470b3b69',
}
assert h.BASE_FIP_CRC == '1917ed23'
assert h.HWFIX_FIP_CRC == '470b3b69'
assert h.A3_FIP_CRC == '82263464'
assert h.A3_BL2_CRC == '9f7bf316'

# Existing active fip is the only persistent object changed.
tx = inspect.getsource(h._transaction)
assert tx.count("f'ubi write 0x{u.LOADADDR:x} fip 0x{FIP_SIZE:x}'") == 1
for forbidden in ('ubi remove ', 'ubi create ', 'ubi rename', 'mtd erase ', 'mtd write '):
    assert forbidden not in tx, forbidden
assert "'saveenv'" not in tx and '"saveenv"' not in tx
assert "f'ubi read 0x{u.READBACK_ADDR:x} fip 0x{FIP_SIZE:x}'" in tx
assert "f'cmp.b 0x{u.LOADADDR:x} 0x{u.READBACK_ADDR:x} 0x{FIP_SIZE:x}'" in tx
assert "f'ubi read 0x{u.READBACK_ADDR:x} fip.old 0x{FIP_SIZE:x}'" in tx
assert '_verify_unchanged_bl2' in tx

# One ordinary write confirmation only.
assert tx.count('ui.prompt(') == 1
assert '[y/N]' in tx
for token in ('WRITE ALPHA4', 'ROLLBACK ALPHA4', 'WRITE HWFIX', 'RECOVER URSUSBOOT'):
    assert token not in tx, token

run = inspect.getsource(h._run)
assert '_baseline(view, BASE_FIP_CRC)' in run
assert '_baseline(view, HWFIX_FIP_CRC)' in run
assert 'HWFIX_FIP, HWFIX_FIP_SHA, HWFIX_FIP_CRC' in run
assert 'BASE_FIP, BASE_FIP_SHA, BASE_FIP_CRC' in run
assert 'hardware-proven alpha4-HWFIX2 rollback FIP' in run

expert = (D / 'data/expert.py').read_text(encoding='utf-8')
# Historical HWFIX2<->HWFIX3 A/B machinery remains testable as source, but is no longer operator-facing.
for forbidden in ('alpha4_ab_install', 'alpha4_ab_rollback', 'alpha4_hwfix_test.install_hwfix3', 'alpha4_hwfix_test.rollback_hwfix3'):
    assert forbidden not in expert, forbidden
terms = json.loads((D / 'data/UI_TERMS.json').read_text(encoding='utf-8'))
assert 'alpha4_ab_install' not in terms['expert_actions']
assert 'alpha4_ab_rollback' not in terms['expert_actions']

m = json.loads((D / 'data/MANIFEST.json').read_text(encoding='utf-8'))
assert m['version'] == '0.2.51-md-alpha4-fudan1-stateui5-payloadrefresh1-rootfsmax2'
c = m['ursusboot']['alpha4_hwfix3_candidate']
assert c['fip_crc32'] == '470b3b69'
assert c['fip_sha256'] == h.HWFIX_FIP_SHA
assert c['required_bl2'].endswith('CRC32 9f7bf316')
assert 'one ordinary y/N' in c['confirmation']
assert 'HELD_AT_BOOT debounce=750 ms' in c['reset_policy']
assert '2585-byte' in c['compression']
assert '0x90000000 / 64 MiB' in c['ram_staging']
assert m['ursusboot']['alpha4_hwfix2_candidate']['status'] == 'HW_PROVEN_RECOVERY_SYSTEM_INFO_BASELINE'

raw = h.HWFIX_RAW.read_bytes()
required = (
    b'U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-UIFIX1 (',
    b'URSUS_WEB_ALREADY_RUNNING owner=active action=noop',
    b'URSUS_NET_ETHERNET_INACTIVE action=clean-stop',
    b'URSUS_CONSOLE_CAPTURE_SELFTEST_PASS',
    b'URSUS_RESET_POLICY=HELD_AT_BOOT debounce_ms=%lu legacy_hold_ms=%lu',
    b'bootcmd=ursusdispatch',
    b'URSUS_LED_MAP status-red=%s(ret=%d)',
    b'URSUS_LED_RECOVERY_PATTERN_SYNC=1',
    b'URSUS_BADBLOCK_SCAN source=UBI skip_full_mtd_scan=1',
    b'URSUS_BADBLOCK_SCAN source=MTD full_scan=1',
    b'"boot_validation_reason":"%s"',
    b'"api_version":190',
    b'initramfs/FIT exceeds shared 64 MiB staging capacity',
    b'https://github.com/Medvedolog/airoha-router-ursusflasher',
    'Предыдущий образ OpenWrt'.encode('utf-8'),
    'Максимальный размер для прошивки и initramfs/FIT — 64 МиБ.'.encode('utf-8'),
)
for marker in required:
    assert marker in raw, marker
for forbidden in (
    b'Run default boot command.',
    b'Load BL31+U-Boot FIP via TFTP then write to NAND',
    b'Load BL2 preloader via TFTP then write to NAND',
    b'U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-HWFIX2 (',
    'Резервный системный образ'.encode('utf-8'),
    'Роутер останется в режиме восстановления'.encode('utf-8'),
    b'[return=%d]\\n',
    b'16 MiB',
):
    assert forbidden not in raw, forbidden

# Source contract for the shared staging window and bootdelay suppression is shipped in build-info/manifest;
# binary gates above prove the matching runtime strings are present.
print('ALPHA4_HWFIX3_TEST1_QA=PASS')
print('DESTRUCTIVE_SCOPE=ACTIVE_FIP_ONLY')
print('ROLLBACK=ACTIVE_FIP_ONLY_TO_HW_PROVEN_HWFIX2')
print('OPERATOR_CONFIRMATIONS=1_NORMAL_YN')
print('GENERIC_UBOOT_COUNTDOWN=SUPPRESSED_FOR_URSUSDISPATCH')
print('RAM_STAGING=SHARED_0X90000000_64M_FIRMWARE_INITRAMFS')
print('SYSTEM_INFO_UX=DEDUP_HWFIX3')

inst=(D/'data/ursusboot_install.py').read_text(encoding='utf-8')
one=(D/'data/one_key.py').read_text(encoding='utf-8')
assert 'общего мигания/перезапуска индикаторов' in inst
assert '5-10 секунд' in one and 'примерно через 1 секунду' in one
assert '0,75 с' not in inst
print('RECOVERY_OPERATOR_FLOW_ACCEPT3_QA=PASS')
