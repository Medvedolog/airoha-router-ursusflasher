#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import lzma
import os
import struct
import time
import zlib
from pathlib import Path

import console_ui as ui
import ui_terms as terms
import ursusboot_update as u
from proven_backend import Error, RecoverySerial, xmodem_send

ROOT = u.ROOT
PAYLOAD_DIR = u.PAYLOAD_DIR
ALPHA3_FIP = u.PAYLOAD
BASE_FIP = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha4-HWFIX2-update.fip'
HWFIX_FIP = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha4-UIFIX1-update.fip'
HWFIX_RAW = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.bin'
HWFIX_LZ = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.lzma'

A3_FIP_SHA = '597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce'
A3_FIP_CRC = '82263464'
BASE_FIP_SHA = 'f164ff4ac0f272550151c4f0d89cd154bd7b0d6eb9165c44c469caec9fc0138f'
BASE_FIP_CRC = '1917ed23'
HWFIX_FIP_SHA = 'a6d1977eed9eb08bb9960b6621322fdd20babe07fb36fdb178b61dedc09a8ad4'
HWFIX_FIP_CRC = '470b3b69'
HWFIX_RAW_SHA = '921d53f396bec54613c792e6a31388e5a12a481fdcf963875dda2fad86499a67'
HWFIX_RAW_SIZE = 947216
HWFIX_LZ_SHA = '380464993b5c326282c0ee6f2efd8c1d16a516f76f999e3169ad1ac7b5f16df6'
HWFIX_LZ_SIZE = 325095
A3_BL2_CRC = '9f7bf316'
A3_BL2_SHA = '6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d'
FIP_SIZE = 503808
NT_UUID = bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
CHECKSUM_UUID = bytes.fromhex('a2cceab7f8254b279704633a6fd69ad8')

def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _crc_bytes(data: bytes) -> str:
    return f'{zlib.crc32(data) & 0xffffffff:08x}'


def _parse_fip(data: bytes) -> tuple[list[dict], int]:
    if len(data) < 56 or struct.unpack_from('<I', data, 0)[0] != 0xAA640001:
        raise Error('FIP header magic неверен')
    if struct.unpack_from('<I', data, 4)[0] != 0x12345678:
        raise Error('FIP serial/header неверен')
    entries: list[dict] = []
    pos = 16
    end = 0
    for _ in range(32):
        uid = data[pos:pos + 16]
        off, size, flags = struct.unpack_from('<QQQ', data, pos + 16)
        if uid == b'\0' * 16:
            end = off
            break
        if off < 0x400 or not size or off + size > len(data):
            raise Error(f'FIP TOC range неверен: off=0x{off:x} size=0x{size:x}')
        entries.append({'uuid': uid, 'off': off, 'size': size, 'flags': flags,
                        'payload': data[off:off + size]})
        pos += 40
    if end != len(data):
        raise Error(f'FIP declared end 0x{end:x} != physical size 0x{len(data):x}')
    return entries, end


