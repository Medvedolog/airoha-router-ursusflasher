#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse
from pathlib import Path

import ui_terms as terms

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent if (HERE.parent.parent / "config").is_dir() else HERE.parent
DIAG_ROOT = KIT / "work" / "diagnostics"
CHUNK = 0x10000
UPLOAD_RETRIES = 2
UPLOAD_RECONNECT_GRACE = 75.0


def _session_log(line: str) -> None:
    try:
        from proven_backend import _write_session_only
        _write_session_only(line)
    except Exception:
        pass

# alpha5-UBIUX1 owns fresh rootfs_data sizing in UrsusBoot itself. Migration
# and explicit settings reset keep 16 free PEBs and persist rootfs_data_max so
# later OpenWrt sysupgrade recreates the same overlay size. The legacy helper
# below is retained only for backward compatibility with alpha4 Recovery.
ROOTFS_MIGRATION_LEBS = 1693
ROOTFS_KEEP_FREE_PEBS = 16
ROOTFS_LEGACY_REQUEST = 0x0CD00000


class UrsusWebError(RuntimeError):
    pass


def _request(host: str, method: str, path: str, *, headers: dict[str, str] | None = None,
             body: bytes | None = None, timeout: float = 30.0) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, 80, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        data = r.read()
        h = {k.lower(): v for k, v in r.getheaders()}
        return r.status, h, data
    finally:
        conn.close()


def _json(host: str, method: str, path: str, *, headers: dict[str, str] | None = None,
          body: bytes | None = None, timeout: float = 30.0) -> dict:
    status, _h, data = _request(host, method, path, headers=headers, body=body, timeout=timeout)
    try:
        parsed = json.loads(data.decode('utf-8', 'replace')) if data else {}
    except json.JSONDecodeError as exc:
        raise UrsusWebError(f'{method} {path}: HTTP {status}, invalid JSON: {data[:300]!r}') from exc
    if not 200 <= status < 300:
        reason = parsed.get('reason') or parsed.get('result') or data.decode('utf-8', 'replace')
        raise UrsusWebError(f'{method} {path}: HTTP {status}: {reason}')
    return parsed


def status(host: str = '192.168.1.1') -> dict:
    st = _json(host, 'GET', '/api/status', timeout=5)
    if st.get('product') != 'UrsusBoot':
        raise UrsusWebError(f'http://{host}/api/status did not identify UrsusBoot: {st.get("product")!r}')
    return st


def console(host: str, command: str, *, timeout: float = 360.0) -> str:
    encoded = urllib.parse.quote(command, safe='')
    code, _h, data = _request(host, 'POST', '/api/console', headers={'X-Ursus-Command': encoded}, timeout=timeout)
    text = data.decode('utf-8', 'replace')
    if not 200 <= code < 300:
        raise UrsusWebError(f'console command failed HTTP {code}: {text[-1200:]}')
    return text


def _text(host: str, path: str, *, timeout: float = 10.0) -> str:
    code, _h, data = _request(host, 'GET', path, timeout=timeout)
    text = data.decode('utf-8', 'replace')
    if not 200 <= code < 300:
        raise UrsusWebError(f'GET {path}: HTTP {code}: {text[-1200:]}')
    return text


def _diag_rel(path: Path) -> str:
    try:
        return path.relative_to(KIT).as_posix()
    except Exception:
        return str(path)


