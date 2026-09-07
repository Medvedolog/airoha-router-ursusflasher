#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import device_state as ds

# Pure state/applicability contract, no network dependency.
complete=ds.DeviceState(probe_status=ds.PROBE_COMPLETE, model='Nokia XG-040G-MD', soc='Airoha AN7581', current_system='RECOVERY', current_layout='OPENWRT_UBI', bootloader='URSUSBOOT', backup_state='VERIFIED')
a=ds.action_applicability(complete)
assert len(a)==12
assert a[1].enabled and a[1].write_capable
assert a[4].enabled and a[4].write_capable
assert not a[6].enabled and 'не реализовано' in a[6].reason
assert a[7].enabled and not a[7].write_capable
assert a[8].enabled and a[8].reason==''
assert a[10].enabled and not a[10].write_capable

partial=ds.DeviceState(probe_status=ds.PROBE_PARTIAL, current_system='UNKNOWN')
ap=ds.action_applicability(partial)
for n,x in ap.items():
    if x.write_capable and x.key!='restore_nokia':
        assert not x.enabled, (n,x)
        assert x.reason=='состояние определено не полностью'
assert ap[7].enabled and ap[10].enabled and ap[11].enabled and ap[12].enabled

failed=ds.DeviceState(probe_status=ds.PROBE_FAILED)
af=ds.action_applicability(failed)
assert not af[1].enabled and af[7].enabled

caps=json.loads((D/'data/FIRMWARE_CAPABILITIES.json').read_text(encoding='utf-8'))
assert caps['md']['GLOBAL_WRITE_STATE_UNKNOWN'].startswith('DEFERRED')
assert caps['ui_actions']['full_backup']['write_capable'] is False
print('DEVICESTATE_V529_QA=PASS')

# STATEUI2: completeness is monotonic; later success cannot promote an earlier failure.
mono=ds.DeviceState(probe_status=ds.PROBE_COMPLETE)
ds.degrade_probe_status(mono, ds.PROBE_PARTIAL, 'NETWORK_IDENTITY_AMBIGUOUS')
ds.degrade_probe_status(mono, ds.PROBE_COMPLETE)
assert mono.probe_status==ds.PROBE_PARTIAL
ds.degrade_probe_status(mono, ds.PROBE_FAILED, 'NO_NETWORK_ENDPOINT')
ds.degrade_probe_status(mono, ds.PROBE_PARTIAL)
assert mono.probe_status==ds.PROBE_FAILED

# Enabled validator uses note, never a denial reason.
no_local=ds.DeviceState(probe_status=ds.PROBE_COMPLETE, current_system='RECOVERY', bootloader='URSUSBOOT', backup_state='NOT_FOUND')
av=ds.action_applicability(no_local)[8]
assert av.enabled and av.reason=='' and 'вручную' in av.note

# Custom image limitation belongs to this release, not to device correctness.
live=ds.DeviceState(probe_status=ds.PROBE_COMPLETE, current_system='OPENWRT_UBI', execution_environment=ds.EXEC_PERSISTENT_ROOT, bootloader='URSUSBOOT')
ac=ds.action_applicability(live)[3]
assert not ac.enabled and ac.reason=='в этой версии доступно только из режима восстановления'
print('STATEUI2_APPLICABILITY_QA=PASS')
