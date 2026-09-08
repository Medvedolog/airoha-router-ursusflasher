#!/usr/bin/env python3
from pathlib import Path
import hashlib, json
HERE=Path(__file__).resolve()
if (HERE.parents[1]/'data').is_dir():
    ROOT=HERE.parents[1]; DATA=ROOT/'data'; PAY=DATA/'payloads/md/ursusboot'; REPO=None
else:
    REPO=HERE.parents[2]; ROOT=REPO; DATA=REPO/'config'; PAY=REPO/'payloads/md/ursusboot'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    m=json.loads((DATA/'MANIFEST.json').read_text(encoding='utf-8'))
    c=m['ursusboot']['alpha5_test60_candidate']
    assert m['version'].startswith('0.2.61-md-alpha5-test61-safetyreg1-')
    assert c['version']=='0.1.0-alpha5-UBIUX1-TEST60'
    assert c['raw_bl33_size']==860176 and c['lzma_size']==291237 and c['fip_size']==503808
    assert c['raw_bl33_sha256']=='4679214615c5b53d67173a31ff9203b834a880e9b1f407b10fcc9cda8e2d32d1'
    assert c['lzma_sha256']=='335d92d42b63677e2d471c675cdab3867a062380919a207e407c8b074df168a9'
    assert c['fip_sha256']=='c0e88d734a33a72ef0ca002860eaf7ff6c7fa7cc856de3f781371259d013d9bb'
    assert c['size_delta_from_test59']['nt_fw_margin_bytes']==36443
    for n,key in [
        ('ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip','fip_sha256'),
        ('ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-u-boot.bin','raw_bl33_sha256'),
        ('ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-u-boot.lzma','lzma_sha256')]:
        assert sha(PAY/n)==c[key]
    if REPO is not None:
        cfg=(REPO/'ursusboot/configs/u-boot.TEST60.full.config').read_text()
        for sym in ('CONFIG_CMD_UBIFS','CONFIG_CMD_PXE','CONFIG_BOOTMETH_EXTLINUX','CONFIG_BOOTMETH_EXTLINUX_PXE','CONFIG_PXE_UTILS'):
            assert f'# {sym} is not set' in cfg, sym
        for sym in ('CONFIG_CMD_UBI=y','CONFIG_MTD_UBI=y','CONFIG_CMD_TFTPBOOT=y','CONFIG_CMD_WGET=y'):
            assert sym in cfg, sym
        patch=(REPO/'ursusboot/patches/170-test60-configtrim1.patch').read_text()
        assert 'TEST59' in patch and 'TEST60' in patch
        src=REPO/c['source_archive']; assert src.is_file() and sha(src)==c['source_archive_sha256']
    print('TEST60_SELFTEST=PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
