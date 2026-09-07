#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import re
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / 'fw').is_dir() and (_REPO_ROOT / 'payloads').is_dir() and (_REPO_ROOT / 'config').is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
PAYLOAD_DIR = (ROOT / 'payloads' / 'md' / 'ursusboot') if REPO_MODE else (HERE / 'payloads' / 'md' / 'ursusboot')
EMERGENCY_PAYLOAD = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha3-update.fip'
PRODUCTION_PAYLOAD = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip'
PAYLOAD = EMERGENCY_PAYLOAD  # compatibility alias for BootROM/emergency alpha3 paths
RAM_INSTALLER = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha3-ram-installer.fip'
BL2_IMAGE = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha3-bl2.bin'
PRELOADER = PAYLOAD_DIR / 'openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin'
DEFAULT_FIT = ROOT / 'fw' / 'openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb'
LOADADDR = 0x8E000000
TFTP_NAME = 'ursusboot.fip'
BL2_ADDR = 0x90000000
READBACK_ADDR = 0x94000000
BL2_SIZE = 0x20000
BL2_SHA256 = '6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d'
BL2_CRC32 = '9f7bf316'
FIP_READ_SIZE = 503808
FIP_OLD_EXPERIMENT_EXPECTED_BL2_CRC32 = '09fb6b36'
FIP_OLD_EXPERIMENT_OLD_CRC32 = '66b31112'
FIP_OLD_EXPERIMENT_NEW_CRC32 = '82263464'
BL2_EXPERIMENT_EXPECTED_OLD_CRC32 = '09fb6b36'
BL2_EXPERIMENT_EXPECTED_FIP_CRC32 = '82263464'
BL2_EXPERIMENT_EXPECTED_FIP_OLD_ID = 6
BL2_EXPERIMENT_EXPECTED_FIP_ID = 7

FIP_CRC32_REFERENCES = {
    '82263464': 'UrsusBoot 0.1.0-alpha3 FIP (SHA256 597071e1...)',
    'b1b313a5': 'UrsusBoot 0.1.0-alpha4 LZMAFIX1 FIP (SHA256 222b0241...)',
    '66b31112': 'UrsusBoot 0.1.0-alpha4/HF6 FIP (SHA256 d56f2673...)',
}

STOCK_BOOT_SIZE = 0x00080000
STOCK_FIP_OFF = 0x00000800
STOCK_ENV_OFF = 0x0007C000
STOCK_FIP_WINDOW = STOCK_ENV_OFF - STOCK_FIP_OFF
NT_FW_UUID = bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
FIP_MAGIC = 0xAA640001
FIP_SERIAL = 0x12345678

sys.path.insert(0, str(HERE))
from proven_backend import (  # noqa: E402
    Error, RecoverySerial, TftpResult, list_serial_ports, probe_serial_port,
    serve_tftp_get, local_ip_for, wait_bootrom_xmodem, xmodem_send,
    wait_uboot_prompt, uboot_command, _uboot_send_line, _uboot_read_until_prompt,
    _uboot_wait_quiet, _uboot_prompt_present, _write_session_only,
)
import ursus_web_client as uw  # noqa: E402
import console_ui as ui  # noqa: E402
import ui_terms as terms  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _ursus_meta() -> dict:
    path = (ROOT / 'config' / 'MANIFEST.json') if REPO_MODE else (HERE / 'MANIFEST.json')
    if not path.is_file():
        raise Error(f'MANIFEST missing: {path}')
    return json.loads(path.read_text(encoding='utf-8'))['ursusboot']

def _production_meta() -> dict:
    meta = _ursus_meta()
    candidate = meta.get('alpha5_ubiux1_candidate') or {}
    if candidate.get('version') != '0.1.0-alpha5-UBIUX1':
        raise Error('alpha5-UBIUX1 production metadata missing from MANIFEST')
    return candidate

def validate_emergency_fip_host() -> dict:
    """Validate the physical production FIP without asking the router about layout.

    This is the host-side integrity check for BootROM emergency UrsusBoot recovery.
    It deliberately does not probe the router layout or call a duplicate
    ``ursusupdate check``; the single device-side ``ursusupdate write`` performs
    mandatory pre-write validation itself.
    """
    meta = _ursus_meta()
    if not PAYLOAD.is_file():
        raise Error(f'Production FIP отсутствует: {PAYLOAD}')
    data = PAYLOAD.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    expected_digest = str(meta.get('fip_sha256') or '').lower()
    if digest != expected_digest:
        raise Error(f'Production FIP SHA256 не совпадает с manifest: {digest} != {expected_digest}')
    rejected = {str(x).lower() for x in meta.get('rejected_alpha4_hashes', [])}
    if digest in rejected:
        raise Error(f'Production FIP находится в blacklist: {digest}')
    if len(data) >= STOCK_FIP_WINDOW:
        raise Error(f'FIP не помещается в mtd0 boot window: 0x{len(data):x}')
    if len(data) < 16 or struct.unpack_from('<I', data, 0)[0] != FIP_MAGIC:
        raise Error('FIP header magic неверен')
    if struct.unpack_from('<I', data, 4)[0] != FIP_SERIAL:
        raise Error('FIP serial/header неверен')

    nt_off = nt_size = declared_end = None
    pos = 16
    for _ in range(32):
        if pos + 40 > len(data):
            raise Error('FIP TOC оборван')
        uuid = data[pos:pos + 16]
        off, size, _flags = struct.unpack_from('<QQQ', data, pos + 16)
        if uuid == b'\0' * 16:
            declared_end = off
            break
        if off < 0x400 or not size or off + size > len(data):
            raise Error(f'FIP TOC range неверен: off=0x{off:x} size=0x{size:x}')
        if uuid == NT_FW_UUID:
            if nt_off is not None:
                raise Error('В FIP больше одного NT_FW')
            nt_off, nt_size = off, size
        pos += 40
    if declared_end != len(data):
        raise Error(f'FIP declared end 0x{(declared_end or 0):x} != physical size 0x{len(data):x}')
    if nt_off is None or nt_size is None:
        raise Error('В FIP нет NT_FW/BL33')
    if nt_off != 0x27800:
        raise Error(f'NT_FW offset 0x{nt_off:x}, ожидался 0x27800')
    if nt_size > 0x50000 or nt_off + nt_size > 0x77800:
        raise Error(f'NT_FW выходит за slot: off=0x{nt_off:x} size=0x{nt_size:x}')

    nt = data[nt_off:nt_off + nt_size]
    if len(nt) < 13 or nt[0] != 0x9B:
        raise Error(f'NT_FW LZMA property неверен: 0x{nt[0] if nt else 0:02x}, нужен 0x9b')
    dictionary = struct.unpack_from('<I', nt, 1)[0]
    usize = struct.unpack_from('<Q', nt, 5)[0]
    if dictionary != 0x00100000:
        raise Error(f'NT_FW LZMA dictionary 0x{dictionary:x}, нужен 0x100000')
    expected_usize = int(meta.get('u_boot_size') or 0)
    if usize != expected_usize:
        raise Error(f'NT_FW usize {usize}, ожидался {expected_usize}')

    filters = [{'id': lzma.FILTER_LZMA1, 'dict_size': dictionary, 'lc': 2, 'lp': 2, 'pb': 3}]
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
        raw = dec.decompress(nt[13:], max_length=usize + 1)
    except lzma.LZMAError as exc:
        raise Error(f'NT_FW LZMA1EXT decode failed: {exc}') from exc
    if len(raw) != usize:
        raise Error(f'NT_FW decoded size {len(raw)}, ожидался {usize}')
    raw_digest = hashlib.sha256(raw).hexdigest()
    expected_raw = str(meta.get('u_boot_sha256') or '').lower()
    if raw_digest != expected_raw:
        raise Error(f'Decoded BL33 SHA256 mismatch: {raw_digest} != {expected_raw}')
    reviewed_raw = PAYLOAD_DIR / 'ursusboot-md-0.1.0-alpha3-u-boot.bin'
    if reviewed_raw.is_file() and raw != reviewed_raw.read_bytes():
        raise Error('Decoded BL33 byte-for-byte не совпадает с комплектным u-boot.bin')
    ui.status('ГОТОВО', f'Проверен точный постоянный FIP UrsusBoot 0.1.0-alpha3. SHA256={digest}')
    ui.note(f'BL33 alpha3: NT_FW 0x{nt_off:x}/0x{nt_size:x}, LZMA1EXT 0x9b, dict 1 MiB, {usize} байт.')
    return {'fip_sha256': digest, 'fip_size': len(data), 'u_boot_sha256': raw_digest, 'u_boot_size': usize}


def _note_xmodem_payload_ready(label: str, expected_sha256: str) -> None:
    """Mark a host-validated payload as ready after XMODEM ACK.

    Alpha3 intentionally does not use the U-Boot CLI ``hash`` command as a
    recovery gate.  The alpha3 build contains the SHA256 library for its own
    device-side code, but the interactive ``hash sha256`` command is not a
    reliable success-return interface on the hardware build.  The source file
    is SHA256-pinned on the host and XMODEM protects every transferred block.
    Persistent writes are verified later by byte-for-byte readback with
    ``cmp.b`` against the still-resident RAM source.
    """
    ui.status('ГОТОВО', f'{label}: XMODEM подтверждён; исходный файл SHA256={expected_sha256}.')


def _uboot_require_ok(sp: RecoverySerial, log, command: str, timeout: float, label: str) -> bytes:
    """Run one U-Boot command and require RC=0.

    ``uboot_command`` already queries ``$?`` on a separate UART line.  Do not
    wrap the command in a second hush ``if`` marker: that duplicated framing
    caused a false failure on real AN7581 hardware even though ``mtd list``
    had returned RC=0.
    """
    try:
        return uboot_command(sp, log, command, timeout=int(timeout))
    except Error as exc:
        raise Error(f'{label}: {exc}') from exc

def load_fip_xmodem_emergency(sp: RecoverySerial, log) -> dict:
    """Load the production FIP for emergency recovery and verify its RAM SHA256."""
    meta = validate_emergency_fip_host()
    size = meta['fip_size']
    ui.status('ШАГ', f'Передаю production FIP через XMODEM в RAM 0x{LOADADDR:08x}; {size} байт / 0x{size:x}.')
    _uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    _uboot_send_line(sp, f'loadx 0x{LOADADDR:x}')
    time.sleep(0.35)
    xmodem_send(sp, PAYLOAD, 'production UrsusBoot FIP for emergency recovery', log)
    _uboot_read_until_prompt(sp, log, 45, 'loadx emergency production UrsusBoot FIP')
    _note_xmodem_payload_ready('Production FIP в RAM', meta['fip_sha256'])
    return meta


def _uboot_command_result(sp: RecoverySerial, log, command: str, timeout: int = 30) -> tuple[bytes, int]:
    """Run a U-Boot command and return transcript + RC without turning RC!=0 into a host exception."""
    marker = f"__URSUS_RECOVERY_{time.time_ns():x}__"
    
    if os.environ.get('URSUS_QUIET_UART_UI') != '1':
        print(f'[U-Boot] {command}')
    _uboot_wait_quiet(sp, log, quiet=0.18, timeout=1.0)
    sp.reset_input()
    _uboot_send_line(sp, command)
    command_transcript = _uboot_read_until_prompt(sp, log, timeout, command)
    _uboot_wait_quiet(sp, log, quiet=0.10, timeout=0.5)
    sp.reset_input()
    _uboot_send_line(sp, f'echo {marker}_RC_$?')
    status_transcript = _uboot_read_until_prompt(sp, log, 10, f'status for {command}')
    m = re.search(re.escape(marker.encode('ascii')) + rb'_RC_([0-9]+)(?:[\r\n]|$)', status_transcript)
    if m is None:
        raise Error(f'U-Boot не вернул код завершения: {command}')
    return command_transcript + status_transcript, int(m.group(1))


def _decode_uart_text(data: bytes) -> str:
    return data.decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')


def _extract_crc32(text: str) -> str | None:
    """Best-effort extraction of U-Boot crc32 output. Never used as a write gate."""
    matches = re.findall(r'(?i)(?:==>|crc32[^0-9a-f]*)\s*([0-9a-f]{8})(?:\b|$)', text)
    return matches[-1].lower() if matches else None