def validate_alpha4_host() -> dict:
    required = [ALPHA3_FIP, BASE_FIP, HWFIX_FIP, HWFIX_RAW, HWFIX_LZ,
                u.BL2_IMAGE, u.PRELOADER, u.RAM_INSTALLER]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise Error('Не хватает файлов alpha4-HWFIX3: ' + ', '.join(missing))
    if HWFIX_FIP.stat().st_size != FIP_SIZE or _sha(HWFIX_FIP) != HWFIX_FIP_SHA:
        raise Error('alpha4-HWFIX3 FIP identity mismatch')
    if _crc_bytes(HWFIX_FIP.read_bytes()) != HWFIX_FIP_CRC:
        raise Error('alpha4-HWFIX3 FIP CRC32 mismatch')
    if HWFIX_RAW.stat().st_size != HWFIX_RAW_SIZE or _sha(HWFIX_RAW) != HWFIX_RAW_SHA:
        raise Error('alpha4-HWFIX3 raw BL33 identity mismatch')
    if HWFIX_LZ.stat().st_size != HWFIX_LZ_SIZE or _sha(HWFIX_LZ) != HWFIX_LZ_SHA:
        raise Error('alpha4-HWFIX3 compressed BL33 identity mismatch')
    if _sha(BASE_FIP) != BASE_FIP_SHA or _crc_bytes(BASE_FIP.read_bytes()) != BASE_FIP_CRC:
        raise Error('hardware-proven alpha4-HWFIX2 rollback FIP identity mismatch')
    if _sha(ALPHA3_FIP) != A3_FIP_SHA or _crc_bytes(ALPHA3_FIP.read_bytes()) != A3_FIP_CRC:
        raise Error('alpha3 fip.old oracle identity mismatch')
    if _sha(u.BL2_IMAGE) != A3_BL2_SHA or _crc_bytes(u.BL2_IMAGE.read_bytes()) != A3_BL2_CRC:
        raise Error('hardware-proven BL2 identity mismatch')

    good_pre_sha = '6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808'
    stale_pre_sha = '66e812b49591cec1c53c00c9f42647c73189b00635a6b4ebee9ce0f2be4618a1'
    if _sha(u.PRELOADER) != good_pre_sha:
        raise Error('package preloader != hardware-proven 6c3b2339...')
    raw = HWFIX_RAW.read_bytes()
    if bytes.fromhex(good_pre_sha) not in raw or bytes.fromhex(A3_BL2_SHA) not in raw:
        raise Error('HWFIX3 BL33 does not contain expected preloader/BL2 runtime contract')
    if bytes.fromhex(stale_pre_sha) in raw:
        raise Error('HWFIX3 BL33 contains stale preloader lineage')

    base = BASE_FIP.read_bytes(); cand = HWFIX_FIP.read_bytes()
    eb, _ = _parse_fip(base); ec, _ = _parse_fip(cand)
    bb = {e['uuid']: e for e in eb}; bc = {e['uuid']: e for e in ec}
    if set(bb) != set(bc):
        raise Error('HWFIX3 FIP changed UUID entry set')
    for uid in bb:
        if uid in (NT_UUID, CHECKSUM_UUID):
            continue
        x, y = bb[uid], bc[uid]
        if (x['off'], x['size'], x['flags'], x['payload']) != (y['off'], y['size'], y['flags'], y['payload']):
            raise Error(f'HWFIX3 changed non-NT FIP entry {uid.hex()}')
    checksum = bc.get(CHECKSUM_UUID)
    if not checksum or checksum['size'] != 40:
        raise Error('HWFIX3 checksum metadata invalid')
    meta = checksum['payload']; covered = struct.unpack_from('<I', meta, 0)[0]
    if covered != checksum['off'] or struct.unpack_from('<I', meta, 4)[0] != (zlib.crc32(cand[:covered]) & 0xffffffff):
        raise Error('HWFIX3 checksum CRC metadata mismatch')
    if meta[8:] != hashlib.sha256(cand[:covered]).digest():
        raise Error('HWFIX3 checksum SHA metadata mismatch')
    nt = bc.get(NT_UUID)
    if not nt or nt['off'] != 0x27800 or nt['size'] != HWFIX_LZ_SIZE or nt['payload'] != HWFIX_LZ.read_bytes():
        raise Error('HWFIX3 final FIP NT_FW != packaged .lzma')
    lz = nt['payload']
    if lz[0] != 0x9b or struct.unpack_from('<I', lz, 1)[0] != 0x100000 or struct.unpack_from('<Q', lz, 5)[0] != HWFIX_RAW_SIZE:
        raise Error('HWFIX3 LZMA1EXT contract mismatch')
    filters = [{'id': lzma.FILTER_LZMA1, 'dict_size': 0x100000, 'lc': 2, 'lp': 2, 'pb': 3}]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    # Airoha BL2 consumes exactly the usize declared in the 13-byte LZMA1EXT
    # header and does not require an EOS marker. Stop at that exact byte count;
    # asking liblzma for one byte more can decode beyond the intended no-EOPM
    # boundary and is not the device-side contract.
    decoded = dec.decompress(lz[13:], max_length=HWFIX_RAW_SIZE)
    if len(decoded) != HWFIX_RAW_SIZE or decoded != raw:
        raise Error('HWFIX3 final FIP host decode mismatch')
    # Runtime policy strings are binary gates, not operator prompts.
    must = [b'URSUS_WEB_ALREADY_RUNNING owner=active action=noop',
            b'URSUS_NET_ETHERNET_INACTIVE action=clean-stop',
            b'bootcmd=ursusdispatch',
            b'U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-UIFIX1',
            b'URSUS_LED_RECOVERY_PATTERN_SYNC=1',
            b'URSUS_BADBLOCK_SCAN source=UBI skip_full_mtd_scan=1',
            b'boot_validation_reason',
            b'initramfs/FIT exceeds shared 64 MiB staging capacity',
            b'https://github.com/Medvedolog/airoha-router-ursusflasher',
            'Предыдущий образ OpenWrt'.encode('utf-8')]
    if any(x not in raw for x in must):
        raise Error('HWFIX3 BL33 is missing required runtime policy markers')
    forbidden = [b'Run default boot command.', b'Load BL31+U-Boot FIP via TFTP then write to NAND',
                 b'Load BL2 preloader via TFTP then write to NAND']
    if any(x in raw for x in forbidden):
        raise Error('HWFIX3 BL33 still contains production bootmenu entries')
    return {'fip_size': FIP_SIZE, 'fip_sha256': HWFIX_FIP_SHA, 'fip_crc32': HWFIX_FIP_CRC}