def _diag_write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def begin_diagnostics(host: str, operation: str, *, status_snapshot: dict | None = None) -> Path | None:
    """Create a persistent read-only diagnostic bundle before a write-capable operation."""
    stamp = time.strftime('%Y%m%d-%H%M%S')
    safe_op = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in operation)[:48] or 'operation'
    out = DIAG_ROOT / f'{stamp}-{safe_op}'
    try:
        # Same-second retries must not overwrite the previous forensic bundle.
        base = out
        suffix = 1
        while out.exists():
            out = Path(str(base) + f'-{suffix:02d}')
            suffix += 1
        out.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        _session_log(f'[DIAGCAP2] mkdir failed operation={operation}: {exc!r}')
        return None

    meta = {
        'host': host,
        'operation': operation,
        'started_at': stamp,
        'result': 'IN_PROGRESS',
        'transaction_state': 'NOT_STARTED',
        'files': {},
        'errors': {},
    }
    st = status_snapshot
    if st is None:
        try:
            st = status(host)
        except Exception as exc:
            meta['errors']['status-before'] = repr(exc)
    if st is not None:
        _diag_write_json(out / 'status-before.json', st)
        meta['files']['status-before'] = 'status-before.json'
        _session_log('[URSUS_STATUS_BEFORE] ' + json.dumps(st, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    try:
        text = _text(host, '/api/operation-log', timeout=8)
        (out / 'operation-log-before.txt').write_text(text, encoding='utf-8', errors='replace')
        meta['files']['operation-log-before'] = 'operation-log-before.txt'
    except Exception as exc:
        meta['errors']['operation-log-before'] = repr(exc)
    _diag_write_json(out / 'operation.json', meta)
    _session_log(f'[DIAGCAP2_BEGIN] operation={operation} bundle={_diag_rel(out)}')
    return out


def finish_diagnostics(bundle: Path | None, host: str, operation: str, result: str,
                       *, status_snapshot: dict | None = None, error: str | None = None,
                       transaction_state: str | None = None) -> Path | None:
    """Complete a diagnostic bundle on both success and failure.

    The bundle is deliberately separate from LATEST.log.  LATEST stays readable,
    while session-*.log receives the raw device JSON, operation log and console
    snapshot for post-mortem work.
    """
    if bundle is None:
        bundle = begin_diagnostics(host, operation, status_snapshot=status_snapshot)
        if bundle is None:
            return None
    op_path = bundle / 'operation.json'
    try:
        meta = json.loads(op_path.read_text(encoding='utf-8')) if op_path.is_file() else {}
    except Exception:
        meta = {}
    meta.setdefault('host', host)
    meta.setdefault('operation', operation)
    meta.setdefault('files', {})
    meta.setdefault('errors', {})
    meta['result'] = result
    meta['finished_at'] = time.strftime('%Y%m%d-%H%M%S')
    if error:
        meta['error'] = error
    if transaction_state is not None:
        meta['transaction_state'] = transaction_state

    st = status_snapshot
    if st is None:
        try:
            st = status(host)
        except Exception as exc:
            meta['errors']['status-after'] = repr(exc)
    if st is not None:
        _diag_write_json(bundle / 'status-after.json', st)
        meta['files']['status-after'] = 'status-after.json'
        meta['stage'] = st.get('operation_stage') or st.get('bootloader_update_stage')
        if transaction_state is None:
            meta['transaction_state'] = st.get('operation_transaction_state') or meta.get('transaction_state')
        meta['error_code'] = st.get('operation_error_code')
        meta['failed_at_stage'] = st.get('operation_failed_at_stage')
        meta['last_success_stage'] = st.get('operation_last_success_stage')
        _session_log('[URSUS_STATUS_AFTER] ' + json.dumps(st, ensure_ascii=False, sort_keys=True, separators=(',', ':')))

    for endpoint, name, marker in (
        ('/api/operation-log', 'operation-log.txt', 'URSUS_OPERATION_LOG'),
        ('/api/log', 'web-log.txt', 'URSUS_WEB_LOG'),
    ):
        try:
            text = _text(host, endpoint, timeout=8)
            (bundle / name).write_text(text, encoding='utf-8', errors='replace')
            meta['files'][endpoint] = name
            _session_log(f'[{marker}]\n{text}')
        except Exception as exc:
            meta['errors'][endpoint] = repr(exc)

    safe_commands = ('version', 'mtd list', 'ubi info', 'ubi info l', 'printenv')
    console_parts: list[str] = []
    for command in safe_commands:
        try:
            text = console(host, command, timeout=20)
            console_parts.append(f'===== $ {command} =====\n{text.rstrip()}\n')
        except Exception as exc:
            console_parts.append(f'===== $ {command} =====\nERROR: {exc!r}\n')
            meta['errors'][f'console:{command}'] = repr(exc)
    console_text = '\n'.join(console_parts)
    (bundle / 'console.txt').write_text(console_text, encoding='utf-8', errors='replace')
    meta['files']['console'] = 'console.txt'
    _session_log('[URSUS_CONSOLE_SNAPSHOT]\n' + console_text)

    _diag_write_json(op_path, meta)
    _session_log(f'[DIAGCAP2_END] operation={operation} result={result} bundle={_diag_rel(bundle)}')
    print(terms.tr(
        f'[ДИАГНОСТИКА] Полный снимок устройства: {_diag_rel(bundle)}',
        f'[DIAGNOSTICS] Full device snapshot: {_diag_rel(bundle)}'))
    return bundle


def collect_diagnostics(host: str, reason: str, *, status_snapshot: dict | None = None) -> Path | None:
    """Backward-compatible one-shot capture for callers outside transaction wrappers."""
    bundle = begin_diagnostics(host, reason, status_snapshot=status_snapshot)
    return finish_diagnostics(bundle, host, reason, 'SNAPSHOT', status_snapshot=status_snapshot)

def _upload_state(kind: str, st: dict) -> tuple[str, int, int]:
    prefix = {
        'firmware': 'firmware',
        'fip': 'ursus_fip',
        'preloader': 'ubi_preloader',
        'initramfs': 'initramfs',
    }[kind]
    return (str(st.get(prefix + '_generation') or ''),
            int(st.get(prefix + '_upload_received') or 0),
            int(st.get(prefix + '_upload_total') or 0))

def _upload_final_from_status(kind: str, st: dict, gen: str, total: int) -> dict | None:
    sg, received, declared = _upload_state(kind, st)
    if sg != gen or received != total or declared != total:
        return None
    valid = {
        'firmware': st.get('last_validation_result') == 'VALID',
        'fip': bool(st.get('ursus_fip_valid')),
        'preloader': bool(st.get('ubi_preloader_valid')) and bool(st.get('ubi_bl2_candidate_valid')),
        'initramfs': bool(st.get('expert_valid')),
    }[kind]
    return {
        'result': 'VALID' if valid else 'REJECTED',
        'generation': gen, 'declared_size': total, 'received': total,
        'reason_class': st.get('last_validation_class') or st.get('reason_class'),
        'reason': st.get('last_validation_reason') or st.get('reason'),
    }


def upload(host: str, path: Path, kind: str, *, progress=True) -> dict:
    """Upload to RAM only; a transport failure never arms a flash operation.

    TEST61 deliberately does not spin through multiple fresh upload sessions by
    itself. After a link loss it gives the existing generation a long grace
    period to reappear and reconciles the acknowledged offset. Only if that RAM
    upload session is gone does it ask the operator whether to start a new
    transfer from byte zero.
    """
    endpoints = {
        'firmware': ('/api/firmware-begin', '/api/firmware-chunk'),
        'fip': ('/api/ursus-fip-begin', '/api/ursus-fip-chunk'),
        'preloader': ('/api/ubi-preloader-begin', '/api/ubi-preloader-chunk'),
        'initramfs': ('/api/initramfs-begin', '/api/initramfs-chunk'),
    }
    if kind not in endpoints:
        raise ValueError(kind)
    if not path.is_file() or path.stat().st_size <= 0:
        raise UrsusWebError(f'file missing or empty: {path}')
    total = path.stat().st_size
    gen = f'host-{int(time.time()*1000):x}'
    begin, chunk = endpoints[kind]
    base = {
        'X-Ursus-Generation': gen,
        'X-Ursus-Total': str(total),
        'X-Ursus-Filename': urllib.parse.quote(path.name, safe=''),
    }

    def ask_restart(reason: str) -> dict:
        _session_log(f'[WEB_UPLOAD_SESSION_LOST] kind={kind} generation={gen} reason={reason}')
        print()
        print(terms.tr(
            '[ВНИМАНИЕ] Передача была прервана. Запись во flash не запускалась.',
            '[WARNING] Transfer was interrupted. No flash write was started.',
        ))
        answer = input(terms.tr(
            'Повторить передачу файла с начала? [y/N]: ',
            'Restart this file transfer from the beginning? [y/N]: ',
        )).strip().lower()
        if answer in ('y', 'yes', 'д', 'да'):
            _session_log(f'[WEB_UPLOAD_MANUAL_RESTART] kind={kind} old_generation={gen}')
            return upload(host, path, kind, progress=progress)
        raise UrsusWebError(f'upload stopped by operator after transport loss at generation={gen}')

    try:
        first = _json(host, 'POST', begin, headers=base, timeout=30)
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        return ask_restart(f'begin:{type(exc).__name__}:{exc}')
    off0 = int(first.get('received', -1))
    if first.get('generation') != gen or int(first.get('declared_size', -1)) != total or off0 != 0:
        raise UrsusWebError(f'begin ACK mismatch: {first}')

    last = first
    off = 0
    with path.open('rb') as f:
        while off < total:
            f.seek(off)
            data = f.read(min(CHUNK, total - off))
            if not data:
                raise UrsusWebError(f'unexpected EOF at {off}/{total}')
            headers = {
                'Content-Type': 'application/octet-stream',
                'Content-Length': str(len(data)),
                'X-Ursus-Generation': gen,
                'X-Ursus-Offset': str(off),
                'X-Ursus-Total': str(total),
            }
            try:
                last = _json(host, 'POST', chunk, headers=headers, body=data, timeout=90)
            except (TimeoutError, OSError, http.client.HTTPException, UrsusWebError) as exc:
                if isinstance(exc, UrsusWebError) and 'HTTP 409' not in str(exc):
                    raise
                _session_log(f'[WEB_UPLOAD_LINK_LOSS] kind={kind} generation={gen} offset={off} error={type(exc).__name__}:{exc}')
                deadline = time.time() + UPLOAD_RECONNECT_GRACE
                reconciled = False
                session_seen = False
                while time.time() < deadline:
                    try:
                        st = status(host)
                        sg, received, declared = _upload_state(kind, st)
                    except Exception as status_exc:
                        _session_log(f'[WEB_UPLOAD_RECONCILE_WAIT] kind={kind} offset={off} error={type(status_exc).__name__}:{status_exc}')
                        time.sleep(2.0)
                        continue
                    if sg != gen or declared != total:
                        _session_log(f'[WEB_UPLOAD_RECONCILE_OTHER_SESSION] kind={kind} expected_generation={gen} seen_generation={sg} declared={declared}')
                        time.sleep(2.0)
                        continue
                    session_seen = True
                    if received == off:
                        _session_log(f'[WEB_UPLOAD_RESUME] kind={kind} generation={gen} offset={off} action=resend-current-chunk')
                        reconciled = True
                        break
                    if received == off + len(data):
                        last = _upload_final_from_status(kind, st, gen, total) or {
                            'result': 'CHUNK_OK', 'generation': gen,
                            'declared_size': total, 'received': received,
                        }
                        _session_log(f'[WEB_UPLOAD_RESUME] kind={kind} generation={gen} offset={off} action=chunk-already-acked')
                        reconciled = True
                        break
                    if received == total:
                        final = _upload_final_from_status(kind, st, gen, total)
                        if final is not None:
                            last = final
                            reconciled = True
                            break
                    raise UrsusWebError(
                        f'upload reconcile mismatch: generation={sg!r} received={received} '
                        f'expected={off} or {off + len(data)} total={declared}'
                    )
                if not reconciled:
                    return ask_restart('reconnect-grace-expired' if not session_seen else 'session-not-reconcilable')
                # If the current chunk was not committed, resend it once after
                # the recovered session becomes reachable.
                if int(last.get('received', off)) == off:
                    try:
                        last = _json(host, 'POST', chunk, headers=headers, body=data, timeout=90)
                    except (TimeoutError, OSError, http.client.HTTPException, UrsusWebError) as retry_exc:
                        return ask_restart(f'resend-after-grace:{type(retry_exc).__name__}:{retry_exc}')

            received = int(last.get('received', -1))
            declared = int(last.get('declared_size', -1))
            if last.get('generation') != gen or declared != total or not (off < received <= total):
                raise UrsusWebError(f'chunk ACK mismatch: {last}')
            off = received
            if progress:
                print(f'\r{terms.tr("[ПЕРЕДАЧА]", "[TRANSFER]")} {path.name}: {off}/{total} ({off*100//total}%)', end='', flush=True)
    if progress:
        print()
    return last

def _poll(host: str, *, bootloader: bool, timeout: float = 420.0) -> dict:
    deadline = time.time() + timeout
    last_key = None
    transport_failures = 0
    last_transport_notice = 0.0
    while time.time() < deadline:
        try:
            st = status(host)
            transport_failures = 0
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            # Destructive UBI/MTD stages execute synchronously inside U-Boot and may
            # temporarily starve lwIP/HTTP while NAND erase/write/readback is active.
            # A single status socket timeout is therefore transport silence, not an
            # operation failure. Keep polling until the global operation deadline.
            transport_failures += 1
            now = time.time()
            try:
                _session_log(f'[WEB_STATUS_RETRY] count={transport_failures} error={type(exc).__name__}:{exc}')
            except Exception:
                pass
            if now - last_transport_notice >= 5.0:
                print(terms.tr(
                    '[ЖДУ] UrsusBoot занят операцией с NAND; Web может временно не отвечать. Продолжаю ждать, операция не считается ошибкой.',
                    '[WAIT] UrsusBoot is busy with NAND; Web may be temporarily unresponsive. Waiting continues and this is not treated as an operation failure.'
                ))
                last_transport_notice = now
            time.sleep(1.0)
            continue
        if bootloader:
            active = bool(st.get('bootloader_update_active'))
            complete = bool(st.get('bootloader_update_complete'))
            failed = bool(st.get('bootloader_update_failed'))
            stage = st.get('bootloader_update_stage')
            pct = st.get('bootloader_update_percent')
            detail = st.get('bootloader_update_detail')
        else:
            active = bool(st.get('operation_active'))
            complete = bool(st.get('operation_complete'))
            failed = bool(st.get('operation_failed'))
            stage = st.get('operation_stage')
            pct = st.get('operation_percent')
            detail = st.get('operation_detail')
        key = (stage, pct, detail, active, complete, failed)
        if key != last_key:
            try:
                _session_log(f'[WEB_STATUS_RAW] stage={stage!r} percent={pct!r} detail={detail!r} active={active} complete={complete} failed={failed}')
                _session_log('[URSUS_STATUS_FULL] ' + json.dumps(st, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
            except Exception:
                pass
            shown_pct = '?' if pct is None else pct
            print(terms.tr(f'[ШАГ] Операция UrsusBoot: {shown_pct}%', f'[STEP] UrsusBoot operation: {shown_pct}%'))
            last_key = key
        if failed:
            code = st.get('operation_error_code') or st.get('bootloader_update_error') or st.get('operation_error')
            failed_at = st.get('operation_failed_at_stage') or stage
            tx = st.get('operation_transaction_state') or 'UNKNOWN'
            raise UrsusWebError(f'operation failed: {stage}: {detail}; code={code} failed_at={failed_at} transaction={tx}')
        if complete:
            return st
        time.sleep(0.6 if active else 1.0)
    raise UrsusWebError('timed out waiting for UrsusBoot flash operation')


def update_bootloader(host: str, fip: Path, *, confirm=True) -> dict:
    operation = 'update-ursusboot'
    before = status(host)
    diag = begin_diagnostics(host, operation, status_snapshot=before)
    operation_started = False
    try:
        st = before
        print(terms.tr(f"[ИНФО] UrsusBoot {st.get('version')}; разметка: {terms.layout_label(st.get('current_layout'))}",
                       f"[INFO] UrsusBoot {st.get('version')}; layout: {terms.layout_label(st.get('current_layout'))}"))
        ack = upload(host, fip, 'fip')
        if ack.get('result') != 'VALID':
            raise UrsusWebError(f'FIP rejected: {ack}')
        print(terms.tr('[ГОТОВО] FIP UrsusBoot проверен загрузчиком.', '[READY] UrsusBoot FIP validated by the bootloader.'))
        if confirm:
            answer = input(terms.tr('Записать FIP UrsusBoot? [y/N]: ', 'Write the UrsusBoot FIP? [y/N]: ')).strip().lower()
            if answer not in ('y', 'yes', 'д', 'да'):
                print(terms.tr('Запись отменена до изменения флеш-памяти.', 'Cancelled before flash write.'))
                st = status(host)
                finish_diagnostics(diag, host, operation, 'CANCELLED', status_snapshot=st)
                return st
        _json(host, 'POST', '/api/update-ursusboot', headers={'X-Ursus-Confirm': 'UPDATE-URSUSBOOT'}, timeout=20)
        operation_started = True
        st = _poll(host, bootloader=True)
        finish_diagnostics(diag, host, operation, 'SUCCESS', status_snapshot=st)
        return st
    except Exception as exc:
        finish_diagnostics(diag, host, operation, 'FAILED', error=repr(exc),
                           transaction_state=None if operation_started else 'NOT_STARTED')
        raise

def update_firmware(host: str, image: Path, *, confirm=True, preloader: Path | None = None, keep_settings: bool = True) -> dict:
    operation = 'update-openwrt'
    before = status(host)
    diag = begin_diagnostics(host, operation, status_snapshot=before)
    operation_started = False
    try:
        st0 = status(host)
        layout = st0.get('current_layout')
        print(terms.tr(f"[ИНФО] UrsusBoot {st0.get('version')}; разметка: {terms.layout_label(layout)}",
                       f"[INFO] UrsusBoot {st0.get('version')}; layout: {terms.layout_label(layout)}"))

        # STOCK and OPENWRT_STOCK_LAYOUT share the same physical migration contract.
        # Validate the transition BL2/preloader before any destructive conversion.
        if layout in ('STOCK', 'OPENWRT_STOCK_LAYOUT') and preloader is not None:
            pack = upload(host, preloader, 'preloader')
            if pack.get('result') != 'VALID':
                raise UrsusWebError(f'UBI preloader rejected: {pack}')
            print(terms.tr('[ГОТОВО] Preloader и кандидат BL2 для перехода на UBI проверены.', '[READY] The UBI transition preloader and 128 KiB BL2 candidate were validated.'))

        ack = upload(host, image, 'firmware')
        if ack.get('result') != 'VALID':
            raise UrsusWebError(f'firmware rejected: {ack}')
        st = status(host)
        image_type = st.get('image_type')

        if image_type == 'OPENWRT_UBI_SYSUPGRADE':
            if layout == 'OPENWRT_UBI':
                endpoint, phrase, header = '/api/install-ubi', 'FLASH', 'INSTALL-UBI'
                print(terms.tr('[ИНФО] Выбрано обновление OpenWrt в текущей разметке UBI с последующей сверкой записи.', '[INFO] Updating OpenWrt in the current UBI layout with post-write readback.'))
            elif layout in ('STOCK', 'OPENWRT_STOCK_LAYOUT'):
                if not st.get('ubi_migration_available'):
                    raise UrsusWebError(f'{layout} -> OPENWRT_UBI requires a validated transition preloader/BL2 candidate')
                endpoint, phrase, header = '/api/install-ubi', 'FLASH', 'INSTALL-UBI'
                if layout == 'STOCK':
                    print(terms.tr('[ИНФО] Выбран переход с заводской прошивки Nokia на OpenWrt UBI.', '[INFO] Migration from Nokia factory firmware to OpenWrt UBI selected.'))
                else:
                    print(terms.tr('[ИНФО] Выбран переход OpenWrt с заводской физической разметки на UBI через UrsusBoot Recovery.', '[INFO] Migration of stock-layout OpenWrt to UBI through UrsusBoot Recovery selected.'))
            else:
                raise UrsusWebError(f'unsupported current layout for UBI sysupgrade: {layout}')
        elif image_type == 'OPENWRT_NONUBI_SYSUPGRADE':
            if layout not in ('STOCK', 'OPENWRT_STOCK_LAYOUT'):
                raise UrsusWebError(f'one-way policy: non-UBI sysupgrade is forbidden on {layout}')
            if not st.get('stock_layout_install_available'):
                raise UrsusWebError('validated non-UBI sysupgrade is not available for current layout')
            endpoint, phrase, header = '/api/install-openwrt-stock-layout', 'FLASH', 'INSTALL-OPENWRT-STOCK-LAYOUT'
            print(terms.tr('[ИНФО] Выбрана установка или обновление OpenWrt в заводской разметке.', '[INFO] OpenWrt install/update in factory layout selected.'))
        else:
            raise UrsusWebError(f'unsupported Main-channel image class: {image_type}')

        if confirm:
            answer = input(terms.tr('Начать запись прошивки? [y/N]: ', 'Start writing the firmware? [y/N]: ')).strip().lower()
            if answer not in ('y', 'yes', 'д', 'да'):
                print(terms.tr('Запись отменена до изменения флеш-памяти.', 'Cancelled before flash write.'))
                finish_diagnostics(diag, host, operation, 'CANCELLED', status_snapshot=st)
                return st
        headers = {'X-Ursus-Confirm': header}
        if endpoint == '/api/install-ubi':
            effective_keep = keep_settings if layout == 'OPENWRT_UBI' else False
            headers['X-Ursus-Keep-Settings'] = '1' if effective_keep else '0'
        _json(host, 'POST', endpoint, headers=headers, timeout=20)
        operation_started = True
        st_result = _poll(host, bootloader=False)
        finish_diagnostics(diag, host, operation, 'SUCCESS', status_snapshot=st_result)
        return st_result
    except Exception as exc:
        finish_diagnostics(diag, host, operation, 'FAILED', error=repr(exc),
                           transaction_state=None if operation_started else 'NOT_STARTED')
        raise



def reset_openwrt_settings(host: str, *, confirm: bool = True) -> dict:
    """Reset only OpenWrt rootfs_data through UrsusBoot Recovery."""
    operation = 'reset-openwrt-settings'
    before = status(host)
    diag = begin_diagnostics(host, operation, status_snapshot=before)
    try:
        st = before
        layout = st.get('current_layout')
        if layout not in ('OPENWRT_UBI', 'OPENWRT_STOCK_LAYOUT'):
            raise UrsusWebError(f'OpenWrt settings reset is not applicable to {layout}')
        if confirm:
            answer = input(terms.tr(
                'Сбросить настройки OpenWrt (rootfs_data), не меняя прошивку? [y/N]: ',
                'Reset OpenWrt settings (rootfs_data) without replacing firmware? [y/N]: '
            )).strip().lower()
            if answer not in ('y', 'yes', 'д', 'да'):
                finish_diagnostics(diag, host, operation, 'CANCELLED', status_snapshot=st)
                return st
        reply = _json(host, 'POST', '/api/reset-openwrt-settings',
                      headers={'X-Ursus-Confirm': 'RESET-OPENWRT-SETTINGS'}, timeout=30)
        try:
            after = status(host)
        except Exception:
            after = st
        finish_diagnostics(diag, host, operation, 'SUCCESS', status_snapshot=after)
        return reply
    except Exception as exc:
        finish_diagnostics(diag, host, operation, 'FAILED', error=repr(exc))
        raise



def maximize_fresh_migration_rootfs_data(host: str, migration_status: dict) -> dict:
    """Expand the still-empty post-migration rootfs_data before first boot.

    This function is deliberately valid only immediately after a successful
    STOCK -> OPENWRT_UBI migration performed by HWFIX3. Completion of that
    migration is the proof that rootfs_data is the historical empty 1693-LEB
    volume. It must never be called on a volume that OpenWrt may already have
    mounted, because remove/recreate would destroy user data.
    """
    if not migration_status.get('operation_complete'):
        raise UrsusWebError('ROOTFSMAX2 requires a completed STOCK -> UBI migration')

    attach = console(host,
        'ubi detach; if ubi part ursus-ubi-full; then echo URSUS_ROOTFSMAX_ATTACH_OK; '
        'else echo URSUS_ROOTFSMAX_ATTACH_FAIL; fi', timeout=60)
    if 'URSUS_ROOTFSMAX_ATTACH_OK' not in attach:
        raise UrsusWebError(f'ROOTFSMAX2 UBI attach failed: {attach[-1200:]}')

    # Read live geometry after re-attaching UBI. Do not trust cached /api/status
    # counters here: HWFIX3 detaches UBI again while committing BL2 last.
    geom = console(host, 'ubi info', timeout=30)
    import re
    m_free = re.search(r'available\s+PEBs\s*:\s*(\d+)', geom, re.IGNORECASE)
    if not m_free:
        m_free = re.search(r'available[_ ]pebs\s*[=:]\s*(\d+)', geom, re.IGNORECASE)
    # U-Boot 2026.07 prints the live field as:
    #   UBI: logical eraseblock size:    126976 bytes
    # Older/test output may use:
    #   UBI: LEB size: 126976 bytes
    # Accept both spellings; this parser is a host-side safety gate and must
    # be validated against captured hardware output, not only synthetic text.
    m_leb = re.search(
        r'(?:logical\s+eraseblock|LEB)\s+size\s*:\s*(\d+)',
        geom, re.IGNORECASE)
    if not m_leb:
        m_leb = re.search(r'leb[_ ]size\s*[=:]\s*(\d+)', geom, re.IGNORECASE)
    if not m_free or not m_leb:
        raise UrsusWebError(f'ROOTFSMAX2 could not parse live UBI geometry: {geom[-1800:]}')
    free_pebs = int(m_free.group(1))
    leb_size = int(m_leb.group(1))
    if leb_size <= 0 or free_pebs <= ROOTFS_KEEP_FREE_PEBS:
        raise UrsusWebError(
            f'ROOTFSMAX2 invalid UBI geometry: leb_size={leb_size} free_pebs={free_pebs} '
            f'keep={ROOTFS_KEEP_FREE_PEBS}'
        )

    target_lebs = ROOTFS_MIGRATION_LEBS + free_pebs - ROOTFS_KEEP_FREE_PEBS
    target_bytes = target_lebs * leb_size
    keep_bytes = ROOTFS_KEEP_FREE_PEBS * leb_size

    print(terms.tr(
        f'[ШАГ] Расширяю пустой rootfs_data до {target_lebs} LEB '
        f'({target_bytes / 1024 / 1024:.1f} MiB UBI), оставляю '
        f'{ROOTFS_KEEP_FREE_PEBS} свободных PEB (~{keep_bytes / 1024 / 1024:.1f} MiB).',
        f'[STEP] Expanding the empty rootfs_data to {target_lebs} LEB '
        f'({target_bytes / 1024 / 1024:.1f} MiB UBI), keeping '
        f'{ROOTFS_KEEP_FREE_PEBS} free PEBs (~{keep_bytes / 1024 / 1024:.1f} MiB).'
    ))

    pre = console(host,
        'if ubi check rootfs_data; then echo URSUS_ROOTFSMAX_PRECHECK_OK; '
        'else echo URSUS_ROOTFSMAX_PRECHECK_FAIL; fi', timeout=30)
    if 'URSUS_ROOTFSMAX_PRECHECK_OK' not in pre:
        raise UrsusWebError(f'ROOTFSMAX2 rootfs_data precheck failed: {pre[-1200:]}')

    removed = console(host,
        'if ubi remove rootfs_data; then echo URSUS_ROOTFSMAX_REMOVE_OK; '
        'else echo URSUS_ROOTFSMAX_REMOVE_FAIL; fi', timeout=60)
    if 'URSUS_ROOTFSMAX_REMOVE_OK' not in removed:
        raise UrsusWebError(f'ROOTFSMAX2 rootfs_data remove failed: {removed[-1200:]}')

    create_cmd = f'ubi create rootfs_data 0x{target_bytes:x} dynamic 6'
    created = console(host,
        f'if {create_cmd}; then echo URSUS_ROOTFSMAX_CREATE_OK; '
        f'else echo URSUS_ROOTFSMAX_CREATE_FAIL; fi', timeout=90)
    if 'URSUS_ROOTFSMAX_CREATE_OK' not in created:
        # Fail safe: do not leave a successful migration without rootfs_data.
        fallback = console(host,
            f'if ubi create rootfs_data 0x{ROOTFS_LEGACY_REQUEST:x} dynamic 6; '
            'then echo URSUS_ROOTFSMAX_FALLBACK_OK; else echo URSUS_ROOTFSMAX_FALLBACK_FAIL; fi',
            timeout=90)
        if 'URSUS_ROOTFSMAX_FALLBACK_OK' in fallback:
            raise UrsusWebError(
                'ROOTFSMAX2 target create failed; legacy 205 MiB rootfs_data was restored safely'
            )
        raise UrsusWebError(
            'ROOTFSMAX2 target create and legacy fallback both failed; do not reboot: '
            + (created + '\n' + fallback)[-1800:]
        )

    verify = console(host,
        'if ubi check rootfs_data; then echo URSUS_ROOTFSMAX_VOLUME_OK; '
        'ubi info; else echo URSUS_ROOTFSMAX_VOLUME_FAIL; fi', timeout=60)
    if 'URSUS_ROOTFSMAX_VOLUME_OK' not in verify:
        raise UrsusWebError(f'ROOTFSMAX2 verification failed: {verify[-1800:]}')

    m = re.search(r'available\s+PEBs\s*:\s*(\d+)', verify, re.IGNORECASE)
    if not m:
        m = re.search(r'available[_ ]pebs\s*[=:]\s*(\d+)', verify, re.IGNORECASE)
    if not m:
        raise UrsusWebError(f'ROOTFSMAX2 could not parse post-create free PEB count: {verify[-1800:]}')
    free_after = int(m.group(1))
    if free_after != ROOTFS_KEEP_FREE_PEBS:
        raise UrsusWebError(
            f'ROOTFSMAX2 post-create headroom mismatch: free={free_after}, '
            f'expected={ROOTFS_KEEP_FREE_PEBS}'
        )

    try:
        console(host, 'ubi detach', timeout=30)
    except Exception:
        pass

    print(terms.tr(
        f'[ГОТОВО] rootfs_data расширен до {target_lebs} LEB; '
        f'свободный UBI headroom: {free_after} PEB.',
        f'[READY] rootfs_data expanded to {target_lebs} LEB; '
        f'free UBI headroom: {free_after} PEB.'
    ))
    return {
        'rootfs_data_lebs': target_lebs,
        'rootfs_data_bytes': target_bytes,
        'free_pebs': free_after,
        'leb_size': leb_size,
    }

def reboot(host: str) -> None:
    _json(host, 'POST', '/api/reboot', headers={'X-Ursus-Confirm': 'REBOOT'}, timeout=10)
