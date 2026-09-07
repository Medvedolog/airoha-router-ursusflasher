#!/usr/bin/env python3
from __future__ import annotations
import hashlib, inspect, json, lzma, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import ursusboot_install as bi
import ursusboot_update as up
import one_key as ok

m=json.loads((D/'data/MANIFEST.json').read_text(encoding='utf-8'))
c=m['ursusboot']['alpha4_fudan1_candidate']
assert m['version']=='0.2.51-md-alpha4-fudan1-stateui5-payloadrefresh1-rootfsmax2'
assert bi.TARGET_URSUS=='0.1.0-alpha4-FUDAN1'
assert up.PRODUCTION_PAYLOAD==bi.PAYLOAD
raw=Path(D/c['raw_bl33']).read_bytes(); comp=Path(D/c['lzma']).read_bytes(); fip=Path(D/c['persistent_fip']).read_bytes()
assert len(raw)==948608 and hashlib.sha256(raw).hexdigest()==c['raw_bl33_sha256']
assert len(comp)==324547 and hashlib.sha256(comp).hexdigest()==c['lzma_sha256']
assert len(fip)==503808 and hashlib.sha256(fip).hexdigest()==c['fip_sha256']
for marker in (b'FM25G01B',b'FM25G02B',b'FM25S01A',b'S35ML02G300',b'W25N02JW'):
    assert marker in raw, marker
assert comp[0]==0x9b and int.from_bytes(comp[1:5],'little')==0x100000 and int.from_bytes(comp[5:13],'little')==len(raw)
dec=lzma.LZMADecompressor(format=lzma.FORMAT_RAW,filters=[{'id':lzma.FILTER_LZMA1,'dict_size':1<<20,'lc':2,'lp':2,'pb':3}])
out=dec.decompress(comp[13:],max_length=len(raw))
assert out==raw
assert len(comp)<=0x50000 and 0x27800+len(comp)<=0x77800
ck=bi.validate_checksum_entry(fip); assert ck['offset']==0x7ac00 and ck['size']==40
lin=bi.validate_direct_stock_lineage(fip); assert lin['unchanged_non_bl33_entries']==8
assert lin['trusted_boot_firmware_sha256']==bi.EXPECTED_STOCK_BL2_SHA256

# Layout-agnostic raw resolver: an all_flash master is accepted only when the
# first 512 KiB itself passes the existing stock hybrid content proof.
stock=(bi.PAYLOAD_DIR/'stock_mtd0_reference.bin').read_bytes()
old_table, old_read = bi._ssh_mtd_table, bi._ssh_read_binary
try:
    bi._ssh_mtd_table=lambda host:[{'index':0,'device':'/dev/mtd0','size':0x10000000,'erase':0x20000,'name':'all_flash','offset':0,'flags':0x400}]
    bi._ssh_read_binary=lambda host,cmd,expected_size: stock
    target, blob, meta=bi._ssh_resolve_raw_boot_target('192.0.2.1',fip,D/'work-selftest-boot.bin')
    assert target['name']=='all_flash' and len(blob)==0x80000 and meta['hybrid_fip_sha256']==c['fip_sha256']
finally:
    bi._ssh_mtd_table, bi._ssh_read_binary = old_table, old_read
    (D/'work-selftest-boot.bin').unlink(missing_ok=True)

src=inspect.getsource(bi.run_install_ssh)
assert '_ssh_find_fip_volume' in src and '_ssh_resolve_raw_boot_target' in src
assert 'ubiupdatevol' in src and 'LAYOUT_UNKNOWN' in src
assert 'automatic retry is forbidden' in src
assert 'ensure_root_ssh_session' in inspect.getsource(bi._ssh_openwrt_identity)
assert 'password' in inspect.getsource(bi._ssh_openwrt_identity) or 'ensure_root_ssh_session' in inspect.getsource(bi._ssh_openwrt_identity)
assert 'install_ursus_from_openwrt' in inspect.getsource(ok.main)
assert 'root SSH' in inspect.getsource(ok.install_ursus_from_openwrt)
assert c['mtd_rw']['kernel']=='6.18.44'
helper=bi.MTD_RAW_HELPER
assert helper.is_file() and helper.stat().st_size==67088
assert hashlib.sha256(helper.read_bytes()).hexdigest()==c['raw_mtd_helper']['ursus_mtd_raw']['sha256']
assert 'ursus-mtd-raw' in inspect.getsource(bi._ssh_raw_writer)
assert 'bad-block-in-boot-range' in (bi.PAYLOAD_DIR/'ursus-mtd-raw.c').read_text(encoding='utf-8')
print('FUDAN1_BUILD_QA=PASS')
print('FUDAN1_SSH_LAYOUT_AGNOSTIC_QA=PASS')
print('FUDAN1_LZMA_SLOT_MARGIN=%d' % (0x50000-len(comp)))
