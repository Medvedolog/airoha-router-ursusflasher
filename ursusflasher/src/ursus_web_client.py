#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import time
import urllib.parse
from pathlib import Path

import ui_terms as terms

CHUNK = 0x10000

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


def upload(host: str, path: Path, kind: str, *, progress=True) -> dict:
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
    first = _json(host, 'POST', begin, headers=base, timeout=15)
    off = int(first.get('received', -1))
    if first.get('generation') != gen or int(first.get('declared_size', -1)) != total or off != 0:
        raise UrsusWebError(f'begin ACK mismatch: {first}')
    last = first
    with path.open('rb') as f:
        while off < total:
            f.seek(off)
            data = f.read(min(CHUNK, total-off))
            if not data:
                raise UrsusWebError(f'unexpected EOF at {off}/{total}')
            headers = {
                'Content-Type': 'application/octet-stream',
                'Content-Length': str(len(data)),
                'X-Ursus-Generation': gen,
                'X-Ursus-Offset': str(off),
                'X-Ursus-Total': str(total),
            }
            last = _json(host, 'POST', chunk, headers=headers, body=data, timeout=45)
            received = int(last.get('received', -1))
            declared = int(last.get('declared_size', -1))
            if last.get('generation') != gen or declared != total or not (off < received <= total):
                raise UrsusWebError(f'chunk ACK mismatch: {last}')
            off = received
            if progress:
                print(f'\r{terms.tr('[ПЕРЕДАЧА]', '[TRANSFER]')} {path.name}: {off}/{total} ({off*100//total}%)', end='', flush=True)
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
                from proven_backend import _write_session_only
                _write_session_only(
                    f'[WEB_STATUS_RETRY] count={transport_failures} error={type(exc).__name__}:{exc}'
                )
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
                from proven_backend import _write_session_only
                _write_session_only(f'[WEB_STATUS_RAW] stage={stage!r} percent={pct!r} detail={detail!r} active={active} complete={complete} failed={failed}')
            except Exception:
                pass
            shown_pct = '?' if pct is None else pct
            print(terms.tr(f'[ШАГ] Операция UrsusBoot: {shown_pct}%', f'[STEP] UrsusBoot operation: {shown_pct}%'))
            last_key = key
        if failed:
            raise UrsusWebError(f'operation failed: {stage}: {detail}')
        if complete:
            return st
        time.sleep(0.6 if active else 1.0)
    raise UrsusWebError('timed out waiting for UrsusBoot flash operation')


def update_bootloader(host: str, fip: Path, *, confirm=True) -> dict:
    st = status(host)
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
            return status(host)
    _json(host, 'POST', '/api/update-ursusboot', headers={'X-Ursus-Confirm': 'UPDATE-URSUSBOOT'}, timeout=20)
    return _poll(host, bootloader=True)


def update_firmware(host: str, image: Path, *, confirm=True, preloader: Path | None = None, keep_settings: bool = True) -> dict:
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
            return st
    headers = {'X-Ursus-Confirm': header}
    if endpoint == '/api/install-ubi':
        effective_keep = keep_settings if layout == 'OPENWRT_UBI' else False
        headers['X-Ursus-Keep-Settings'] = '1' if effective_keep else '0'
    _json(host, 'POST', endpoint, headers=headers, timeout=20)
    return _poll(host, bootloader=False)



def reset_openwrt_settings(host: str, *, confirm: bool = True) -> dict:
    """Reset only OpenWrt rootfs_data through UrsusBoot Recovery."""
    st = status(host)
    layout = st.get('current_layout')
    if layout not in ('OPENWRT_UBI', 'OPENWRT_STOCK_LAYOUT'):
        raise UrsusWebError(f'OpenWrt settings reset is not applicable to {layout}')
    if confirm:
        answer = input(terms.tr(
            'Сбросить настройки OpenWrt (rootfs_data), не меняя прошивку? [y/N]: ',
            'Reset OpenWrt settings (rootfs_data) without replacing firmware? [y/N]: '
        )).strip().lower()
        if answer not in ('y', 'yes', 'д', 'да'):
            return st
    return _json(host, 'POST', '/api/reset-openwrt-settings',
                 headers={'X-Ursus-Confirm': 'RESET-OPENWRT-SETTINGS'}, timeout=30)



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