def _parse_ubi_layout(text: str) -> list[dict]:
    """Best-effort parser for ``ubi info l`` output.

    The raw transcript is always retained in the forensic report. Parsed fields
    are operator convenience only and never authorize or block a write.
    """
    volumes: list[dict] = []
    cur: dict = {}

    def flush() -> None:
        nonlocal cur
        if cur and ('id' in cur or 'name' in cur):
            volumes.append(cur)
        cur = {}

    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'(?i)^vol_id\s+(-?\d+)$', line)
        if m:
            flush(); cur['id'] = int(m.group(1)); continue
        m = re.match(r'(?i)^volume\s+id\s*[:=]\s*(-?\d+)', line)
        if m:
            flush(); cur['id'] = int(m.group(1)); continue
        m = re.match(r'(?i)^name(?:_len)?\s+(.+)$', line)
        if m and not line.lower().startswith('name_len'):
            cur['name'] = m.group(1).strip().strip('"'); continue
        m = re.match(r'(?i)^name\s*[:=]\s*(.+)$', line)
        if m:
            cur['name'] = m.group(1).strip().strip('"'); continue
        m = re.match(r'(?i)^vol_type\s+(\d+)$', line)
        if m:
            n = int(m.group(1)); cur['type_raw'] = n; cur['type'] = {3:'dynamic',4:'static'}.get(n, str(n)); continue
        m = re.match(r'(?i)^type\s*[:=]\s*(dynamic|static|\d+)', line)
        if m:
            v=m.group(1).lower(); cur['type']= {'3':'dynamic','4':'static'}.get(v,v); continue
        m = re.match(r'(?i)^reserved_pebs\s+(\d+)$', line)
        if m: cur['reserved_pebs']=int(m.group(1)); continue
        m = re.match(r'(?i)^used_bytes\s+(\d+)$', line)
        if m: cur['used_bytes']=int(m.group(1)); continue
        m = re.match(r'(?i)^usable_leb_size\s+(\d+)$', line)
        if m: cur['usable_leb_size']=int(m.group(1)); continue
    flush()
    return volumes


def _identify_fip_crc32(crc: str | None) -> str:
    if not crc:
        return 'UNKNOWN'
    return FIP_CRC32_REFERENCES.get(crc.lower(), 'unknown FIP contents')


def _parse_mtd_list(text: str) -> dict:
    """Extract names from U-Boot ``mtd list`` without treating parsing as a gate."""
    names = set(re.findall(r'"([^"\r\n]+)"', text))
    master = None
    for raw in text.splitlines():
        m = re.match(r'^\s*\*\s+([^\s]+)', raw)
        if m:
            master = m.group(1).strip()
            names.add(master)
            break
    if master is None and 'spi-nand0' in text:
        master = 'spi-nand0'
        names.add(master)
    return {'master': master, 'names': sorted(names)}


def _prepare_readonly_mtd_view(sp: RecoverySerial, log) -> dict:
    """Prepare RAM-only MTD aliases needed to inspect the migrated UBI layout.

    The alpha3 source does not call its custom ``ursus_ubi_register_mtd()`` before
    we interrupt autoboot at the RAM prompt.  Therefore the source-level names
    ``ursus-ubi-full`` / ``ursus-ubi-bl2`` may not exist yet.  0.2.28 incorrectly
    assumed Linux/newer-U-Boot names ``ubi`` / ``bl2`` and failed immediately.

    First preserve the original ``mtd list``.  If no usable UBI partition name is
    already present, create temporary aliases in RAM with the legacy mtdparts
    parser.  No ``saveenv`` is issued and no NAND/UBI data is written.
    """
    original_raw = _uboot_command_no_rc(sp, log, 'mtd list', timeout=30)
    original_text = _decode_uart_text(original_raw)
    inv = _parse_mtd_list(original_text)
    master = inv.get('master')
    names = set(inv.get('names') or [])
    attach_attempts = []
    temp_raw = b''

    def try_attach(name: str) -> tuple[bool, bytes, int]:
        _uboot_command_no_rc(sp, log, 'ubi detach', timeout=20)
        raw, rc = _uboot_command_result(sp, log, f'ubi part {name}', timeout=50)
        attach_attempts.append((name, rc, _decode_uart_text(raw)))
        return rc == 0, raw, rc

    ubi_target = None
    for candidate in ('ursus-ubi-full', 'ubi', 'ursus-update-ubi'):
        if candidate not in names:
            continue
        ok, _raw, _rc = try_attach(candidate)
        if ok:
            ubi_target = candidate
            break

    # Exact MD/AN7581 migrated layout is BL2 0..0x1ffff + UBI 0x20000..end.
    # If the interrupted alpha3 RAM helper has not registered its private MTD
    # aliases yet, create equivalent *RAM-only* aliases.  The original MTD list
    # above is already preserved in the report before this happens.
    if ubi_target is None and master:
        _uboot_command_no_rc(sp, log, 'ubi detach', timeout=20)
        _uboot_command_no_rc(sp, log, 'mtdparts delall', timeout=20)
        _uboot_command_no_rc(sp, log, f'setenv mtdids nand0={master}', timeout=20)
        _uboot_command_no_rc(
            sp, log,
            f'setenv mtdparts mtdparts={master}:128k(ursus-diag-bl2),-(ursus-diag-ubi)',
            timeout=20,
        )
        _uboot_command_no_rc(sp, log, 'mtdparts', timeout=30)
        temp_raw = _uboot_command_no_rc(sp, log, 'mtd list', timeout=30)
        temp_text = _decode_uart_text(temp_raw)
        temp_inv = _parse_mtd_list(temp_text)
        names.update(temp_inv.get('names') or [])
        if 'ursus-diag-ubi' in names:
            ok, _raw, _rc = try_attach('ursus-diag-ubi')
            if ok:
                ubi_target = 'ursus-diag-ubi'

    if 'ursus-ubi-bl2' in names:
        bl2_target, bl2_offset = 'ursus-ubi-bl2', 0
    elif 'bl2' in names:
        bl2_target, bl2_offset = 'bl2', 0
    elif 'ursus-diag-bl2' in names:
        bl2_target, bl2_offset = 'ursus-diag-bl2', 0
    elif master:
        # Reading the first 128 KiB directly from the master MTD is equivalent
        # to reading the BL2 partition and does not require any partition alias.
        bl2_target, bl2_offset = master, 0
    else:
        bl2_target, bl2_offset = None, 0

    return {
        'original_mtd_text': original_text,
        'temporary_mtd_text': _decode_uart_text(temp_raw) if temp_raw else '',
        'master': master,
        'names': sorted(names),
        'ubi_target': ubi_target,
        'bl2_target': bl2_target,
        'bl2_offset': bl2_offset,
        'attach_attempts': attach_attempts,
    }


def capture_bootchain_forensics(sp: RecoverySerial, log, report_path: Path) -> dict:
    """Read UBI volume metadata and the current BL2 before any persistent write.

    Parsing is best-effort.  Command failures are written to the report instead
    of erasing the evidence with an exception.  The only RAM-side changes allowed
    here are temporary MTD aliases/environment variables; there is no ``saveenv``
    and no UBI/MTD write, erase, create, remove or rename operation.
    """
    ui.rule(terms.tr('ПРОВЕРКА UBI И BL2 — БЕЗ ЗАПИСИ', 'UBI + BL2 CHECK — READ-ONLY'), style='amber2')
    ui.info(terms.tr('Читаю таблицу томов UBI и текущий BL2. NAND/UBI не изменяются.',
                     'Reading the UBI volume table and current BL2. NAND/UBI are not modified.'))

    view = _prepare_readonly_mtd_view(sp, log)
    ubi_target = view.get('ubi_target')
    bl2_target = view.get('bl2_target')
    bl2_offset = int(view.get('bl2_offset') or 0)

    ubi_raw = b''
    ubi_rc = None
    ubi_text = ''
    volumes = []
    if ubi_target:
        ubi_raw, ubi_rc = _uboot_command_result(sp, log, 'ubi info l', timeout=50)
        ubi_text = _decode_uart_text(ubi_raw)
        if ubi_rc == 0:
            volumes = _parse_ubi_layout(ubi_text)

    # Read exactly the known persistent FIP length from each relevant volume.
    # This is a pure UBI read into RAM followed by CRC32; it does not modify UBI.
    # The fixed length lets us compare the current bytes with known alpha3/alpha4
    # persistent FIP artifacts even if the volume metadata itself is surprising.
    fip_checks = []
    if ubi_target:
        by_name = {str(v.get('name', '')): v for v in volumes}
        for name in ('fip.old', 'fip'):
            v = by_name.get(name)
            if not v:
                continue
            read_raw, read_rc = _uboot_command_result(
                sp, log, f'ubi read 0x{READBACK_ADDR:x} {name} 0x{FIP_READ_SIZE:x}', timeout=120
            )
            crc_raw = b''
            crc_rc_local = None
            crc_value = None
            if read_rc == 0:
                crc_raw, crc_rc_local = _uboot_command_result(
                    sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{FIP_READ_SIZE:x}', timeout=40
                )
                if crc_rc_local == 0:
                    crc_value = _extract_crc32(_decode_uart_text(crc_raw))
            fip_checks.append({
                'name': name,
                'id': v.get('id'),
                'type': v.get('type'),
                'used_bytes': v.get('used_bytes'),
                'read_size': FIP_READ_SIZE,
                'read_rc': read_rc,
                'crc32_rc': crc_rc_local,
                'crc32': crc_value,
                'reference': _identify_fip_crc32(crc_value),
                'read_transcript': _decode_uart_text(read_raw),
                'crc_transcript': _decode_uart_text(crc_raw),
            })

    bl2_read = b''
    bl2_read_rc = None
    crc_text = ''
    crc_rc = None
    current_crc = None
    if bl2_target:
        bl2_read, bl2_read_rc = _uboot_command_result(
            sp, log,
            f'mtd read {bl2_target} 0x{READBACK_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}',
            timeout=120,
        )
        if bl2_read_rc == 0:
            crc_raw, crc_rc = _uboot_command_result(
                sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{BL2_SIZE:x}', timeout=40
            )
            crc_text = _decode_uart_text(crc_raw)
            if crc_rc == 0:
                current_crc = _extract_crc32(crc_text)

    attempts = view.get('attach_attempts') or []
    lines = [
        'UrsusFlasher UBI + BL2 read-only report',
        f'timestamp={time.strftime("%Y-%m-%d %H:%M:%S")}',
        'persistent_writes=0',
        'saveenv=0',
        f'mtd_master={view.get("master") or "UNKNOWN"}',
        f'ubi_target={ubi_target or "NOT_ATTACHED"}',
        f'ubi_info_layout_rc={ubi_rc if ubi_rc is not None else "NOT_RUN"}',
        f'bl2_target={bl2_target or "UNKNOWN"}',
        f'bl2_read_rc={bl2_read_rc if bl2_read_rc is not None else "NOT_RUN"}',
        f'bl2_crc32_rc={crc_rc if crc_rc is not None else "NOT_RUN"}',
        f'bl2_current_crc32={current_crc or "UNKNOWN"}',
        f'bl2_alpha3_expected_crc32={BL2_CRC32}',
        f'bl2_alpha3_expected_sha256={BL2_SHA256}',
        f'fip_read_size={FIP_READ_SIZE}',
        'fip_crc32_alpha3=82263464',
        'fip_crc32_alpha4_lzmafix1=b1b313a5',
        'fip_crc32_alpha4_hf6=66b31112',
        '',
        'FIP_CONTENT_CHECKS:',
    ]
    if fip_checks:
        for item in fip_checks:
            public = {k: v for k, v in item.items() if not k.endswith('_transcript')}
            lines.append(json.dumps(public, ensure_ascii=False, sort_keys=True))
    else:
        lines.append('NO_FIP_OR_FIP_OLD_VOLUME_FOUND')
    lines += [
        '',
        'ATTACH_ATTEMPTS:',
    ]
    if attempts:
        for name, rc, transcript in attempts:
            lines += [f'--- {name} rc={rc} ---', transcript]
    else:
        lines.append('NONE')
    lines += ['', 'PARSED_UBI_VOLUMES:']
    if volumes:
        for v in volumes:
            lines.append(json.dumps(v, ensure_ascii=False, sort_keys=True))
    else:
        lines.append('PARSE_UNAVAILABLE_OR_EMPTY -- use RAW_UBI_INFO_LAYOUT below')
    lines += [
        '', 'RAW_MTD_LIST_BEFORE_TEMP_ALIASES:', view.get('original_mtd_text') or '',
        '', 'RAW_MTD_LIST_AFTER_TEMP_ALIASES:', view.get('temporary_mtd_text') or 'NOT_USED',
        '', 'RAW_UBI_INFO_LAYOUT:', ubi_text or 'NOT_AVAILABLE',
        '', 'RAW_FIP_CONTENT_CHECKS:',
    ]
    if fip_checks:
        for item in fip_checks:
            lines += [
                f'--- {item["name"]} ID={item.get("id")} read_rc={item.get("read_rc")} crc32_rc={item.get("crc32_rc")} ---',
                item.get('read_transcript') or 'NO_READ_TRANSCRIPT',
                item.get('crc_transcript') or 'NO_CRC_TRANSCRIPT',
            ]
    else:
        lines.append('NOT_AVAILABLE')
    lines += [
        '', 'RAW_BL2_READ:', _decode_uart_text(bl2_read) if bl2_read else 'NOT_AVAILABLE',
        '', 'RAW_BL2_CRC32:', crc_text or 'NOT_AVAILABLE',
        '',
    ]
    report_path.write_text('\n'.join(lines), encoding='utf-8')

    ui.status(terms.tr('ГОТОВО', 'DONE'), terms.tr('Проверка завершена. Во флеш-память ничего не записывалось.',
                                                   'Check complete. Nothing was written to flash.'))
    ui.info(terms.tr(f'Отчёт: {report_path}', f'Report: {report_path}'))
    if ubi_target:
        ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(f'UBI подключён через MTD «{ubi_target}».',
                                                    f'UBI attached through MTD "{ubi_target}".'))
    else:
        ui.status(terms.tr('ОШИБКА', 'ERROR'), terms.tr('UBI подключить не удалось; отчёт всё равно сохранён.',
                                                       'UBI could not be attached; the report was still saved.'))
    if current_crc:
        if current_crc == BL2_CRC32:
            ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(f'CRC32 текущего BL2: {current_crc} — совпадает с alpha3.',
                                                        f'Current BL2 CRC32: {current_crc} — matches alpha3.'))
        else:
            ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(f'CRC32 текущего BL2: {current_crc} — не совпадает с alpha3 ({BL2_CRC32}).',
                                                        f'Current BL2 CRC32: {current_crc} — does not match alpha3 ({BL2_CRC32}).'))
    else:
        ui.note(terms.tr('CRC32 текущего BL2 получить не удалось; сырой вывод сохранён в отчёте.',
                         'Could not obtain the current BL2 CRC32; raw output is saved in the report.'))

    fips = [v for v in volumes if str(v.get('name', '')).lower().startswith('fip')]
    if fips:
        ui.info(terms.tr('Тома fip*:', 'fip* volumes:'))
        checks_by_name = {x.get('name'): x for x in fip_checks}
        for v in fips:
            name = str(v.get('name', ''))
            chk = checks_by_name.get(name)
            if chk and chk.get('crc32'):
                ui.info(terms.tr(
                    f'  {name}: ID {v.get("id")}, {v.get("type")}, {v.get("used_bytes")} байт, CRC32={chk["crc32"]} — {chk["reference"]}',
                    f'  {name}: ID {v.get("id")}, {v.get("type")}, {v.get("used_bytes")} bytes, CRC32={chk["crc32"]} — {chk["reference"]}',
                ))
            else:
                ui.info('  ' + json.dumps(v, ensure_ascii=False, sort_keys=True))
    elif ubi_target:
        ui.note(terms.tr('Автопарсер не выделил тома fip*; смотрите RAW_UBI_INFO_LAYOUT в отчёте.',
                         'The parser did not identify fip* volumes; see RAW_UBI_INFO_LAYOUT in the report.'))

    return {
        'report_path': str(report_path),
        'volumes': volumes,
        'bl2_crc32': current_crc,
        'bl2_matches_alpha3': (current_crc == BL2_CRC32) if current_crc else None,
        'ubi_target': ubi_target,
        'bl2_target': bl2_target,
        'bl2_offset': bl2_offset,
        'mtd_master': view.get('master'),
        'fip_checks': fip_checks,
    }


