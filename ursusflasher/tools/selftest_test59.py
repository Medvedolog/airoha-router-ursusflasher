#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, re
HERE=Path(__file__).resolve()
if (HERE.parents[1]/'data').is_dir():
    ROOT=HERE.parents[1]
    DATA=ROOT/'data'
    PAY=DATA/'payloads/md/ursusboot'
    REPO=None
else:
    REPO=HERE.parents[2]
    ROOT=REPO
    DATA=REPO/'config'
    PAY=REPO/'payloads/md/ursusboot'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    m=json.loads((DATA/'MANIFEST.json').read_text(encoding='utf-8'))
    c=m['ursusboot']['alpha5_test59_candidate']
    assert c['version']=='0.1.0-alpha5-UBIUX1-TEST59'
    assert c['raw_bl33_size']==956088 and c['lzma_size']==327650 and c['fip_size']==503808
    assert c['raw_bl33_sha256']=='e2e98b1da4f757065346b05aa0c004fe359e687d99209a4601fed0bf90d166ab'
    assert c['lzma_sha256']=='1e729eee0daca21fdf77a4ac9dab57566351768a77e8712beb7f55e2b4038967'
    assert c['fip_sha256']=='e6fef3f64fe119994704812a6f2f0138bacfdf34705e5e8ed4933647b540e1b8'
    assert sha(PAY/'ursusboot-md-0.1.0-alpha5-UBIUX1-TEST59-update.fip')==c['fip_sha256']
    assert sha(PAY/'ursusboot-md-0.1.0-alpha5-UBIUX1-TEST59-u-boot.bin')==c['raw_bl33_sha256']
    assert sha(PAY/'ursusboot-md-0.1.0-alpha5-UBIUX1-TEST59-u-boot.lzma')==c['lzma_sha256']
    assert 'physical FIP end=0x7b800' in c['compression']
    if REPO is not None:
        patch=(REPO/'ursusboot/patches/160-test59-corrective.patch').read_text(encoding='utf-8')
        for x in ('opActive','ursus_ubi_update_complete()','preserve_headroom','projected_free','URSUS_UBI_UPDATE_FAILED stage=%s ret=%d reboot=MANUAL'):
            assert x in patch, x
        additions='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        assert not re.search(r'[А-Яа-яЁё]', additions)
    print('TEST59_SELFTEST=PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
