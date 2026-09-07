#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,sys
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'data'))
F=R/'fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin'
U=R/'fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(F)=='23ad06174184f71c9a845734571752f62930ba1cfac45f4ad8deadd9d8965820'
assert sha(U)=='47ea7c6f1e22a4aae9482e653a4fc6e87524f7e27847aaaed7fb75349cae7f3d'
assert F.stat().st_size==8714513
assert U.stat().st_size==10408217
b=json.loads((R/'data/FIRMWARE_BUNDLE.json').read_text(encoding='utf-8'))
assert b['openwrt_revision']=='r36009+75-6c315233aa' and b['kernel_vermagic']=='bed7e2dec73efb4c3050bc8a8373af30'
assert 'LAN4 becomes WAN' in b['network_profile']
src=(R/'data/network_guidance.py').read_text(encoding='utf-8')
assert 'LAN2 или LAN3' in src and 'EN8811H' in src and 'LAN4' in src and 'WAN' in src
print('PAYLOADREFRESH1_QA=PASS')
