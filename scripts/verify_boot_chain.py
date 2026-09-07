#!/usr/bin/env python3
from pathlib import Path
import hashlib, zlib
ROOT=Path(__file__).resolve().parents[1]
checks={
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-bl2.bin':'6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-update.fip':'597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-HWFIX3-u-boot.bin':'fe150f81b98a9ad02dbba6764722383652d5982056c429faad4c427ef8373548',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.bin':'921d53f396bec54613c792e6a31388e5a12a481fdcf963875dda2fad86499a67',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-u-boot.bin':'a41a81a011e19d1498d5ff0773dfd6bf9bd4c56beb3e7a46ce4622a643a30703',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-u-boot.lzma':'450add116075477311cbf794da2541ddbdb33fb0c9eade39a47cf8d1fc0a81b7',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip':'ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600',
}
for rel,expected in checks.items():
 p=ROOT/rel; actual=hashlib.sha256(p.read_bytes()).hexdigest(); assert actual==expected,(rel,actual,expected)
fip=ROOT/'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip'
assert f'{zlib.crc32(fip.read_bytes()) & 0xffffffff:08x}' == '27ee17f0'
print('BOOT_CHAIN_IDENTITY_QA=PASS')
