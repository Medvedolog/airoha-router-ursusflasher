#!/usr/bin/env python3
from pathlib import Path
import inspect, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data'))
import device_state as ds
import proven_backend as pb

calls=[]
orig=pb.ssh_run
sample='''__URSUS_STATE__\nBOARD=nokia,xg-040g-md-ubi\nMODEL=Nokia XG-040G-MD (UBI)\nMACHINE=Nokia XG-040G-MD (UBI)\nMTD=dev: size erasesize name;mtd0: 10000000 00020000 "all_flash";mtd1: 00020000 00020000 "bl2";mtd2: 0ffe0000 00020000 "ubi";\nFIPVOL=fip\nROOTMOUNT=overlayfs:/overlay|overlay|rw\nROMMOUNT=/dev/root|squashfs|ro\nOVERLAYMOUNT=/dev/ubi0_6|ubifs|rw\nRELEASE=SNAPSHOT/test\n'''
def fake(host, command, **kwargs):
    calls.append(kwargs)
    return 0, sample
pb.ssh_run=fake
try:
    st=ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_openwrt_ssh('192.168.1.1', st, interactive=False)
    assert calls[-1].get('batch_mode') is True
    st2=ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_openwrt_ssh('192.168.1.1', st2, interactive=True)
    assert calls[-1].get('batch_mode') is False
    assert calls[-1].get('password_prompts') == 3
    assert st2.current_layout == 'OPENWRT_UBI'
    assert st2.execution_environment == ds.EXEC_PERSISTENT_ROOT
finally:
    pb.ssh_run=orig

profile=pb.backup_recovery_profile_md()
assert profile['model']=='Nokia XG-040G-MD'
assert profile['soc']=='AN7581'
assert Path(profile['preloader']).is_file()
assert Path(profile['fip']).is_file()
assert Path(profile['backup_initramfs']).is_file()

wizard=inspect.getsource(pb.bootrom_backup_wizard)
assert 'verify_kit()' not in wizard
assert 'backup_recovery_dependency_preflight()' in wizard
assert 'RAW_NAND_SPAN' in wizard
assert '_finalize_raw_bootrom_backup' in wizard
preflight=inspect.getsource(pb.backup_recovery_dependency_preflight)
assert 'transition-bundle.bin' not in preflight
assert 'verify_kit' not in preflight

expert=(ROOT/'data/expert.py').read_text(encoding='utf-8')
assert 'full_backup_readonly(_interactive_diagnostic_state(state))' in expert
assert 'flash_diagnostics(_interactive_diagnostic_state(state))' in expert
assert 'probe_device_state(state.host, interactive_ssh=True)' in expert
assert 'verify_raw_bootrom_backup(path)' in expert
print('STATEUI8_DIAGAUTH1_BACKUPRAW1_QA=PASS')
