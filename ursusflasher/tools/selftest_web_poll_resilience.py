#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data'))
import ursus_web_client as uw

orig_status = uw.status
orig_sleep = uw.time.sleep
try:
    seq = [
        TimeoutError('timed out'),
        ConnectionResetError('connection reset'),
        {
            'operation_active': True,
            'operation_complete': False,
            'operation_failed': False,
            'operation_stage': 'FORMAT_UBI',
            'operation_percent': 25,
            'operation_detail': 'Format NAND region for UBI',
        },
        {
            'operation_active': False,
            'operation_complete': True,
            'operation_failed': False,
            'operation_stage': 'COMPLETE',
            'operation_percent': 100,
            'operation_detail': 'Migration complete',
        },
    ]
    def fake_status(_host='192.168.1.1'):
        item = seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    uw.status = fake_status
    uw.time.sleep = lambda _s: None
    out = uw._poll('192.168.1.1', bootloader=False, timeout=5.0)
    assert out['operation_complete'] is True
    assert out['operation_stage'] == 'COMPLETE'

    def protocol_error(_host='192.168.1.1'):
        raise uw.UrsusWebError('protocol mismatch')
    uw.status = protocol_error
    try:
        uw._poll('192.168.1.1', bootloader=False, timeout=1.0)
    except uw.UrsusWebError as exc:
        assert 'protocol mismatch' in str(exc)
    else:
        raise AssertionError('UrsusWebError must not be swallowed as a transport retry')
finally:
    uw.status = orig_status
    uw.time.sleep = orig_sleep
print('WEB_POLL_TRANSIENT_TIMEOUT_QA=PASS')
