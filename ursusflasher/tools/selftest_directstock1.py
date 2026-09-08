#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import ursusboot_install as bi
import one_key as ok

assert bi.TARGET_URSUS == '0.1.0-alpha5-UBIUX1-TEST61'
assert bi.PAYLOAD.name == 'ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip'
assert hashlib.sha256(bi.PAYLOAD.read_bytes()).hexdigest() == '3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea'
assert bi.ALPHA3_REFERENCE_PAYLOAD.name == 'ursusboot-md-0.1.0-alpha3-update.fip'
assert hashlib.sha256(bi.ALPHA3_REFERENCE_PAYLOAD.read_bytes()).hexdigest() == '597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce'

target=bi.require_payload()
lineage=bi.validate_direct_stock_lineage(target)
assert lineage['unchanged_non_bl33_entries'] == 8
assert lineage['trusted_boot_firmware_sha256'] == '07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e'
assert lineage['changed_entries'] == [bi.NT_FW_UUID.hex(), bi.CHECKSUM_UUID.hex()]

stock=(bi.PAYLOAD_DIR/'stock_mtd0_reference.bin').read_bytes()
candidate, meta=bi.build_candidate(stock,target)
assert candidate[:bi.FIP_PHYS_OFF] == stock[:bi.FIP_PHYS_OFF]
assert candidate[bi.STOCK_BOOT_ENV_OFF:] == stock[bi.STOCK_BOOT_ENV_OFF:]
assert candidate[bi.FIP_PHYS_OFF:bi.FIP_PHYS_OFF+len(target)] == target
assert meta['hybrid_fip_sha256'] == hashlib.sha256(target).hexdigest()

src=(D/'data/one_key.py').read_text(encoding='utf-8')
assert 'route="stock"' in src
assert 'alpha5-UBIUX1' in src
assert 'Служебный alpha3 bootstrap записан' not in src
assert 'first stock write uses exact alpha3' not in src.lower()

m=json.loads((D/'data/MANIFEST.json').read_text(encoding='utf-8'))
assert m['ursusboot']['stock_bootstrap_version'] == 'REMOVED_FROM_ONECLICK'
assert m['ursusboot']['direct_stock_target_version'] == '0.1.0-alpha5-UBIUX1-TEST61'

print('DIRECT_STOCK_HWFIX3_LINEAGE_QA=PASS')
print('DIRECT_STOCK_HWFIX3_CANDIDATE_QA=PASS')
print('ONECLICK_ALPHA3_INTERMEDIATE=REMOVED')
print('BOOTROM_EMERGENCY_ALPHA3=RETAINED')
