#!/usr/bin/env python3
from pathlib import Path
import hashlib
import lzma
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parents[2]
KIT = ROOT.parents[3]
sys.path.insert(0, str(DATA))
from fit_fdt import analyze_sysupgrade
from tcboot_builder import build_tcboot, make_post_script

p = ROOT / 'tcboot-MD-direct-sysupgrade-patch8-FDTAWARE-BEAR-WRITE.bin'
o = ROOT / 'tcboot-original.bin'
fw = KIT / 'fw' / 'openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb'
info = analyze_sysupgrade(fw)
b = p.read_bytes(); a = o.read_bytes()
sha = lambda x: hashlib.sha256(x).hexdigest()
assert len(a) == len(b) == 0x80000
assert sha(a) == '2cd248f49ec1e73c048b3bfb9886c759c9cbb06f19823993c906500178dffb50'
assert b[0x950:0x960] == bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
size = struct.unpack_from('<Q', b, 0x968)[0]
dec = lzma.decompress(b[0x2a400:0x2a400+size], format=lzma.FORMAT_ALONE)
need = [
 b'U:UPLOAD_BEGIN', b'U:FIT_CHECK_BEGIN', b'U:FIT_CHECK_OK', b'U:UBI_PROBE_BEGIN',
 b'U:UBI_MIGRATION_BEGIN', b'U:CAL_SAVE_BEGIN', b'U:CAL_SAVE_OK', b'U:UBI_FORMAT_BEGIN', b'U:UBI_FORMAT_DONE',
 b'U:FIT_READBACK_OK', b'U:ENV_SAVE_OK', b'U:FLASH_COMPLETE_RESET', b'UrsusITB FDT p8', '🐻'.encode('utf-8'), b'UrsusFlasher WebFailsafe',
 b'bootcmd=echo U00_RECOVERY; httpd 192.168.1.1', b'U:FDT_PATH=$up', b'fdt set $up reg', b'fdt print $up reg',
 b'U:FDT_PATCH_OK', b'U:PREP_OK', b'U:KERNEL_GO', b'bootm prep', b'bootm go', b'saveenv',
 b'setenv us $filesize', b'/configurations default', b'/configurations/$uc description',
 b'mtd read ubi 8e000000 50c0000 40000', b'ubi create fit $us dynamic 5', b'ubi write $ua fit $us',
 info.ubi_path.encode('ascii'), info.uboot_reg_literal.encode('ascii'),
]
for token in need:
    assert token in dec, token
for forbidden in (b'81e8e400', b'cp.b 81e8e400', b'bootm cmdline', b'bootm bdt', b'/configurations/config-1 kernel'):
    assert forbidden not in dec, forbidden
assert make_post_script(info).encode('ascii') in dec
with tempfile.TemporaryDirectory() as td:
    rebuilt, digest, _ = build_tcboot(ROOT, info, Path(td) / 'rebuilt.bin')
    assert rebuilt.read_bytes() == b
    assert digest == sha(b)
print('PASS')
print('patched_sha256=' + sha(b))
print('sysupgrade_sha256=' + info.sha256)
print('ubi_path=' + info.ubi_path)
print('replacement_reg=' + info.uboot_reg_literal)
print('bl33_compressed_size=' + str(size))
print('bl33_decompressed_sha256=' + sha(dec))