def _baseline(view: dict, active_crc: str) -> dict:
    if not view.get('ubi_target'):
        raise Error('UBI не подключён; HWFIX3-тест остановлен до записи.')
    by_name = {str(v.get('name', '')): v for v in (view.get('volumes') or [])}
    old = by_name.get('fip.old'); cur = by_name.get('fip')
    if not old or not cur:
        raise Error('Нужны существующие fip.old и fip; HWFIX3-тест ничего не создаёт и не переименовывает.')
    if old.get('type') != 'static' or cur.get('type') != 'static':
        raise Error('fip.old и fip должны быть static; HWFIX3-тест остановлен.')
    if int(old.get('used_bytes') or 0) != FIP_SIZE or int(cur.get('used_bytes') or 0) != FIP_SIZE:
        raise Error(f'fip.old/fip должны иметь used_bytes={FIP_SIZE}; HWFIX3-тест остановлен.')
    checks = {str(x.get('name', '')): x for x in (view.get('fip_checks') or [])}
    old_crc = str((checks.get('fip.old') or {}).get('crc32') or '').lower()
    cur_crc = str((checks.get('fip') or {}).get('crc32') or '').lower()
    bl2_crc = str(view.get('bl2_crc32') or '').lower()
    if old_crc != A3_FIP_CRC:
        raise Error(f'fip.old должен оставаться exact alpha3 {A3_FIP_CRC}; сейчас {old_crc or "UNKNOWN"}.')
    if cur_crc != active_crc:
        raise Error(f'active fip имеет CRC32 {cur_crc or "UNKNOWN"}, ожидался {active_crc}; HWFIX3-тест остановлен.')
    if bl2_crc != A3_BL2_CRC:
        raise Error(f'BL2 должен быть exact alpha3 {A3_BL2_CRC}; сейчас {bl2_crc or "UNKNOWN"}.')
    if old.get('id') == cur.get('id'):
        raise Error('fip.old и fip имеют одинаковый ID; HWFIX3-тест остановлен.')
    return {'ubi_target': view.get('ubi_target'), 'bl2_target': view.get('bl2_target'),
            'bl2_offset': int(view.get('bl2_offset') or 0),
            'old_id': old.get('id'), 'old_type': old.get('type'),
            'cur_id': cur.get('id'), 'cur_type': cur.get('type'),
            'old_crc': old_crc, 'cur_crc': cur_crc, 'bl2_crc': bl2_crc}


