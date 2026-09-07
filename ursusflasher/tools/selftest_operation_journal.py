#!/usr/bin/env python3
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'data'))
import operation_journal as j
with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    rec=j.prepare(write_class='UPSTREAM_SYSUPGRADE', candidate_sha256='aa'*32,
                  expected_artifact_identity={'build':'test'}, directory=root)
    oid=rec['operation_id']
    assert j.load(oid,root)['transaction_state']=='NOT_STARTED'
    assert len(j.list_unclosed(root))==1
    j.update(oid,directory=root,transaction_state='IN_PROGRESS')
    assert j.load(oid,root)['transaction_state']=='IN_PROGRESS'
    abandoned, _=j.abandon_on_proven_mismatch(oid, {'factory_mac':'00:11:22:33:44:55'}, directory=root)
    assert abandoned is False  # no target binding is not evidence of mismatch
    j.update(oid,directory=root,target_device_binding={'factory_mac':'AA:BB:CC:DD:EE:FF'})
    # Extra observed facts are not a mismatch when the shared authoritative fact matches.
    abandoned, _=j.abandon_on_proven_mismatch(oid, {'factory_mac':'AA:BB:CC:DD:EE:FF','serial_number':'NBEL12345678'}, directory=root)
    assert abandoned is False
    # No shared facts is unresolved, not proof of another device.
    abandoned, _=j.abandon_on_proven_mismatch(oid, {'serial_number':'NBEL12345678'}, directory=root)
    assert abandoned is False
    abandoned, rec2=j.abandon_on_proven_mismatch(oid, {'factory_mac':'00:11:22:33:44:55'}, directory=root)
    assert abandoned is True and rec2['record_state']=='ABANDONED'
    assert not list(root.glob('*.tmp'))
print('OPERATION_JOURNAL_QA=PASS')
