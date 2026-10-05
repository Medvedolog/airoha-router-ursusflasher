#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data'))
import ursus_web_client as uw

orig_status = uw.status
orig_text = uw._text
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
    # _poll now consults /api/log as an independent evidence channel while
    # /api/status is unavailable.  Keep this first case strictly about status
    # retry behavior and never touch the real network from the selftest.
    uw._text = lambda _host, _path, timeout=5: ''
    uw.time.sleep = lambda _s: None
    out = uw._poll('192.168.1.1', bootloader=False, timeout=5.0)
    assert out['operation_complete'] is True
    assert out['operation_stage'] == 'COMPLETE'

    # A temporary UrsusWebError from /api/status is also an API-surface loss
    # during synchronous NAND work and is retried until the operation deadline.
    def protocol_error(_host='192.168.1.1'):
        raise uw.UrsusWebError('protocol mismatch')
    uw.status = protocol_error
    try:
        uw._poll('192.168.1.1', bootloader=False, timeout=0.02)
    except uw.UrsusWebError as exc:
        assert 'timed out waiting for UrsusBoot flash operation' in str(exc)
    else:
        raise AssertionError('persistent status/API loss must end at the operation deadline')

    # The device log is accepted only for an explicit firmware-side terminal
    # marker, so a starved /api/status does not create a false failure.
    uw.status = lambda _host='192.168.1.1': (_ for _ in ()).throw(TimeoutError('busy'))
    uw._text = lambda _host, _path, timeout=5: '... URSUS_UBI_MIGRATION_COMPLETE ...'
    out = uw._poll('192.168.1.1', bootloader=False, timeout=1.0)
    assert out['operation_complete'] is True
    assert out['operation_stage'] == 'COMPLETE'
    assert out['status_source'] == 'api-log-fallback'
finally:
    uw.status = orig_status
    uw._text = orig_text
    uw.time.sleep = orig_sleep
print('WEB_POLL_TRANSIENT_TIMEOUT_QA=PASS')