def _load_candidate(sp: RecoverySerial, log, path: Path, label: str, expected_sha: str) -> None:
    if _sha(path) != expected_sha or path.stat().st_size != FIP_SIZE:
        raise Error(f'{label}: host identity mismatch')
    ui.status(tr('ШАГ', 'STEP'), tr(
        f'Передаю {label} через XMODEM в RAM 0x{u.LOADADDR:08x}. Постоянная память пока не меняется.',
        f'Transferring {label} over XMODEM to RAM 0x{u.LOADADDR:08x}. Persistent storage is unchanged.'))
    u._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input(); u._uboot_send_line(sp, f'loadx 0x{u.LOADADDR:x}'); time.sleep(0.35)
    xmodem_send(sp, path, label, log)
    u._uboot_read_until_prompt(sp, log, 50, f'loadx {label}')
    u._note_xmodem_payload_ready(label, expected_sha)


def _verify_unchanged_bl2(sp: RecoverySerial, log, baseline: dict) -> tuple[bytes, bytes, str]:
    target = baseline.get('bl2_target')
    if not target:
        raise Error('Не удалось определить MTD target BL2.')
    off = int(baseline.get('bl2_offset') or 0)
    read = u._uboot_require_ok(sp, log, f'mtd read {target} 0x{u.READBACK_ADDR:x} 0x{off:x} 0x{u.BL2_SIZE:x}', 120, 'контрольное чтение BL2')
    crc_raw, rc = u._uboot_command_result(sp, log, f'crc32 0x{u.READBACK_ADDR:x} 0x{u.BL2_SIZE:x}', timeout=40)
    crc = u._extract_crc32(u._decode_uart_text(crc_raw)) if rc == 0 else None
    if crc != A3_BL2_CRC:
        raise Error(f'BL2 изменился или не читается: CRC32={crc or "UNKNOWN"}, ожидался {A3_BL2_CRC}.')
    return read, crc_raw, crc


