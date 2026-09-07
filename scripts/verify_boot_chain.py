#!/usr/bin/env python3
from pathlib import Path
import hashlib, zlib
ROOT=Path(__file__).resolve().parents[1]
checks={
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-bl2.bin':'6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-update.fip':'597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-HWFIX3-u-boot.bin':'fe150f81b98a9ad02dbba6764722383652d5982056c429faad4c427ef8373548',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.bin':'921d53f396bec54613c792e6a31388e5a12a481fdcf963875dda2fad86499a67',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip':'ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-u-boot.bin':'06397f68ba876e01ba6a07ebbdbbcfac1e5341b9d82926fd6b4a54ae1bf7e552',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-u-boot.lzma':'648fe1e12616068a99305645b34bee74d669ee9219f51c26ddd0b6b5003e0b1f',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip':'548c446555231ee1b6ec4666000831226e0749c576d702c06dc5f501a6f510db',
}
for rel,expected in checks.items():
 p=ROOT/rel; actual=hashlib.sha256(p.read_bytes()).hexdigest(); assert actual==expected,(rel,actual,expected)
fip=ROOT/'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip'
assert f'{zlib.crc32(fip.read_bytes()) & 0xffffffff:08x}' == 'f85beabc'
source=ROOT/'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst'
assert hashlib.sha256(source.read_bytes()).hexdigest() == '57736bb74e2efd198e56e687dba50b945c160ada8ee9a3f25e3534842aa7f8c3'
print('BOOT_CHAIN_IDENTITY_QA=PASS production=alpha5-UBIUX1 historical_alpha3_alpha4=retained')