def _require_fipold_experiment_baseline(view: dict) -> dict:
    """Authorize the single-variable fip.old experiment on the observed hardware state.

    This is not a generic recovery classifier.  It intentionally accepts only the
    exact read-only state captured on the failing device: existing static fip.old
    contains the known alpha4/HF6 FIP, existing static fip contains exact alpha3,
    and BL2 is still the observed non-alpha3 image.  If any of these facts differ,
    writing would no longer be the same A/B experiment and is refused before
    payload transfer or persistent mutation.
    """
    if not view.get('ubi_target'):
        raise Error('UBI не подключён; эксперимент остановлен до записи.')
    volumes = view.get('volumes') or []
    by_name = {str(v.get('name', '')): v for v in volumes}
    old = by_name.get('fip.old')
    cur = by_name.get('fip')
    if not old or not cur:
        raise Error('Для эксперимента нужны одновременно существующие тома fip.old и fip. Ничего не записано.')
    if old.get('type') != 'static' or cur.get('type') != 'static':
        raise Error('Эксперимент ожидает static-тома fip.old и fip. Ничего не записано.')
    if int(old.get('used_bytes') or 0) != FIP_READ_SIZE or int(cur.get('used_bytes') or 0) != FIP_READ_SIZE:
        raise Error(f'Эксперимент ожидает fip.old и fip по {FIP_READ_SIZE} байт. Ничего не записано.')
    checks = {str(x.get('name', '')): x for x in (view.get('fip_checks') or [])}
    old_crc = str((checks.get('fip.old') or {}).get('crc32') or '').lower()
    cur_crc = str((checks.get('fip') or {}).get('crc32') or '').lower()
    bl2_crc = str(view.get('bl2_crc32') or '').lower()
    if old_crc != FIP_OLD_EXPERIMENT_OLD_CRC32:
        raise Error(f'fip.old имеет CRC32 {old_crc or "UNKNOWN"}, ожидался исходный alpha4/HF6 {FIP_OLD_EXPERIMENT_OLD_CRC32}. Ничего не записано.')
    if cur_crc != FIP_OLD_EXPERIMENT_NEW_CRC32:
        raise Error(f'fip имеет CRC32 {cur_crc or "UNKNOWN"}, ожидался точный alpha3 {FIP_OLD_EXPERIMENT_NEW_CRC32}. Ничего не записано.')
    if bl2_crc != FIP_OLD_EXPERIMENT_EXPECTED_BL2_CRC32:
        raise Error(f'BL2 имеет CRC32 {bl2_crc or "UNKNOWN"}, исходное состояние эксперимента {FIP_OLD_EXPERIMENT_EXPECTED_BL2_CRC32}. Ничего не записано.')
    if old.get('id') == cur.get('id'):
        raise Error('fip.old и fip имеют одинаковый ID тома; целевой том не определён однозначно. Ничего не записано.')
    return {
        'fip_old_id': old.get('id'),
        'fip_id': cur.get('id'),
        'fip_old_type': old.get('type'),
        'fip_type': cur.get('type'),
        'fip_old_crc32_before': old_crc,
        'fip_crc32_before': cur_crc,
        'bl2_crc32_before': bl2_crc,
    }


def require_fipold_experiment_payloads() -> None:
    """Gate only exact alpha3 files used by the historical fip.old experiment."""
    require_ram_bootstrap_payloads()
    _require_exact_file(EMERGENCY_PAYLOAD, _ursus_meta()['fip_sha256'], 'exact alpha3 FIP')