def _transaction(sp: RecoverySerial, log, view: dict, baseline: dict, candidate: Path,
                 candidate_sha: str, candidate_crc: str,
                 label: str, report_path: Path) -> None:
    _load_candidate(sp, log, candidate, label, candidate_sha)
    ui.rule(tr('ОДНА ПЕРЕМЕННАЯ: ACTIVE FIP', 'SINGLE VARIABLE: ACTIVE FIP'), style='red')
    ui.status(tr('ВНИМАНИЕ', 'WARNING'), tr(
        f'Изменятся только {FIP_SIZE} байт содержимого существующего static-тома fip ID {baseline["cur_id"]}. fip.old и BL2 не записываются; UBI volumes не удаляются/создаются/переименовываются.',
        f'Only {FIP_SIZE} bytes in existing static fip volume ID {baseline["cur_id"]} will change. fip.old and BL2 are not written; UBI volumes are not removed/created/renamed.'))
    ans = ui.prompt(tr('Записать этот active fip? [y/N]: ', 'Write this active fip? [y/N]: ')).strip().lower()
    if ans not in ('y', 'yes'):
        raise Error('Операция отменена до записи.')

    write = u._uboot_require_ok(sp, log, f'ubi write 0x{u.LOADADDR:x} fip 0x{FIP_SIZE:x}', 180, f'запись {label} в fip')
    read = u._uboot_require_ok(sp, log, f'ubi read 0x{u.READBACK_ADDR:x} fip 0x{FIP_SIZE:x}', 120, 'readback active fip')
    cmp_raw = u._uboot_require_ok(sp, log, f'cmp.b 0x{u.LOADADDR:x} 0x{u.READBACK_ADDR:x} 0x{FIP_SIZE:x}', 90, 'byte compare active fip')
    crc_raw, crc_rc = u._uboot_command_result(sp, log, f'crc32 0x{u.READBACK_ADDR:x} 0x{FIP_SIZE:x}', timeout=40)
    active_after = u._extract_crc32(u._decode_uart_text(crc_raw)) if crc_rc == 0 else None
    if active_after != candidate_crc:
        raise Error(f'active fip readback CRC32={active_after or "UNKNOWN"}, ожидался {candidate_crc}. Не выключайте питание; сохраните лог.')

    old_read = u._uboot_require_ok(sp, log, f'ubi read 0x{u.READBACK_ADDR:x} fip.old 0x{FIP_SIZE:x}', 120, 'контрольное чтение fip.old')
    old_crc_raw, old_rc = u._uboot_command_result(sp, log, f'crc32 0x{u.READBACK_ADDR:x} 0x{FIP_SIZE:x}', timeout=40)
    old_after = u._extract_crc32(u._decode_uart_text(old_crc_raw)) if old_rc == 0 else None
    if old_after != A3_FIP_CRC:
        raise Error(f'fip.old изменился: CRC32={old_after or "UNKNOWN"}, ожидался alpha3 {A3_FIP_CRC}.')

    info_raw, info_rc = u._uboot_command_result(sp, log, 'ubi info l', timeout=50)
    volumes = u._parse_ubi_layout(u._decode_uart_text(info_raw)) if info_rc == 0 else []
    by_name = {str(v.get('name', '')): v for v in volumes}
    old = by_name.get('fip.old'); cur = by_name.get('fip')
    if not old or old.get('id') != baseline['old_id'] or old.get('type') != baseline['old_type']:
        raise Error('После записи изменилась identity fip.old. Не выключайте питание; сохраните лог.')
    if not cur or cur.get('id') != baseline['cur_id'] or cur.get('type') != baseline['cur_type']:
        raise Error('После записи изменилась identity active fip. Не выключайте питание; сохраните лог.')

    bl2_read, bl2_crc_raw, bl2_after = _verify_unchanged_bl2(sp, log, baseline)
    lines = [
        'UrsusFlasher alpha4-HWFIX3 active-FIP transaction',
        f'timestamp={time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'label={label}', f'candidate_sha256={candidate_sha}', f'candidate_crc32={candidate_crc}',
        f'fip_id={baseline["cur_id"]}', f'fip_crc32_before={baseline["cur_crc"]}', f'fip_crc32_after={active_after}',
        f'fip_old_id={baseline["old_id"]}', f'fip_old_crc32_before={baseline["old_crc"]}', f'fip_old_crc32_after={old_after}',
        f'bl2_crc32_before={baseline["bl2_crc"]}', f'bl2_crc32_after={bl2_after}',
        'ubi_remove=0', 'ubi_create=0', 'ubi_rename=0', 'bl2_write=0', 'saveenv=0',
        '', 'RAW_FIP_WRITE:', u._decode_uart_text(write),
        '', 'RAW_FIP_READBACK:', u._decode_uart_text(read),
        '', 'RAW_FIP_CMP:', u._decode_uart_text(cmp_raw),
        '', 'RAW_FIP_CRC32:', u._decode_uart_text(crc_raw),
        '', 'RAW_FIP_OLD_READ:', u._decode_uart_text(old_read),
        '', 'RAW_FIP_OLD_CRC32:', u._decode_uart_text(old_crc_raw),
        '', 'RAW_UBI_INFO_AFTER:', u._decode_uart_text(info_raw),
        '', 'RAW_BL2_READ:', u._decode_uart_text(bl2_read),
        '', 'RAW_BL2_CRC32:', u._decode_uart_text(bl2_crc_raw), '',
    ]
    report_path.write_text('\n'.join(lines), encoding='utf-8')
    ui.rule(tr('ЗАПИСЬ И READBACK ПРОШЛИ', 'WRITE AND READBACK PASSED'), style='green')
    ui.status(tr('ГОТОВО', 'DONE'), tr(
        f'active fip теперь CRC32={active_after}; fip.old остался alpha3 {old_after}; BL2 остался exact alpha3 {bl2_after}.',
        f'active fip is now CRC32={active_after}; fip.old remains alpha3 {old_after}; BL2 remains exact alpha3 {bl2_after}.'))
    ui.info(tr(f'Отчёт HWFIX3: {report_path}', f'HWFIX3 report: {report_path}'))


