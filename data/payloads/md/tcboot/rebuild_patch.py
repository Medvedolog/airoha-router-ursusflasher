#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parents[2]
KIT = ROOT.parents[3]
sys.path.insert(0, str(DATA))
from fit_fdt import analyze_sysupgrade
from tcboot_builder import build_tcboot

FW = KIT / 'fw' / 'openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb'
OUT = ROOT / 'tcboot-MD-direct-sysupgrade-patch8-FDTAWARE-BEAR-WRITE.bin'
info = analyze_sysupgrade(FW)
out, digest, bl33 = build_tcboot(ROOT, info, OUT)
print('output=' + str(out))
print('sha256=' + digest)
print('sysupgrade_sha256=' + info.sha256)
print('ubi_path=' + info.ubi_path)
print('reg=' + info.uboot_reg_literal)
print('bl33_decompressed_sha256=' + bl33)
print('PASS')