def fipold_alpha3_experiment_transaction(sp: RecoverySerial, log, meta: dict, view: dict, baseline: dict, report_path: Path) -> str:
    """Change one persistent variable: contents of the existing fip.old volume.

    Volume identity, name, type and BL2 are deliberately preserved.  The exact
    alpha3 FIP already resident at LOADADDR is written in-place to fip.old, then
    read back and byte-compared.  Post-write reads prove that fip remains alpha3,
    fip.old keeps the same ID/type, and BL2 CRC32 is unchanged.
    """
    size = int(meta['fip_size'])
    if size != FIP_READ_SIZE:
        raise Error(f'Размер точного alpha3 FIP {size} != ожидаемых {FIP_READ_SIZE}; запись запрещена.')
    target_id = baseline.get('fip_old_id')
    ui.rule(terms.tr('ЭКСПЕРИМЕНТ: МЕНЯЕТСЯ ТОЛЬКО СОДЕРЖИМОЕ FIP.OLD', 'EXPERIMENT: ONLY FIP.OLD CONTENTS CHANGE'), style='red')
    ui.info(terms.tr(
        f'До записи: fip.old ID {target_id} = alpha4/HF6 ({FIP_OLD_EXPERIMENT_OLD_CRC32}); fip ID {baseline.get("fip_id")} = alpha3 ({FIP_OLD_EXPERIMENT_NEW_CRC32}); BL2={baseline.get("bl2_crc32_before")}.',
        f'Before write: fip.old ID {target_id} = alpha4/HF6 ({FIP_OLD_EXPERIMENT_OLD_CRC32}); fip ID {baseline.get("fip_id")} = alpha3 ({FIP_OLD_EXPERIMENT_NEW_CRC32}); BL2={baseline.get("bl2_crc32_before")}.',
    ))
    ui.status(terms.tr('ВНИМАНИЕ', 'WARNING'), terms.tr(
        'Будут изменены только 503808 байт содержимого существующего тома fip.old. Том не удаляется и не создаётся заново; ID, имя и тип не меняются; BL2 не записывается.',
        'Only the 503808-byte contents of the existing fip.old volume will change. The volume is not removed or recreated; ID/name/type stay unchanged; BL2 is not written.',
    ))
    answer = ui.prompt(terms.tr(
        'Чтобы записать alpha3 только в fip.old, наберите латиницей WRITE FIP.OLD: ',
        'To write alpha3 only to fip.old, type WRITE FIP.OLD: ',
    )).strip()
    if answer != 'WRITE FIP.OLD':
        ui.status(terms.tr('СТОП', 'STOP'), terms.tr('Эксперимент отменён до записи.', 'Experiment cancelled before writing.'))
        return 'CANCELLED'

    ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
        f'Записываю точный alpha3 FIP в существующий fip.old ID {target_id}. BL2 не трогаю.',
        f'Writing exact alpha3 FIP into existing fip.old ID {target_id}. BL2 is untouched.',
    ))
    write_raw = _uboot_require_ok(sp, log, f'ubi write 0x{LOADADDR:x} fip.old 0x{size:x}', 180, 'запись alpha3 FIP в fip.old')
    read_raw = _uboot_require_ok(sp, log, f'ubi read 0x{READBACK_ADDR:x} fip.old 0x{size:x}', 120, 'readback fip.old')
    cmp_raw = _uboot_require_ok(sp, log, f'cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x} 0x{size:x}', 90, 'byte compare fip.old')
    crc_old_raw, crc_old_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{size:x}', timeout=40)
    crc_old_after = _extract_crc32(_decode_uart_text(crc_old_raw)) if crc_old_rc == 0 else None

    # Verify the untouched current fip volume still contains alpha3.
    fip_read_raw = _uboot_require_ok(sp, log, f'ubi read 0x{READBACK_ADDR:x} fip 0x{size:x}', 120, 'контрольное чтение fip')
    fip_crc_raw, fip_crc_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{size:x}', timeout=40)
    fip_crc_after = _extract_crc32(_decode_uart_text(fip_crc_raw)) if fip_crc_rc == 0 else None
    if fip_crc_after != FIP_OLD_EXPERIMENT_NEW_CRC32:
        raise Error(f'После записи соседний том fip имеет CRC32 {fip_crc_after or "UNKNOWN"}, ожидался alpha3 {FIP_OLD_EXPERIMENT_NEW_CRC32}. Не выключайте питание; сохраните лог.')

    # Verify the target volume still has the same identity/type after in-place write.
    info_raw, info_rc = _uboot_command_result(sp, log, 'ubi info l', timeout=50)
    post_volumes = _parse_ubi_layout(_decode_uart_text(info_raw)) if info_rc == 0 else []
    post_by_name = {str(v.get('name', '')): v for v in post_volumes}
    post_old = post_by_name.get('fip.old')
    post_cur = post_by_name.get('fip')
    if not post_old or post_old.get('id') != target_id or post_old.get('type') != baseline.get('fip_old_type'):
        raise Error('После записи изменились ID или тип тома fip.old. Не выключайте питание; сохраните лог.')
    if not post_cur or post_cur.get('id') != baseline.get('fip_id') or post_cur.get('type') != baseline.get('fip_type'):
        raise Error('После записи изменились ID или тип тома fip. Не выключайте питание; сохраните лог.')

    # BL2 is explicitly re-read after the UBI transaction to prove it did not change.
    bl2_target = view.get('bl2_target')
    bl2_offset = int(view.get('bl2_offset') or 0)
    bl2_read_raw = _uboot_require_ok(sp, log, f'mtd read {bl2_target} 0x{READBACK_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 120, 'контрольное чтение BL2')
    bl2_crc_raw, bl2_crc_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{BL2_SIZE:x}', timeout=40)
    bl2_crc_after = _extract_crc32(_decode_uart_text(bl2_crc_raw)) if bl2_crc_rc == 0 else None
    if bl2_crc_after != baseline.get('bl2_crc32_before'):
        raise Error(f'CRC32 BL2 изменился: было {baseline.get("bl2_crc32_before")}, стало {bl2_crc_after or "UNKNOWN"}. Не выключайте питание; сохраните лог.')

    if crc_old_after != FIP_OLD_EXPERIMENT_NEW_CRC32:
        raise Error(f'fip.old после побайтового сравнения имеет CRC32 {crc_old_after or "UNKNOWN"}, ожидался alpha3 {FIP_OLD_EXPERIMENT_NEW_CRC32}. Не выключайте питание; сохраните лог.')

    lines = [
        'UrsusFlasher fip.old single-variable experiment',
        f'timestamp={time.strftime("%Y-%m-%d %H:%M:%S")}',
        'persistent_write_scope=fip.old contents only',
        f'fip_old_id_before={baseline.get("fip_old_id")}',
        f'fip_old_type_before={baseline.get("fip_old_type")}',
        f'fip_old_crc32_before={baseline.get("fip_old_crc32_before")}',
        f'fip_old_crc32_after={crc_old_after or "UNKNOWN"}',
        f'fip_id={baseline.get("fip_id")}',
        f'fip_crc32_before={baseline.get("fip_crc32_before")}',
        f'fip_crc32_after={fip_crc_after or "UNKNOWN"}',
        f'bl2_crc32_before={baseline.get("bl2_crc32_before")}',
        f'bl2_crc32_after={bl2_crc_after or "UNKNOWN"}',
        'volume_recreate=0',
        'volume_rename=0',
        'bl2_write=0',
        'saveenv=0',
        '', 'RAW_FIP_OLD_WRITE:', _decode_uart_text(write_raw),
        '', 'RAW_FIP_OLD_READBACK:', _decode_uart_text(read_raw),
        '', 'RAW_FIP_OLD_CMP:', _decode_uart_text(cmp_raw),
        '', 'RAW_FIP_OLD_CRC32:', _decode_uart_text(crc_old_raw),
        '', 'RAW_FIP_UNTOUCHED_READ:', _decode_uart_text(fip_read_raw),
        '', 'RAW_FIP_UNTOUCHED_CRC32:', _decode_uart_text(fip_crc_raw),
        '', 'RAW_UBI_INFO_AFTER:', _decode_uart_text(info_raw),
        '', 'RAW_BL2_READ_AFTER:', _decode_uart_text(bl2_read_raw),
        '', 'RAW_BL2_CRC32_AFTER:', _decode_uart_text(bl2_crc_raw),
        '',
    ]
    report_path.write_text('\n'.join(lines), encoding='utf-8')

    ui.rule(terms.tr('ЭКСПЕРИМЕНТ ЗАПИСАН И ПРОВЕРЕН', 'EXPERIMENT WRITTEN AND VERIFIED'), style='green')
    ui.status(terms.tr('ГОТОВО', 'DONE'), terms.tr(
        f'fip.old ID {target_id}: alpha4/HF6 → точный alpha3, CRC32={crc_old_after}; считанный обратно FIP побайтово совпал с исходником.',
        f'fip.old ID {target_id}: alpha4/HF6 → exact alpha3, CRC32={crc_old_after}; byte-for-byte readback PASS.',
    ))
    ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(
        f'fip ID {baseline.get("fip_id")} остался alpha3, CRC32={fip_crc_after}.',
        f'fip ID {baseline.get("fip_id")} remains alpha3, CRC32={fip_crc_after}.',
    ))
    ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(
        f'BL2 не записывался и остался CRC32={bl2_crc_after}.',
        f'BL2 was not written and remains CRC32={bl2_crc_after}.',
    ))
    ui.info(terms.tr(f'Отчёт эксперимента: {report_path}', f'Experiment report: {report_path}'))
    ui.status(terms.tr('СДЕЛАЙТЕ', 'DO THIS'), terms.tr(
        'Выключите питание на 5 секунд, затем включите БЕЗ Reset и сохраните UART-лог холодной загрузки до успешного запуска или PANIC.',
        'Power off for 5 seconds, then power on WITHOUT Reset and save the cold-boot UART through boot success or PANIC.',
    ))
    ui.note(terms.tr(
        'Если холодная загрузка пройдёт — это сильное доказательство, что ранняя цепочка использует прежний том UBI (ID 6), а не выбирает FIP только по имени. Если снова будет LZMA: res 1 — это не исключит зависимость от физического размещения PEB; следующим чистым экспериментом можно менять только BL2.',
        'If cold boot passes, that is strong evidence that the early boot chain consumes the previous UBI volume identity (ID6) rather than selecting FIP only by name. If LZMA: res 1 returns, fixed physical PEB placement remains possible because an in-place UBI update may remap PEBs; changing only BL2 is the next clean experiment.',
    ))
    ui.prompt(terms.tr('Нажмите Enter после того, как прочитали итог...', 'Press Enter after reading the result...'))
    return 'FIP_OLD_ONLY_ALPHA3'


def _uart_bootrom_fipold_experiment_flow() -> None:
    logs = ROOT / 'results'; logs.mkdir(exist_ok=True)
    print(); ui.rule(terms.tr('BOOTROM: ЭКСПЕРИМЕНТ ТОЛЬКО FIP.OLD', 'BOOTROM: FIP.OLD-ONLY EXPERIMENT'), style='red')
    require_fipold_experiment_payloads()
    port = choose_port()
    stamp = time.strftime('%Y%m%d-%H%M%S')
    log_path = logs / f'ursus-bootstrap-uart-{stamp}.log'
    baseline_path = logs / f'ursus-bootchain-state-{stamp}.txt'
    experiment_path = logs / f'ursus-fip-old-experiment-{stamp}.txt'
    sp = RecoverySerial(port)
    old_quiet = os.environ.get('URSUS_QUIET_UART_UI')
    os.environ['URSUS_QUIET_UART_UI'] = '1'
    try:
        with log_path.open('ab', buffering=0) as log:
            ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
                'Запускаю UrsusBoot 0.1.0-alpha3 из RAM. До записи проверяю UBI, fip.old/fip и BL2.',
                'Starting UrsusBoot 0.1.0-alpha3 in RAM. UBI, fip.old/fip and BL2 are checked before writing.',
            ))
            _enter_bootrom_ram_updater(
                sp, log,
                reason='До записи проверяется точное исходное состояние. Эксперимент меняет только содержимое существующего fip.old.',
                require_native=False,
            )
            view = capture_bootchain_forensics(sp, log, baseline_path)
            baseline = _require_fipold_experiment_baseline(view)
            ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(
                f'Исходное состояние совпало: fip.old ID {baseline["fip_old_id"]}=HF6, fip ID {baseline["fip_id"]}=alpha3, BL2={baseline["bl2_crc32_before"]}.',
                f'Baseline matches: fip.old ID {baseline["fip_old_id"]}=HF6, fip ID {baseline["fip_id"]}=alpha3, BL2={baseline["bl2_crc32_before"]}.',
            ))
            meta = load_fip_xmodem_emergency(sp, log)
            fipold_alpha3_experiment_transaction(sp, log, meta, view, baseline, experiment_path)
    finally:
        if old_quiet is None:
            os.environ.pop('URSUS_QUIET_UART_UI', None)
        else:
            os.environ['URSUS_QUIET_UART_UI'] = old_quiet
        sp.close()
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Исходные данные UBI/FIP/BL2: {baseline_path}', f'Baseline UBI/FIP/BL2: {baseline_path}'))
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Полный UART-лог: {log_path}', f'Full UART log: {log_path}'))


def uart_bootrom_fipold_experiment() -> None:
    _uart_bootrom_fipold_experiment_flow()


def _require_bl2_experiment_baseline(view: dict) -> dict:
    """Authorize only the observed post-fip.old-write failing state.

    Hardware has already shown that changing fip.old from HF6 to exact alpha3
    did not change the cold-boot LZMA failure.  The next A/B experiment is valid
    only when both logical FIP volumes are exact alpha3, their IDs/types are
    unchanged, and the live BL2 is still the observed non-alpha3 image.
    """
    if not view.get('ubi_target') or not view.get('bl2_target'):
        raise Error('Не удалось однозначно определить UBI и BL2. Эксперимент остановлен до записи.')
    volumes = view.get('volumes') or []
    by_name = {str(v.get('name', '')): v for v in volumes}
    old = by_name.get('fip.old')
    cur = by_name.get('fip')
    if not old or not cur:
        raise Error('Для эксперимента нужны одновременно существующие тома fip.old и fip. Ничего не записано.')
    if old.get('id') != BL2_EXPERIMENT_EXPECTED_FIP_OLD_ID or cur.get('id') != BL2_EXPERIMENT_EXPECTED_FIP_ID:
        raise Error(f'ID томов изменились: ожидались fip.old={BL2_EXPERIMENT_EXPECTED_FIP_OLD_ID}, fip={BL2_EXPERIMENT_EXPECTED_FIP_ID}. Ничего не записано.')
    if old.get('type') != 'static' or cur.get('type') != 'static':
        raise Error('Эксперимент ожидает static-тома fip.old и fip. Ничего не записано.')
    if int(old.get('used_bytes') or 0) != FIP_READ_SIZE or int(cur.get('used_bytes') or 0) != FIP_READ_SIZE:
        raise Error(f'Эксперимент ожидает fip.old и fip по {FIP_READ_SIZE} байт. Ничего не записано.')
    checks = {str(x.get('name', '')): x for x in (view.get('fip_checks') or [])}
    old_crc = str((checks.get('fip.old') or {}).get('crc32') or '').lower()
    cur_crc = str((checks.get('fip') or {}).get('crc32') or '').lower()
    if old_crc != BL2_EXPERIMENT_EXPECTED_FIP_CRC32 or cur_crc != BL2_EXPERIMENT_EXPECTED_FIP_CRC32:
        raise Error(f'Оба FIP должны быть exact alpha3 CRC32 {BL2_EXPERIMENT_EXPECTED_FIP_CRC32}; сейчас fip.old={old_crc or "UNKNOWN"}, fip={cur_crc or "UNKNOWN"}. Ничего не записано.')
    bl2_crc = str(view.get('bl2_crc32') or '').lower()
    if bl2_crc != BL2_EXPERIMENT_EXPECTED_OLD_CRC32:
        raise Error(f'BL2 имеет CRC32 {bl2_crc or "UNKNOWN"}, ожидалось исходное состояние {BL2_EXPERIMENT_EXPECTED_OLD_CRC32}. Ничего не записано.')
    return {
        'fip_old_id': old.get('id'),
        'fip_id': cur.get('id'),
        'fip_old_type': old.get('type'),
        'fip_type': cur.get('type'),
        'fip_old_crc32_before': old_crc,
        'fip_crc32_before': cur_crc,
        'bl2_crc32_before': bl2_crc,
    }