def _run(mode: str) -> None:
    validate_alpha4_host()
    logs = ROOT / 'results'; logs.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    uart_log = logs / f'ursus-alpha4-hwfix3-uart-{stamp}.log'
    state_report = logs / f'ursus-alpha4-hwfix3-state-{stamp}.txt'
    tx_report = logs / f'ursus-alpha4-hwfix3-{mode}-{stamp}.txt'
    port = u.choose_port(); sp = RecoverySerial(port)
    old_quiet = os.environ.get('URSUS_QUIET_UART_UI'); os.environ['URSUS_QUIET_UART_UI'] = '1'
    try:
        with uart_log.open('ab', buffering=0) as log:
            u._enter_bootrom_ram_updater(sp, log,
                reason=tr('HWFIX3 меняет только active fip через hardware-proven alpha3 RAM path.',
                          'HWFIX3 changes only active fip through the hardware-proven alpha3 RAM path.'),
                require_native=False)
            view = u.capture_bootchain_forensics(sp, log, state_report)
            if mode == 'install':
                base = _baseline(view, BASE_FIP_CRC)
                _transaction(sp, log, view, base, HWFIX_FIP, HWFIX_FIP_SHA, HWFIX_FIP_CRC,
                             'UrsusBoot alpha4-HWFIX3 active FIP', tx_report)
                ui.status(tr('СДЕЛАЙТЕ', 'DO THIS'), tr(
                    'Полностью выключите питание, затем включите без Reset и сохраните cold-boot UART. Ожидается U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-UIFIX1.',
                    'Power off completely, then power on without Reset and save the cold-boot UART. Expected: U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-UIFIX1.'))
            elif mode == 'rollback':
                base = _baseline(view, HWFIX_FIP_CRC)
                _transaction(sp, log, view, base, BASE_FIP, BASE_FIP_SHA, BASE_FIP_CRC,
                             'hardware-proven alpha4-HWFIX2 rollback FIP', tx_report)
                ui.status(tr('СДЕЛАЙТЕ', 'DO THIS'), tr(
                    'Полностью выключите питание и включите без Reset. Ожидается возврат U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-HWFIX2.',
                    'Power off completely and power on without Reset. Expected: return to U-Boot 2026.07-UrsusBoot-0.1.0-alpha4-HWFIX2.'))
            else:
                raise Error(f'unknown mode {mode}')
    finally:
        if old_quiet is None: os.environ.pop('URSUS_QUIET_UART_UI', None)
        else: os.environ['URSUS_QUIET_UART_UI'] = old_quiet
        sp.close()
    ui.info(tr(f'Исходное состояние: {state_report}', f'Baseline state: {state_report}'))
    ui.info(tr(f'Полный UART-лог: {uart_log}', f'Full UART log: {uart_log}'))


def install_hwfix3() -> None:
    _run('install')


def rollback_hwfix3() -> None:
    _run('rollback')


# Compatibility aliases for older EXPERT glue.
def install_hwfix2() -> None:
    install_hwfix3()


def rollback_hwfix2() -> None:
    rollback_hwfix3()


def install_hwfix1() -> None:
    install_hwfix3()


def rollback_hwfix1() -> None:
    rollback_hwfix3()


if __name__ == '__main__':
    validate_alpha4_host()
    print('ALPHA4_UIFIX1_HOST_QA=PASS')
