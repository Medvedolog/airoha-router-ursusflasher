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
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.bin':'43296d98686ada9e4e13c5a5a49430372abf45e9bd0fc8eae837920e8ba5224d',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.lzma':'bec245ab0b10e3fffcc2f0a482c2c3b97b03577b4a03c436857243cd68ff9d29',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip':'3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-u-boot.bin':'4679214615c5b53d67173a31ff9203b834a880e9b1f407b10fcc9cda8e2d32d1',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-u-boot.lzma':'335d92d42b63677e2d471c675cdab3867a062380919a207e407c8b074df168a9',
 'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip':'c0e88d734a33a72ef0ca002860eaf7ff6c7fa7cc856de3f781371259d013d9bb',
}
for rel,expected in checks.items():
 p=ROOT/rel; actual=hashlib.sha256(p.read_bytes()).hexdigest(); assert actual==expected,(rel,actual,expected)
fip=ROOT/'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip'
assert f'{zlib.crc32(fip.read_bytes()) & 0xffffffff:08x}' == 'c1edda32'
source=ROOT/'ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst'
assert hashlib.sha256(source.read_bytes()).hexdigest() == '57736bb74e2efd198e56e687dba50b945c160ada8ee9a3f25e3534842aa7f8c3'
print('BOOT_CHAIN_IDENTITY_QA=PASS public_test=alpha5-UBIUX1-TEST61 historical_alpha3_alpha4_alpha5=retained')