def require_bl2_experiment_payloads() -> None:
    """Gate only payloads used to boot the RAM helper and replace BL2."""
    require_ram_bootstrap_payloads()
    _require_exact_file(BL2_IMAGE, BL2_SHA256, 'UrsusBoot alpha3 BL2')
    if BL2_IMAGE.stat().st_size != BL2_SIZE:
        raise Error(f'alpha3 BL2 имеет размер {BL2_IMAGE.stat().st_size}, ожидалось {BL2_SIZE}')


def bl2_alpha3_experiment_transaction(sp: RecoverySerial, log, view: dict, baseline: dict, report_path: Path) -> str:
    """Change one persistent variable: the raw 128-KiB BL2 partition contents."""
    bl2_target = view.get('bl2_target')
    bl2_offset = int(view.get('bl2_offset') or 0)
    ubi_target = view.get('ubi_target')
    if not bl2_target or not ubi_target:
        raise Error('Безопасные цели BL2/UBI не определены. Ничего не записано.')

    ui.rule(terms.tr('ЭКСПЕРИМЕНТ: МЕНЯЕТСЯ ТОЛЬКО BL2', 'EXPERIMENT: ONLY BL2 CHANGES'), style='red')
    ui.info(terms.tr(
        f'До записи: fip.old ID {baseline["fip_old_id"]}=alpha3, fip ID {baseline["fip_id"]}=alpha3; BL2={baseline["bl2_crc32_before"]}.',
        f'Before write: fip.old ID {baseline["fip_old_id"]}=alpha3, fip ID {baseline["fip_id"]}=alpha3; BL2={baseline["bl2_crc32_before"]}.',
    ))
    ui.status(terms.tr('ВНИМАНИЕ', 'WARNING'), terms.tr(
        'Будет стёрт и записан только raw-раздел BL2 размером 128 КиБ. UBI и оба FIP не записываются, не удаляются и не переименовываются.',
        'Only the 128-KiB raw BL2 partition will be erased and written. UBI and both FIP volumes are not written, removed or renamed.',
    ))
    answer = ui.prompt(terms.tr(
        'Чтобы заменить только BL2 на exact alpha3, наберите латиницей WRITE BL2: ',
        'To replace only BL2 with exact alpha3, type WRITE BL2: ',
    )).strip()
    if answer != 'WRITE BL2':
        ui.status(terms.tr('СТОП', 'STOP'), terms.tr('Эксперимент отменён до записи.', 'Experiment cancelled before writing.'))
        return 'CANCELLED'

    # BL2 is a raw eraseblock at 0x00000000..0x0001ffff. Detach the sibling
    # UBI partition before the raw transaction; this does not modify UBI.
    _uboot_command_no_rc(sp, log, 'ubi detach', timeout=20)
    ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
        f'Стираю и записываю только BL2 ({BL2_SIZE} байт) точным alpha3 образом.',
        f'Erasing and writing only BL2 ({BL2_SIZE} bytes) with the exact alpha3 image.',
    ))
    erase_raw = _uboot_require_ok(sp, log, f'mtd erase {bl2_target} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 90, 'erase BL2')
    write_raw = _uboot_require_ok(sp, log, f'mtd write {bl2_target} 0x{BL2_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 120, 'write alpha3 BL2')
    read_raw = _uboot_require_ok(sp, log, f'mtd read {bl2_target} 0x{READBACK_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 120, 'readback alpha3 BL2')
    cmp_raw = _uboot_require_ok(sp, log, f'cmp.b 0x{BL2_ADDR:x} 0x{READBACK_ADDR:x} 0x{BL2_SIZE:x}', 60, 'byte compare alpha3 BL2')
    crc_raw, crc_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{BL2_SIZE:x}', timeout=40)
    bl2_crc_after = _extract_crc32(_decode_uart_text(crc_raw)) if crc_rc == 0 else None
    if bl2_crc_after != BL2_CRC32:
        raise Error(f'BL2 readback CRC32={bl2_crc_after or "UNKNOWN"}, ожидался exact alpha3 {BL2_CRC32}. Не выключайте питание; сохраните лог.')

    # Reattach UBI and prove both FIP logical objects remain exact alpha3 with
    # the same volume identity/type. This is post-write proof, not a new gate.
    attach_raw = _uboot_require_ok(sp, log, f'ubi part {ubi_target}', 40, 'reattach UBI after BL2 write')
    info_raw, info_rc = _uboot_command_result(sp, log, 'ubi info l', timeout=50)
    post_volumes = _parse_ubi_layout(_decode_uart_text(info_raw)) if info_rc == 0 else []
    post_by_name = {str(v.get('name', '')): v for v in post_volumes}
    post_old = post_by_name.get('fip.old')
    post_cur = post_by_name.get('fip')
    if not post_old or post_old.get('id') != baseline.get('fip_old_id') or post_old.get('type') != baseline.get('fip_old_type'):
        raise Error('После записи BL2 изменились ID или тип fip.old. Не выключайте питание; сохраните лог.')
    if not post_cur or post_cur.get('id') != baseline.get('fip_id') or post_cur.get('type') != baseline.get('fip_type'):
        raise Error('После записи BL2 изменились ID или тип fip. Не выключайте питание; сохраните лог.')

    fip_old_read = _uboot_require_ok(sp, log, f'ubi read 0x{READBACK_ADDR:x} fip.old 0x{FIP_READ_SIZE:x}', 120, 'контрольное чтение fip.old')
    fip_old_crc_raw, fip_old_crc_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{FIP_READ_SIZE:x}', timeout=40)
    fip_old_crc_after = _extract_crc32(_decode_uart_text(fip_old_crc_raw)) if fip_old_crc_rc == 0 else None
    fip_read = _uboot_require_ok(sp, log, f'ubi read 0x{READBACK_ADDR:x} fip 0x{FIP_READ_SIZE:x}', 120, 'контрольное чтение fip')
    fip_crc_raw, fip_crc_rc = _uboot_command_result(sp, log, f'crc32 0x{READBACK_ADDR:x} 0x{FIP_READ_SIZE:x}', timeout=40)
    fip_crc_after = _extract_crc32(_decode_uart_text(fip_crc_raw)) if fip_crc_rc == 0 else None
    if fip_old_crc_after != BL2_EXPERIMENT_EXPECTED_FIP_CRC32 or fip_crc_after != BL2_EXPERIMENT_EXPECTED_FIP_CRC32:
        raise Error(f'После записи BL2 FIP изменились: fip.old={fip_old_crc_after or "UNKNOWN"}, fip={fip_crc_after or "UNKNOWN"}. Не выключайте питание; сохраните лог.')

    lines = [
        'UrsusFlasher BL2 single-variable experiment',
        f'timestamp={time.strftime("%Y-%m-%d %H:%M:%S")}',
        'persistent_write_scope=BL2 raw 128KiB only',
        f'bl2_target={bl2_target}',
        f'bl2_offset=0x{bl2_offset:x}',
        f'bl2_crc32_before={baseline.get("bl2_crc32_before")}',
        f'bl2_crc32_after={bl2_crc_after or "UNKNOWN"}',
        f'bl2_alpha3_expected_crc32={BL2_CRC32}',
        f'bl2_alpha3_expected_sha256={BL2_SHA256}',
        f'fip_old_id={baseline.get("fip_old_id")}',
        f'fip_old_crc32_before={baseline.get("fip_old_crc32_before")}',
        f'fip_old_crc32_after={fip_old_crc_after or "UNKNOWN"}',
        f'fip_id={baseline.get("fip_id")}',
        f'fip_crc32_before={baseline.get("fip_crc32_before")}',
        f'fip_crc32_after={fip_crc_after or "UNKNOWN"}',
        'ubi_write=0', 'ubi_remove=0', 'ubi_create=0', 'ubi_rename=0', 'saveenv=0',
        '', 'RAW_BL2_ERASE:', _decode_uart_text(erase_raw),
        '', 'RAW_BL2_WRITE:', _decode_uart_text(write_raw),
        '', 'RAW_BL2_READBACK:', _decode_uart_text(read_raw),
        '', 'RAW_BL2_CMP:', _decode_uart_text(cmp_raw),
        '', 'RAW_BL2_CRC32:', _decode_uart_text(crc_raw),
        '', 'RAW_UBI_REATTACH:', _decode_uart_text(attach_raw),
        '', 'RAW_UBI_INFO_AFTER:', _decode_uart_text(info_raw),
        '', 'RAW_FIP_OLD_READ_AFTER:', _decode_uart_text(fip_old_read),
        '', 'RAW_FIP_OLD_CRC32_AFTER:', _decode_uart_text(fip_old_crc_raw),
        '', 'RAW_FIP_READ_AFTER:', _decode_uart_text(fip_read),
        '', 'RAW_FIP_CRC32_AFTER:', _decode_uart_text(fip_crc_raw),
        '',
    ]
    report_path.write_text('\n'.join(lines), encoding='utf-8')

    ui.rule(terms.tr('BL2 ЗАПИСАН И ПРОВЕРЕН', 'BL2 WRITTEN AND VERIFIED'), style='green')
    ui.status(terms.tr('ГОТОВО', 'DONE'), terms.tr(
        f'BL2: {baseline.get("bl2_crc32_before")} → exact alpha3 {bl2_crc_after}; 128 КиБ считаны обратно и побайтово совпали.',
        f'BL2: {baseline.get("bl2_crc32_before")} → exact alpha3 {bl2_crc_after}; all 128 KiB read back byte-for-byte.',
    ))
    ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(
        f'fip.old ID {baseline.get("fip_old_id")} и fip ID {baseline.get("fip_id")} остались exact alpha3 CRC32={BL2_EXPERIMENT_EXPECTED_FIP_CRC32}.',
        f'fip.old ID {baseline.get("fip_old_id")} and fip ID {baseline.get("fip_id")} remain exact alpha3 CRC32={BL2_EXPERIMENT_EXPECTED_FIP_CRC32}.',
    ))
    ui.info(terms.tr(f'Отчёт эксперимента: {report_path}', f'Experiment report: {report_path}'))
    ui.status(terms.tr('СДЕЛАЙТЕ', 'DO THIS'), terms.tr(
        'Выключите питание на 5 секунд, затем включите БЕЗ Reset и сохраните UART холодной загрузки до успешного запуска или PANIC.',
        'Power off for 5 seconds, then power on WITHOUT Reset and save cold-boot UART through boot success or PANIC.',
    ))
    ui.note(terms.tr(
        'Если загрузка пройдёт, BL2 был необходимой причиной текущего отказа: предыдущий тест с заменой только fip.old не помог, а этот тест меняет только BL2. Если LZMA: res 1 останется, exact alpha3 уже будет находиться в обоих FIP и в BL2; тогда надо исследовать раннее чтение UBI/PEB и физическое размещение.',
        'If boot succeeds, BL2 was a necessary cause of the current failure: the prior fip.old-only change did not help, while this test changes only BL2. If LZMA: res 1 remains, both FIP volumes and BL2 will be exact alpha3; then early UBI/PEB reads and physical placement must be investigated.',
    ))
    ui.prompt(terms.tr('Нажмите Enter после того, как прочитали итог...', 'Press Enter after reading the result...'))
    return 'BL2_ONLY_ALPHA3'


def _uart_bootrom_bl2_experiment_flow() -> None:
    logs = ROOT / 'results'; logs.mkdir(exist_ok=True)
    print(); ui.rule(terms.tr('BOOTROM: ЭКСПЕРИМЕНТ ТОЛЬКО BL2', 'BOOTROM: BL2-ONLY EXPERIMENT'), style='red')
    require_bl2_experiment_payloads()
    port = choose_port()
    stamp = time.strftime('%Y%m%d-%H%M%S')
    log_path = logs / f'ursus-bootstrap-uart-{stamp}.log'
    baseline_path = logs / f'ursus-bootchain-state-{stamp}.txt'
    experiment_path = logs / f'ursus-bl2-experiment-{stamp}.txt'
    sp = RecoverySerial(port)
    old_quiet = os.environ.get('URSUS_QUIET_UART_UI')
    os.environ['URSUS_QUIET_UART_UI'] = '1'
    try:
        with log_path.open('ab', buffering=0) as log:
            ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
                'Запускаю UrsusBoot 0.1.0-alpha3 из RAM. До записи проверяю UBI, оба FIP и текущий BL2.',
                'Starting UrsusBoot 0.1.0-alpha3 in RAM. UBI, both FIP volumes and current BL2 are checked before writing.',
            ))
            _enter_bootrom_ram_updater(
                sp, log,
                reason='До записи проверяется точное состояние после неуспешного fip.old-only эксперимента. Меняется только BL2.',
                require_native=False,
            )
            view = capture_bootchain_forensics(sp, log, baseline_path)
            baseline = _require_bl2_experiment_baseline(view)
            ui.status(terms.tr('ФАКТ', 'FACT'), terms.tr(
                f'Исходное состояние совпало: fip.old ID {baseline["fip_old_id"]}=alpha3, fip ID {baseline["fip_id"]}=alpha3, BL2={baseline["bl2_crc32_before"]}.',
                f'Baseline matches: fip.old ID {baseline["fip_old_id"]}=alpha3, fip ID {baseline["fip_id"]}=alpha3, BL2={baseline["bl2_crc32_before"]}.',
            ))
            load_bl2_xmodem_emergency(sp, log, experiment=True)
            bl2_alpha3_experiment_transaction(sp, log, view, baseline, experiment_path)
    finally:
        if old_quiet is None:
            os.environ.pop('URSUS_QUIET_UART_UI', None)
        else:
            os.environ['URSUS_QUIET_UART_UI'] = old_quiet
        sp.close()
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Исходные данные UBI/FIP/BL2: {baseline_path}', f'Baseline UBI/FIP/BL2: {baseline_path}'))
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Полный UART-лог: {log_path}', f'Full UART log: {log_path}'))


