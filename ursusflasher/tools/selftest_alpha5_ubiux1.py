#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path
D=Path(__file__).resolve().parents[1]
M=json.loads((D/'data/MANIFEST.json').read_text(encoding='utf-8'))
a=M['ursusboot']['alpha5_ubiux1_candidate']
pd=D/'data/payloads/md/ursusboot'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert a['version']=='0.1.0-alpha5-UBIUX1'
assert sha(pd/'ursusboot-md-0.1.0-alpha5-UBIUX1-u-boot.bin')==a['raw_bl33_sha256']=='06397f68ba876e01ba6a07ebbdbbcfac1e5341b9d82926fd6b4a54ae1bf7e552'
assert sha(pd/'ursusboot-md-0.1.0-alpha5-UBIUX1-u-boot.lzma')==a['lzma_sha256']=='648fe1e12616068a99305645b34bee74d669ee9219f51c26ddd0b6b5003e0b1f'
assert sha(pd/'ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip')==a['fip_sha256']=='548c446555231ee1b6ec4666000831226e0749c576d702c06dc5f501a6f510db'
raw=(pd/'ursusboot-md-0.1.0-alpha5-UBIUX1-u-boot.bin').read_bytes()
for marker in (
 b'ursussettings', b'rootfs_data_max', b'URSUS_OPENWRT_SETTINGS_RESET_OK',
 b'X-Ursus-Keep-Settings', b'OPENWRT_STOCK_LAYOUT', b'URSUS_ROOTFS_DATA_CREATED',
 b'URSUS_ROOTFS_DATA_MAX_ENV_OK', b'DIRECT_RECOVERY_SAFE',
): assert marker in raw, marker
web=(D/'data/ursus_web_client.py').read_text(encoding='utf-8')
assert "layout in ('STOCK', 'OPENWRT_STOCK_LAYOUT')" in web
assert "X-Ursus-Keep-Settings" in web
assert 'reset_openwrt_settings' in web
inst=(D/'data/ursusboot_install.py').read_text(encoding='utf-8')
assert 'stock Web/Telnet fallback is disabled' in inst
assert '_tcp_open(host, 23)' not in inst[inst.index('def run_install('):inst.index('def _materialize_mtd0_backup')]
one=(D/'data/one_key.py').read_text(encoding='utf-8')
assert 'nokia_stock' in one and 'Stock Web/Telnet не запускается' in one
upd=(D/'data/ursusboot_update.py').read_text(encoding='utf-8')
assert 'Сохранить текущие настройки OpenWrt? [Y/n]' in upd
assert M['ursusboot']['layout_policy']['OPENWRT_STOCK_LAYOUT->OPENWRT_UBI']=='ALLOW_RECOVERY_ONLY'
print('ALPHA5_UBIUX1_ROOTFSENV1_QA=PASS')
print('ROUTE1_TELNET_NOT_STOCK_PROOF=PASS')
print('WEB_KEEP_RESET_SETTINGS_QA=PASS')