def uart_bootrom_bl2_experiment() -> None:
    _uart_bootrom_bl2_experiment_flow()

def load_bl2_xmodem_emergency(sp: RecoverySerial, log, *, experiment: bool = False) -> None:
    """Load the exact alpha3 128-KiB BL2 image to RAM and verify it."""
    if not BL2_IMAGE.is_file() or BL2_IMAGE.stat().st_size != BL2_SIZE:
        raise Error('Комплектный alpha3 BL2 отсутствует или имеет неверный размер')
    digest = sha256(BL2_IMAGE)
    if digest != BL2_SHA256:
        raise Error(f'alpha3 BL2 SHA256 mismatch: {digest} != {BL2_SHA256}')
    ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
        'Передаю точный alpha3 BL2 (128 КиБ) в RAM. NAND пока не изменяется.' if experiment else 'Передаю точный alpha3 BL2 (128 КиБ) в RAM для восстановления цепочки загрузки.',
        'Transferring exact alpha3 BL2 (128 KiB) into RAM. NAND is not modified yet.' if experiment else 'Transferring exact alpha3 BL2 (128 KiB) into RAM for boot-chain recovery.',
    ))
    _uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    _uboot_send_line(sp, f'loadx 0x{BL2_ADDR:x}')
    time.sleep(0.35)
    xmodem_send(sp, BL2_IMAGE, 'UrsusBoot alpha3 BL2', log)
    _uboot_read_until_prompt(sp, log, 45, 'loadx alpha3 BL2')
    _note_xmodem_payload_ready('alpha3 BL2 в RAM', BL2_SHA256)


def _remove_boot_volume_if_present(sp: RecoverySerial, log, name: str) -> None:
    # Emergency repair intentionally ignores ENOENT.  Any real create/write error is fatal below.
    _uboot_command_no_rc(sp, log, f'ubi remove {name}', timeout=30)


def emergency_ursusboot_transaction(sp: RecoverySerial, log, meta: dict, view: dict) -> str:
    """Restore the complete known-working alpha3 boot-chain state.

    This recovery intentionally restores the canonical alpha3 UBI/FIP state and
    the matching alpha3 BL2 together.  Success proves only that the known-good
    combination works; it does not by itself identify whether the original
    failure was caused by volume ID, volume type, UBI metadata/placement, BL2,
    or another early-boot invariant.  Forensic mode must be used first when
    root-cause evidence is required.
    """
    size = int(meta['fip_size'])
    expected = str(meta['fip_sha256']).lower()
    ubi_target = view.get('ubi_target')
    bl2_target = view.get('bl2_target')
    bl2_offset = int(view.get('bl2_offset') or 0)
    if not ubi_target:
        raise Error('UBI не подключён в режиме только чтения; восстановление остановлено до записи.')
    if not bl2_target:
        raise Error('Не удалось определить MTD для BL2; восстановление остановлено до записи.')

    print()
    ui.rule('ПОЛНОЕ ВОССТАНОВЛЕНИЕ ЦЕПОЧКИ ЗАГРУЗКИ ALPHA3', style='red')
    ui.info('В RAM уже загружены и проверены точные alpha3 FIP и BL2.')
    ui.info('Восстанавливаю штатное для alpha3 состояние UBI: fip = static volume ID 4.')
    ui.info('После проверки FIP последним восстанавливаю парный alpha3 BL2 128 КиБ.')
    ui.note('ubootenv, ubootenv2, FIT, rootfs и rootfs_data не изменяются.')
    ui.status('ВНИМАНИЕ', 'После подтверждения питание не отключать до итогового ГОТОВО.')
    answer = ui.prompt('Чтобы восстановить цепочку загрузки, наберите латиницей RECOVER URSUSBOOT: ').strip()
    if answer != 'RECOVER URSUSBOOT':
        ui.status('СТОП', 'Восстановление отменено до записи. NAND/UBI не изменялись.')
        return 'CANCELLED'

    ui.status('ШАГ', 'Подключаю UBI и возвращаю том fip в штатное для alpha3 состояние: static ID 4.')
    _uboot_command_no_rc(sp, log, 'ubi detach', timeout=20)
    _uboot_require_ok(sp, log, f'ubi part {ubi_target}', 30, 'attach UBI')
    for name in ('fip.new', 'fip.bad', 'fip.old', 'fip'):
        _remove_boot_volume_if_present(sp, log, name)
    _uboot_require_ok(sp, log, 'ubi create fip 0x100000 static 4', 60, 'создание штатного для alpha3 тома fip ID 4')

    ui.status('ШАГ', 'Записываю рабочий alpha3 FIP в UBI volume ID 4.')
    _uboot_require_ok(sp, log, f'ubi write 0x{LOADADDR:x} fip 0x{size:x}', 180, 'запись alpha3 FIP')
    _uboot_require_ok(sp, log, f'ubi read 0x{READBACK_ADDR:x} fip 0x{size:x}', 120, 'readback alpha3 FIP')
    _uboot_require_ok(sp, log, f'cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x} 0x{size:x}', 90, 'byte compare alpha3 FIP')
    ui.status('ГОТОВО', 'alpha3 FIP записан в UBI static volume ID 4 и побайтово совпал с исходником из RAM.')

    # BL2 is the final destructive step, matching the alpha3 STOCK->UBI migration contract.
    ui.status('ШАГ', 'FIP подтверждён. Последним восстанавливаю парный alpha3 BL2. НЕ ВЫКЛЮЧАЙТЕ питание.')
    _uboot_command_no_rc(sp, log, 'ubi detach', timeout=20)
    _uboot_require_ok(sp, log, f'mtd erase {bl2_target} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 90, 'erase BL2')
    _uboot_require_ok(sp, log, f'mtd write {bl2_target} 0x{BL2_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 120, 'write alpha3 BL2')
    _uboot_require_ok(sp, log, f'mtd read {bl2_target} 0x{READBACK_ADDR:x} 0x{bl2_offset:x} 0x{BL2_SIZE:x}', 120, 'readback alpha3 BL2')
    _uboot_require_ok(sp, log, f'cmp.b 0x{BL2_ADDR:x} 0x{READBACK_ADDR:x} 0x{BL2_SIZE:x}', 60, 'byte compare alpha3 BL2')
    ui.status('ГОТОВО', 'alpha3 BL2 считан обратно и побайтово совпал с исходником из RAM.')

    print()
    ui.rule('ЦЕПОЧКА ЗАГРУЗКИ ALPHA3 ВОССТАНОВЛЕНА', style='green')
    ui.status('ГОТОВО', 'UrsusBoot 0.1.0-alpha3 полностью восстановлен.')
    ui.info('FIP: UBI static volume ID 4, SHA256=' + expected)
    ui.info('BL2: 128 КиБ, SHA256=' + BL2_SHA256)
    ui.info('FIT/rootfs/rootfs_data и настройки U-Boot не изменялись.')
    ui.status('ГОТОВО', 'ПИТАНИЕ ТЕПЕРЬ МОЖНО ВЫКЛЮЧИТЬ.')
    ui.status('СДЕЛАЙТЕ', 'Выключите питание на 5 секунд и включите БЕЗ Reset.')
    ui.note('Cold-boot PASS: после DRAM FLOW DONE должен исчезнуть LZMA: res 1 / PANIC и появиться UrsusBoot 0.1.0-alpha3.')
    ui.prompt('Нажмите Enter после того, как прочитали итог...')
    return 'UBI_ID4_PLUS_BL2'

def _require_exact_file(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file() or not path.stat().st_size:
        raise Error(f'{label} отсутствует: {path}')
    actual = sha256(path)
    if actual != str(expected_sha256).lower():
        raise Error(f'{label} SHA256 mismatch: {actual} != {expected_sha256}')


def require_fip_payload() -> None:
    """Gate the ordinary production UrsusBoot FIP; emergency alpha3 is separate."""
    meta = _production_meta()
    _require_exact_file(PRODUCTION_PAYLOAD, meta['fip_sha256'], 'UrsusBoot alpha5-UBIUX1 production FIP')
    if PRODUCTION_PAYLOAD.stat().st_size >= (0x7C000 - 0x800):
        raise Error(f'FIP не помещается в STOCK окно: 0x{PRODUCTION_PAYLOAD.stat().st_size:x}')

def require_ram_bootstrap_payloads() -> None:
    """Gate only the two files required to reach a RAM U-Boot prompt."""
    meta = _ursus_meta()
    _require_exact_file(PRELOADER, meta['preloader_sha256'], 'BootROM preloader')
    _require_exact_file(RAM_INSTALLER, meta['ram_installer_fip_sha256'], 'RAM installer FIP')


def require_emergency_payloads() -> None:
    """Gate exact persistent recovery payloads only for destructive BootROM recovery."""
    meta = _ursus_meta()
    require_ram_bootstrap_payloads()
    _require_exact_file(EMERGENCY_PAYLOAD, meta['fip_sha256'], 'exact alpha3 emergency FIP')
    _require_exact_file(BL2_IMAGE, meta['bl2_image_sha256'], 'alpha3 BL2')


def _uart_port_busy(detail: str) -> bool:
    text = str(detail).lower()
    markers = (
        'winerror 5', 'winerror 32', 'access is denied', 'отказано в доступе',
        'sharing violation', 'занят другой программой', 'resource busy',
        'device or resource busy',
    )
    return any(marker in text for marker in markers)


def choose_port() -> str:
    """Select a UART and stay in-place while the chosen port is busy.

    A terminal commonly owns the same COM port immediately before a BootROM
    operation.  That is an operator-fixable condition, not an operation
    failure: explain it, wait for the operator to release the port, and retry
    the exact same selection without unwinding back to the EXPERT menu.
    """
    while True:
        ports = list_serial_ports()
        if ports:
            ui.section('UART', style='magenta'); ui.info('Обнаруженные UART-порты:')
            for i, p in enumerate(ports, 1):
                print(f'  {i}. {p}')
        else:
            ui.status('ВНИМАНИЕ', 'UART-порты автоматически не обнаружены.')

        entered = ui.prompt('UART-порт или номер в списке: ').strip()
        if entered.isdigit() and ports and 1 <= int(entered) <= len(ports):
            port = ports[int(entered) - 1]
        else:
            port = entered.upper() if os.name == 'nt' else entered
        if not port:
            raise Error('UART-порт не указан')

        while True:
            try:
                probe_serial_port(port)
                return port
            except Error as exc:
                detail = str(exc)
                if not _uart_port_busy(detail):
                    raise
                ui.status(terms.tr('ВНИМАНИЕ', 'WARNING'), terms.tr(
                    f'{port} занят другой программой.',
                    f'{port} is currently in use by another program.',
                ))
                ui.info(terms.tr(
                    f'Закройте терминал или другую программу, которая держит {port} (PuTTY, Tera Term и т. п.).',
                    f'Close the terminal or other program holding {port} (PuTTY, Tera Term, etc.).',
                ))
                ui.status(terms.tr('ЖДУ', 'WAIT'), terms.tr(
                    'UrsusFlasher остаётся на этом шаге. Никакая запись во флеш-память не начиналась.',
                    'UrsusFlasher will stay at this step. No flash write has started.',
                ))
                retry = ui.prompt(terms.tr(
                    f'Освободите {port} и нажмите Enter для повторной проверки; 0 — выбрать другой UART: ',
                    f'Release {port} and press Enter to retry; 0 — choose another UART: ',
                )).strip()
                if retry == '0':
                    break
                # Empty input (and any non-zero text) means retry the same port.
                continue


def acquire_installed_prompt(sp: RecoverySerial, log, timeout: float = 60.0) -> None:
    print('Жду режим восстановления уже установленного UrsusBoot и затем перехвачу консоль...')
    sp.reset_input()
    deadline = time.time() + timeout
    tail = bytearray()
    last_break = 0.0
    recovery_seen_at: float | None = None
    web_ready = False
    while time.time() < deadline:
        data = sp.read(4096, 0.2)
        if data:
            log.write(data); log.flush()
            print(data.decode('utf-8', 'replace'), end='', flush=True)
            tail.extend(data)
            if len(tail) > 16384:
                del tail[:-8192]
            raw = bytes(tail)
            if _uboot_prompt_present(raw):
                _uboot_wait_quiet(sp, log, quiet=0.35, timeout=2.0)
                sp.reset_input()
                print('\n[ГОТОВО] Консоль UrsusBoot перехвачена.')
                return
            low = raw.lower()
            if b'starting kernel' in low or b'booting linux on physical cpu' in low:
                raise Error('Началась обычная загрузка. Повторять запись не нужно. Для Recovery: выключите питание, включите снова, примерно через 1 секунду зажмите Reset на 5-10 секунд — до 2 коротких + 3 длинных красных миганий и постоянного красного света; затем отпустите.')
            if recovery_seen_at is None and (
                b'ursus_recovery_latched' in low or
                b'ursus_web_begin' in low or
                b'ursus_webfailsafe_ready' in low or
                b'ursus_http_listen_ok' in low
            ):
                recovery_seen_at = time.time()
            if b'ursus_webfailsafe_ready' in low or b'ursus_http_listen_ok' in low:
                web_ready = True
        now = time.time()
        # Do not spam Ctrl-C during early boot/reset measurement.  Once Recovery
        # is clearly latched (or WebFailsafe is ready), paced Ctrl-C/ESC exits the
        # Web loop into the UART shell without sending Enter.
        may_break = web_ready or (recovery_seen_at is not None and now - recovery_seen_at >= 1.0)
        if may_break and now - last_break >= 0.7:
            sp.write(b'\x03\x1b')
            last_break = now
    raise Error('Консоль UrsusBoot не получена за 60 с. Повторите Recovery: питание OFF -> ON, примерно через 1 секунду зажмите Reset на 5-10 секунд и держите до 2 коротких + 3 длинных красных миганий и постоянного красного света.')


def _uboot_command_no_rc(sp: RecoverySerial, log, command: str, timeout: int = 20) -> bytes:
    """Run a read-only capability probe without failing on command return code."""
    _uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    if os.environ.get('URSUS_QUIET_UART_UI') != '1':
        print(f'[U-Boot] {command}')
    _uboot_send_line(sp, command)
    return _uboot_read_until_prompt(sp, log, timeout, command)


def has_native_ursusupdate(sp: RecoverySerial, log) -> bool:
    """Detect the transport-independent updater before any candidate transfer."""
    transcript = _uboot_command_no_rc(sp, log, 'help ursusupdate', timeout=20)
    low = transcript.lower()
    if b"unknown command 'ursusupdate'" in low or b'unknown command "ursusupdate"' in low:
        print('[ИНФО] Установленный UrsusBoot слишком старый для штатного самообновления.')
        return False
    if (b'validate/update ursusboot fip from ram' in low or
            b'ursusupdate write <addr> <len>' in low or
            b'check <addr> <len>' in low and b'ursusupdate' in low):
        print('[ИНФО] Установленный UrsusBoot умеет обновляться сам.')
        return True
    raise Error('Не удалось однозначно определить наличие ursusupdate; NAND write запрещён.')


def load_fip_xmodem(sp: RecoverySerial, log, *, require_native: bool = True) -> None:
    size = PRODUCTION_PAYLOAD.stat().st_size
    if require_native and not has_native_ursusupdate(sp, log):
        raise Error('Установленный UrsusBoot слишком старый; требуется запуск обновляющего загрузчика из RAM.')
    print(f'Передаю production UrsusBoot FIP через XMODEM в RAM 0x{LOADADDR:08x}; FIP={size} bytes / 0x{size:x}.')
    _uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0); sp.reset_input()
    _uboot_send_line(sp, f'loadx 0x{LOADADDR:x}'); time.sleep(0.35)
    xmodem_send(sp, PRODUCTION_PAYLOAD, 'production UrsusBoot alpha5-UBIUX1 FIP', log)
    _uboot_read_until_prompt(sp, log, 45, 'loadx production UrsusBoot FIP')
    print('[OK] Production FIP передан в RAM. Валидация выполняется самим ursusupdate write перед записью.')


def commit_uart(sp: RecoverySerial, log) -> None:
    size = PRODUCTION_PAYLOAD.stat().st_size
    answer = input('\nЗаписать обновление во флеш-память? [y/N]: ').strip().lower()
    if answer not in ('y','yes','д','да'):
        print('Запись отменена. NAND не изменялась.'); return
    transcript = uboot_command(sp, log, f'ursusupdate write 0x{LOADADDR:x} 0x{size:x}', timeout=360)
    if b'URSUS_UPDATE_COMMIT_OK' not in transcript:
        raise Error('Загрузчик не подтвердил завершение записи; автоматическая перезагрузка запрещена.')
    print('\n[ГОТОВО] Загрузчик записан и считан обратно без расхождений. BL2 не изменялся. Перезагрузку выполняйте отдельно.')


def _enter_bootrom_ram_updater(sp: RecoverySerial, log, *, reason: str, require_native: bool = True) -> None:
    """Boot the selfupdate-capable RAM profile, then leave a deterministic prompt."""
    print(); ui.rule('AIROHA BOOTROM → RAM URSUSBOOT', style='red')
    ui.info(reason)
    ui.note('Установленный загрузчик для этой операции не используется.')
    ui.info('UrsusFlasher запускает точный alpha3 RAM installer через Airoha BootROM.')
    ui.status('ИНФО', 'До отдельного подтверждения RECOVER URSUSBOOT постоянная память не изменяется.')
    print(); ui.status('СДЕЛАЙТЕ', 'Подготовьте вход в Airoha BootROM:')
    ui.info('  1. ВЫКЛЮЧИТЕ питание Nokia.')
    ui.info('  2. Зажмите Reset ДО подачи питания.')
    ui.prompt('  3. Когда питание выключено и Reset уже зажат, нажмите Enter здесь...')
    sp.reset_input()
    ui.status('СДЕЛАЙТЕ', 'Теперь ВКЛЮЧИТЕ питание Nokia и держите Reset до Press x / C C C.')
    wait_bootrom_xmodem(sp, log, 'preloader', discard_stale=False)
    xmodem_send(sp, PRELOADER, 'OpenWrt AN7581 preloader (RAM)', log)
    wait_bootrom_xmodem(sp, log, 'BL31 + RAM updater FIP')
    xmodem_send(sp, RAM_INSTALLER, 'UrsusBoot alpha3 RAM installer FIP', log)
    if wait_uboot_prompt(sp, log) != 'prompt':
        raise Error('Консоль UrsusBoot из RAM не перехвачена; NAND не изменялась.')
    ver = _uboot_command_no_rc(sp, log, 'version', timeout=20)
    ui.status('UART', 'RAM U-Boot: ' + (ver.decode('utf-8', 'replace').splitlines()[1] if len(ver.decode('utf-8', 'replace').splitlines()) > 1 else 'version read'))
    if require_native and not has_native_ursusupdate(sp, log):
        raise Error('UrsusBoot в RAM не содержит ursusupdate; штатное обновление запрещено.')
    ui.status('ГОТОВО', 'UrsusBoot 0.1.0-alpha3 запущен из RAM.')


def uart_update_installed() -> None:
    require_fip_payload()
    print('\nЭтот пункт начинает работу через режим восстановления уже установленного UrsusBoot.')
    print('Если текущая версия уже умеет ursusupdate — обновление пойдёт напрямую через UART loadx/XMODEM.')
    print('Если ursusupdate ещё нет — UrsusFlasher сам переключит вас на безопасный BootROM -> RAM updater bootstrap.')
    port = choose_port(); logs = ROOT / 'results'; logs.mkdir(exist_ok=True)
    log_path = logs / f'ursus-selfupdate-uart-{time.strftime("%Y%m%d-%H%M%S")}.log'; sp = RecoverySerial(port)
    try:
        with log_path.open('ab', buffering=0) as log:
            print('\nUART открыт. Вход в обычный режим восстановления UrsusBoot:')
            print('  1) если роутер работает — перезагрузите его; при общем мигании/перезапуске индикаторов сразу зажмите Reset;')
            print('  2) держите Reset до 2 коротких + 3 длинных красных миганий и постоянного красного света; затем отпустите;')
            print('  3) если момент пропущен: питание OFF -> ON, примерно через 1 секунду зажмите Reset на 5-10 секунд до той же красной последовательности.')
            print('  Reset ДО подачи питания не зажимайте: это Airoha BootROM, а не обычное восстановление.')
            input('Нажмите Enter, когда готовы выполнить эти действия...')
            acquire_installed_prompt(sp, log)
            ver = _uboot_command_no_rc(sp, log, 'version', timeout=20)
            if has_native_ursusupdate(sp, log):
                print('\n[ШАГ] Текущий UrsusBoot поддерживает штатное обновление. Передаю FIP и затем сверяю запись.')
                load_fip_xmodem(sp, log, require_native=False)
                commit_uart(sp, log)
            else:
                print('\n[ШАГ] Установленный UrsusBoot слишком старый для штатного самообновления. Запускаю новый UrsusBoot из оперативной памяти.')
                require_ram_bootstrap_payloads()
                _enter_bootrom_ram_updater(
                    sp, log,
                    reason='На установленном UrsusBoot команда ursusupdate отсутствует; обнаружено автоматически.',
                )
                load_fip_xmodem(sp, log, require_native=False)
                print('Сохраняю ROM prefix 0x000..0x7ff и env 0x7c000..0x7ffff. После записи считываю весь mtd0 обратно для сверки.')
                commit_uart(sp, log)
    finally:
        sp.close()
    ui.status('ГОТОВО', f'UART-лог сохранён: {log_path}')


def _uart_bootrom_flow(*, recover: bool) -> None:
    logs = ROOT / 'results'; logs.mkdir(exist_ok=True)
    if recover:
        print(); ui.rule(terms.tr('BOOTROM: ВОССТАНОВЛЕНИЕ URSUSBOOT', 'BOOTROM: URSUSBOOT RECOVERY'), style='red')
        require_emergency_payloads()
    else:
        print(); ui.rule(terms.tr('BOOTROM: ПРОВЕРКА UBI И BL2', 'BOOTROM: UBI + BL2 READ-ONLY CHECK'), style='amber')
        require_ram_bootstrap_payloads()
    port = choose_port()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = logs / f'ursus-bootstrap-uart-{stamp}.log'
    forensic_path = logs / f'ursus-bootchain-state-{stamp}.txt'
    sp = RecoverySerial(port)
    old_quiet = os.environ.get('URSUS_QUIET_UART_UI')
    os.environ['URSUS_QUIET_UART_UI'] = '1'
    try:
        with log_path.open('ab', buffering=0) as log:
            print(); ui.status(terms.tr('ШАГ', 'STEP'), terms.tr(
                'Запускаю UrsusBoot 0.1.0-alpha3 из RAM через Airoha BootROM. Затем читаю UBI и BL2 без записи.',
                'Starting UrsusBoot 0.1.0-alpha3 in RAM through Airoha BootROM. Then reading UBI and BL2 without writing.',
            ))
            _enter_bootrom_ram_updater(
                sp, log,
                reason='Установленный загрузчик не используется. После запуска из RAM будут прочитаны UBI и BL2; запись не выполняется.',
                require_native=False,
            )
            view = capture_bootchain_forensics(sp, log, forensic_path)
            if not recover:
                ui.rule(terms.tr('ПРОВЕРКА UBI И BL2 ЗАВЕРШЕНА — ЗАПИСИ НЕ БЫЛО', 'UBI + BL2 CHECK COMPLETE — NO WRITE OCCURRED'), style='green')
                ui.status(terms.tr('ГОТОВО', 'READY'), terms.tr(
                    'Тома UBI и раздел BL2 не удалялись, не создавались и не переписывались.',
                    'UBI volumes and the BL2 partition were not removed, created or rewritten.',
                ))
                ui.info(terms.tr('Сохраните и передайте этот отчёт перед восстановлением:',
                                 'Save and share this report before recovery:'))
                ui.info(str(forensic_path))
                ui.prompt(terms.tr('Нажмите Enter, чтобы вернуться в меню EXPERT...',
                                   'Press Enter to return to the EXPERT menu...'))
                return

            if not view.get('ubi_target') or not view.get('bl2_target'):
                raise Error('Проверка UBI/BL2 не смогла определить безопасные цели записи; восстановление остановлено до записи.')
            # Hardware evidence from 0.2.29 disproved the old universal ID4 assumption:
            # on the observed migrated layout ID4 is bosa, while fip.old/fip are ID6/ID7.
            # Do not let the legacy fixed-ID4 transaction remove evidence and then fail.
            id4 = next((v for v in view.get('volumes', []) if v.get('id') == 4), None)
            if id4 and str(id4.get('name', '')).lower() not in ('fip', 'fip.old', 'fip.new', 'fip.bad'):
                raise Error(terms.tr(
                    f'Восстановление с фиксированным UBI ID 4 отключено: ID 4 уже занят томом «{id4.get("name")}». Ничего не записано. Сначала установите фактический boot-chain contract по результатам проверки.',
                    f'Fixed UBI ID 4 recovery is disabled: ID 4 is already occupied by volume "{id4.get("name")}". Nothing was written. Establish the actual boot-chain contract from the read-only evidence first.',
                ))
            ui.status(terms.tr('ВНИМАНИЕ', 'WARNING'), terms.tr(
                'Проверка UBI и BL2 завершена. Запись начнётся только после отдельного подтверждения RECOVER URSUSBOOT.',
                'The UBI and BL2 check is complete. Writing starts only after the separate RECOVER URSUSBOOT confirmation.',
            ))
            meta = load_fip_xmodem_emergency(sp, log)
            load_bl2_xmodem_emergency(sp, log)
            emergency_ursusboot_transaction(sp, log, meta, view)
    finally:
        if old_quiet is None:
            os.environ.pop('URSUS_QUIET_UART_UI', None)
        else:
            os.environ['URSUS_QUIET_UART_UI'] = old_quiet
        sp.close()
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Отчёт UBI/BL2: {forensic_path}', f'UBI/BL2 report: {forensic_path}'))
    ui.status(terms.tr('ИНФО', 'INFO'), terms.tr(f'Полный технический UART-лог: {log_path}', f'Full technical UART log: {log_path}'))


def uart_bootrom_forensics() -> None:
    _uart_bootrom_flow(recover=False)


def uart_bootrom_recover() -> None:
    _uart_bootrom_flow(recover=True)


def uart_bootrom_install() -> None:
    """Backward-compatible entry point: destructive recovery, with forensic capture first."""
    uart_bootrom_recover()

def web_fip_update() -> None:
    require_fip_payload(); host = input('IP-адрес роутера в режиме восстановления UrsusBoot [192.168.1.1]: ').strip() or '192.168.1.1'
    st = uw.update_bootloader(host, PRODUCTION_PAYLOAD, confirm=True)
    print(f"[ГОТОВО] UrsusBoot обновлён и сверен. Система: {terms.layout_label(st.get('bootloader_update_layout') or st.get('current_layout'))}")


def web_fit_update(image: Path | None = None) -> None:
    host = input('IP-адрес роутера в режиме восстановления UrsusBoot [192.168.1.1]: ').strip() or '192.168.1.1'
    if image is None:
        raw = input(f'Путь к FIT/sysupgrade [{DEFAULT_FIT}]: ').strip()
        image = Path(raw.strip('"')).expanduser() if raw else DEFAULT_FIT
    image = image.resolve()
    if not image.is_file(): raise Error(f'FIT/sysupgrade не найден: {image}')
    keep_settings = True
    try:
        before = uw.status(host)
    except Exception:
        before = {}
    if before.get('current_layout') == 'OPENWRT_UBI':
        answer = input('Сохранить текущие настройки OpenWrt? [Y/n]: ').strip().lower()
        keep_settings = answer not in ('n', 'no', 'н', 'нет')
        print('[ИНФО] Настройки OpenWrt: ' + ('сохранить' if keep_settings else 'очистить после проверки новой прошивки'))
    st = uw.update_firmware(host, image, confirm=True, keep_settings=keep_settings)
    _write_session_only(f"[TECH] firmware operation_stage={st.get('operation_stage')!r} operation_detail={st.get('operation_detail')!r} keep_settings={keep_settings}")
    print('[ГОТОВО] Прошивка записана и проверена.')


def tftp_update_automated() -> None:
    """TFTP is transport only; the single write command owns validation + commit."""
    require_fip_payload(); router = input('IP UrsusBoot [192.168.1.1]: ').strip() or '192.168.1.1'
    st = uw.status(router)
    print(f"[ИНФО] Режим восстановления UrsusBoot отвечает: версия {st.get('version')}, система: {terms.layout_label(st.get('current_layout'))}")
    try: auto = local_ip_for(router)
    except Exception: auto = '192.168.1.254'
    bind = input(f'IP компьютера для TFTP [{auto}]: ').strip() or auto
    result = TftpResult(); ready = threading.Event()
    th = threading.Thread(target=serve_tftp_get, args=(bind,69,PRODUCTION_PAYLOAD,TFTP_NAME,router,ready,result),
                          kwargs={'timeout':300,'maximum_block_size':4096}, daemon=True)
    th.start(); ready.wait(3)
    if not ready.is_set(): raise Error('Не удалось запустить TFTP-сервер')
    size = PRODUCTION_PAYLOAD.stat().st_size
    print('[ШАГ] Передаю FIP по TFTP через консоль UrsusBoot...')
    out = uw.console(router, f'setenv serverip {bind}; setenv ipaddr {router}; tftpboot 0x{LOADADDR:x} {TFTP_NAME}', timeout=180)
    th.join(timeout=5)
    if result.error: raise Error(f'TFTP: {result.error}')
    if result.bytes_transferred != size: raise Error(f'TFTP передал {result.bytes_transferred}, ожидалось {size}; console={out[-800:]}')
    print('[ГОТОВО] FIP передан по TFTP. Его проверка будет выполнена перед первой записью.')
    if input('Начать запись обновления? [y/N]: ').strip().lower() not in ('y','yes','д','да'): print('[СТОП] Отменено до записи. Постоянная память не изменялась.'); return
    write = uw.console(router, f'ursusupdate write 0x{LOADADDR:x} 0x{size:x}', timeout=420)
    if 'URSUS_UPDATE_COMMIT_OK' not in write: raise Error('Загрузчик не подтвердил завершение записи; перезагрузка запрещена.')
    print('[ГОТОВО] Загрузчик записан и считан обратно без расхождений. Перезагрузка остаётся ручной.')


def tftp_server_manual() -> None:
    require_fip_payload(); router = input('IP UrsusBoot [192.168.1.1]: ').strip() or '192.168.1.1'
    try: auto = local_ip_for(router)
    except Exception: auto = '192.168.1.254'
    bind = input(f'IP компьютера для TFTP [{auto}]: ').strip() or auto
    result = TftpResult(); ready = threading.Event()
    th = threading.Thread(target=serve_tftp_get, args=(bind,69,PRODUCTION_PAYLOAD,TFTP_NAME,router,ready,result),
                          kwargs={'timeout':300,'maximum_block_size':4096}, daemon=True)
    th.start(); ready.wait(3)
    if not ready.is_set(): raise Error('Не удалось запустить TFTP-сервер')
    size=PRODUCTION_PAYLOAD.stat().st_size
    print('\nВ локальной U-Boot console:')
    print(f'  setenv serverip {bind}; setenv ipaddr {router}')
    print(f'  tftpboot 0x{LOADADDR:x} {TFTP_NAME}')
    print(f'  ursusupdate write 0x{LOADADDR:x} 0x{size:x}')
    th.join()
    if result.error: raise Error(f'TFTP: {result.error}')


def show_info() -> None:
    """Diagnostic inventory only: missing/mismatched files are reported, never gated."""
    try:
        meta = _ursus_meta()
    except Exception:
        meta = {}
    firmware_manifest = (ROOT / 'config' / 'FIRMWARE_BUNDLE.json') if REPO_MODE else (HERE / 'FIRMWARE_BUNDLE.json')
    try:
        fw_info = json.loads(firmware_manifest.read_text(encoding='utf-8')) if firmware_manifest.is_file() else {}
    except Exception:
        fw_info = {}

    rows: list[tuple[str, Path, str | None]] = [
        ('Production UrsusBoot alpha5-UBIUX1 FIP', PRODUCTION_PAYLOAD, (_production_meta()).get('fip_sha256')),
        ('Emergency UrsusBoot alpha3 FIP', EMERGENCY_PAYLOAD, meta.get('fip_sha256')),
        ('BootROM preloader', PRELOADER, meta.get('preloader_sha256')),
        ('RAM installer FIP', RAM_INSTALLER, meta.get('ram_installer_fip_sha256')),
        ('alpha3 BL2', BL2_IMAGE, meta.get('bl2_image_sha256')),
    ]
    for item in fw_info.get('files', []):
        role = str(item.get('role') or item.get('path') or 'firmware')
        rel = Path(str(item.get('path') or ''))
        path = ROOT / rel
        rows.append((role, path, str(item.get('sha256') or '') or None))

    print('\nФайлы комплекта (диагностика; отсутствие файла не блокирует этот пункт):')
    seen: set[Path] = set()
    for label, path, expected in rows:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            print(f'  {label:<36} MISSING  {path}')
            continue
        size = path.stat().st_size
        digest = sha256(path)
        if expected and digest.lower() != expected.lower():
            state = 'MISMATCH'
        else:
            state = 'OK'
        print(f'  {label:<36} {state:<8} {size:>9} bytes  sha256={digest}')
    print('\n[INFO] Этот пункт ничего не записывает и не требует полного комплекта файлов.')


def main(argv: list[str] | None = None) -> int:
    ap=argparse.ArgumentParser(description='UrsusFlasher UrsusBoot transport/orchestration helper')
    ap.add_argument('mode', choices=['web','web-fit','tftp','tftp-manual','uart','bootrom-uart','info'])
    ap.add_argument('--image', type=Path)
    args=ap.parse_args(argv)
    try:
        {
            'web': web_fip_update,
            'web-fit': lambda: web_fit_update(args.image),
            'tftp': tftp_update_automated,
            'tftp-manual': tftp_server_manual,
            'uart': uart_bootrom_install,
            'bootrom-uart': uart_bootrom_install,
            'info': show_info,
        }[args.mode]()
        return 0
    except (Error, OSError, ValueError, uw.UrsusWebError) as e:
        print(f'\n[ОШИБКА] {e}', file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
