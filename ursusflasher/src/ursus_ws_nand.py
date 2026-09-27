"""Expert NAND main-area presets for the UrsusBoot live console.

The archive keeps physical offsets and a bad-block map. It is not a raw
page+OOB/OTP dump; U-Boot's ECC-corrected MTD reads are used for good blocks.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time

import ui_terms as terms
from ursus_ws_xmodem import WebSocketSerial


RAM_ADDR = 0x81800000
VERIFY_ADDR = 0x83800000
CHUNK_LIMIT = 8 * 1024 * 1024
PORT = 1069
PROMPT = re.compile(rb'(?:^|[\r\n])UrsusBoot>\s*$')
NAME = re.compile(r'^[A-Za-z0-9_.-]+$')
RANGE = re.compile(r'0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+) : "([^"]+)"')
HEX64 = re.compile(rb'\b[0-9a-fA-F]{64}\b')


def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


@dataclass(frozen=True)
class Region:
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class Geometry:
    master: str
    size: int
    erase: int
    page: int
    parts: tuple[Region, ...]
    bad: tuple[int, ...]


class Session:
    def __init__(self, host: str):
        from ursus_web_client import UrsusLiveConsole
        ws, _hello = UrsusLiveConsole.connect(host)
        self.link = WebSocketSerial(ws)
        self.host = host

    def close(self) -> None:
        self.link.close()

    def command(self, cmd: str, timeout: float = 60) -> bytes:
        # All command arguments are generated from validated geometry/filenames.
        token = f'UF_{time.monotonic_ns():x}'
        self.link.write(f'if {cmd}; then echo {token}_OK; else echo {token}_FAIL; fi\r'.encode('ascii'))
        end = time.monotonic() + timeout
        out = bytearray()
        while time.monotonic() < end:
            out.extend(self.link.read(4096, .3))
            if len(out) > 256 * 1024:
                raise RuntimeError('U-Boot command output exceeded 256 KiB')
            if PROMPT.search(out):
                if (token + '_OK').encode() in out:
                    return bytes(out)
                raise RuntimeError(f'U-Boot command failed: {cmd}\n{bytes(out)[-1000:].decode("utf-8", "replace")}')
        raise TimeoutError(f'U-Boot command did not finish: {cmd}')

    def sha(self, address: int, size: int) -> str:
        out = self.command(f'hash sha256 0x{address:x} 0x{size:x}', 90)
        matches = HEX64.findall(out)
        if not matches:
            raise RuntimeError('U-Boot did not report SHA256')
        return matches[-1].decode('ascii').lower()


def _parse_list(out: bytes, status: dict) -> tuple[str, int, int, int, tuple[Region, ...]]:
    text = out.decode('utf-8', 'replace')
    devices = []
    current = None
    for line in text.splitlines():
        match = re.match(r'^\* ([A-Za-z0-9_.-]+)$', line)
        if match:
            current = {'name': match.group(1), 'type': '', 'erase': 0, 'page': 0, 'ranges': []}
            devices.append(current)
            continue
        if current is None:
            continue
        if '  - type: ' in line:
            current['type'] = line.split('type: ', 1)[1].strip()
        if '  - block size: ' in line:
            current['erase'] = int(line.split('block size: ', 1)[1].split()[0], 16)
        if '  - min I/O: ' in line:
            current['page'] = int(line.split('min I/O: ', 1)[1].split()[0], 16)
        region = RANGE.search(line)
        if region and (line.startswith('  - 0x') or line.startswith('\t  - 0x')):
            a, b = int(region[1], 16), int(region[2], 16)
            current['ranges'].append(Region(region[3], a, b - a))
    size = int(status.get('flash_size_mib') or 0) << 20
    candidates = [d for d in devices if d['type'] == 'NAND flash' and
                  len(d['ranges']) > 0 and d['ranges'][0].size == size and
                  d['ranges'][0].name == d['name']]
    if len(candidates) != 1 or not size:
        raise RuntimeError('cannot uniquely identify the physical NAND in mtd list')
    d = candidates[0]
    erase, page = d['erase'], d['page']
    if (not erase or not page or size % erase or erase % page or
            erase != int(status.get('flash_erase_size') or 0) or
            page != int(status.get('flash_page_size') or 0)):
        raise RuntimeError('NAND geometry differs between mtd list and UrsusBoot status')
    parts = tuple(p for p in d['ranges'][1:] if p.size > 0 and
                  0 <= p.offset < size and p.offset + p.size <= size and
                  p.offset % erase == 0 and p.size % erase == 0 and NAME.fullmatch(p.name))
    # The persistent DTS may still advertise BL2+UBI while the chip holds a
    # Nokia stock layout. Do not offer those aliases as stock partitions.
    if status.get('current_layout') in ('STOCK', 'OPENWRT_STOCK_LAYOUT'):
        parts = ()
        # UrsusBoot's stock_parts diagnostic map is known for MD/AN7581.
        # MF stock partition-by-partition restore needs its own proven map.
        if 'AN7581' in str(status.get('soc')):
            parts = tuple(Region(str(n), int(off), int(length))
                          for n, off, length in status.get('stock_parts', [])
                          if NAME.fullmatch(str(n)) and 0 <= int(off) < size and
                          int(length) > 0 and int(off) + int(length) <= size and
                          int(off) % erase == 0 and int(length) % erase == 0)
    unique = {(p.name, p.offset, p.size): p for p in parts}
    return d['name'], size, erase, page, tuple(unique.values())


def discover(session: Session, status: dict) -> Geometry:
    if not str(status.get('version', '')).endswith('-t75'):
        raise RuntimeError('NAND presets require UrsusBoot T75')
    identity = (str(status.get('board') or ''), str(status.get('soc') or ''))
    if identity not in (('Nokia XG-040G-MD', 'Airoha AN7581'),
                        ('Nokia XG-040G-MF', 'Airoha AN7583')):
        raise RuntimeError(f'NAND presets are limited to identified MD/MF boards: {identity}')
    if status.get('operation_active') or status.get('bootloader_update_active'):
        raise RuntimeError('UrsusBoot has an active flash operation')
    if int(status.get('dram_mib') or 0) < 128:
        raise RuntimeError('not enough verified DRAM for two separate 8 MiB buffers')
    master, size, erase, page, parts = _parse_list(session.command('mtd list'), status)
    out = session.command(f'mtd bad {master}', 120).decode('utf-8', 'replace')
    if f'MTD device {master} bad blocks list:' not in out:
        raise RuntimeError('could not obtain the NAND bad-block map')
    bad = tuple(sorted({int(n, 16) for n in re.findall(r'^\s+0x([0-9a-fA-F]+)\s*$', out, re.M)}))
    if any(n < 0 or n >= size or n % erase for n in bad):
        raise RuntimeError('bad-block map has invalid offsets')
    if len(bad) != int(status.get('bad_blocks') or 0):
        raise RuntimeError('bad-block count differs from UrsusBoot status')
    return Geometry(master, size, erase, page, parts, bad)


def _runs(region: Region, geo: Geometry) -> list[tuple[int, int]]:
    if region.offset % geo.erase or region.size % geo.erase or region.size <= 0:
        raise ValueError('region is not eraseblock aligned')
    bad = set(geo.bad)
    runs: list[tuple[int, int]] = []
    for off in range(region.offset, region.offset + region.size, geo.erase):
        if off in bad:
            continue
        if runs and runs[-1][0] + runs[-1][1] == off and runs[-1][1] + geo.erase <= CHUNK_LIMIT:
            start, length = runs[-1]
            runs[-1] = (start, length + geo.erase)
        else:
            runs.append((off, geo.erase))
    return runs


def _metadata_path(image: Path) -> Path:
    return image.with_name(image.name + '.json')


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def backup(host: str, status: dict, region: Region, output: Path) -> None:
    from ursus_ws_tftp import receive_ram
    output = output.expanduser().resolve()
    manifest = _metadata_path(output)
    partial = output.with_name(output.name + '.partial')
    if any(p.exists() for p in (output, manifest, partial)):
        raise FileExistsError('image, manifest or partial file already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    session = Session(host)
    try:
        geo = discover(session, status)
        if region.name == 'entire-nand':
            region = Region(region.name, 0, geo.size)
        elif region not in geo.parts:
            raise RuntimeError('selected partition is absent from the current MTD layout')
        if shutil.disk_usage(output.parent).free < region.size + 16 * 1024 * 1024:
            raise RuntimeError('not enough free space on the PC for this NAND backup')
        print(tr(f'Читаю {region.name}: 0x{region.offset:x} + 0x{region.size:x}, '
                 f'плохих блоков {len(geo.bad)}. OOB не входит.',
                 f'Reading {region.name}: 0x{region.offset:x} + 0x{region.size:x}, '
                 f'{len(geo.bad)} bad blocks. OOB is excluded.'))
        runs = _runs(region, geo)
        bad = set(geo.bad)
        h = hashlib.sha256()
        pos = region.offset
        with partial.open('wb') as dest:
            for off, length in runs:
                while pos < off:
                    if pos not in bad:
                        raise RuntimeError('good NAND block was not scheduled for reading')
                    fill = b'\xff' * geo.erase
                    dest.write(fill)
                    h.update(fill)
                    pos += geo.erase
                session.command(f'mtd read {geo.master} 0x{RAM_ADDR:x} 0x{off:x} 0x{length:x}',
                                max(90, length // 20000))
                chunk = output.with_name(output.name + f'.chunk-{off:08x}')
                try:
                    receive_ram(host, RAM_ADDR, length, chunk, link=session.link)
                    with chunk.open('rb') as source:
                        for data in iter(lambda: source.read(1024 * 1024), b''):
                            dest.write(data)
                            h.update(data)
                finally:
                    chunk.unlink(missing_ok=True)
                pos = off + length
                print(f'[NAND] 0x{pos - region.offset:x}/0x{region.size:x}')
            while pos < region.offset + region.size:
                if pos not in bad:
                    raise RuntimeError('unread good NAND block')
                fill = b'\xff' * geo.erase
                dest.write(fill)
                h.update(fill)
                pos += geo.erase
            dest.flush()
            os.fsync(dest.fileno())
        if partial.stat().st_size != region.size:
            raise RuntimeError('backup image has an unexpected length')
        meta = {
            'schema': 1, 'format': 'ursus-nand-main-area-ecc',
            'region': {'name': region.name, 'offset': region.offset, 'size': region.size},
            'board': status.get('board'), 'soc': status.get('soc'),
            'flash_chip': status.get('flash_chip'), 'flash_id': status.get('flash_id'),
            'flash_size': geo.size, 'erase_size': geo.erase, 'page_size': geo.page,
            'bad_blocks': list(geo.bad), 'sha256': h.hexdigest(),
            'oob': False, 'bad_block_fill': 'ff', 'ursusboot_version': status.get('version'),
        }
        tmpmeta = manifest.with_name(manifest.name + '.partial')
        tmpmeta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(partial, output)
        os.replace(tmpmeta, manifest)
        print(tr(f'[ГОТОВО] {output} и {manifest}; SHA256 {meta["sha256"]}',
                 f'[DONE] {output} and {manifest}; SHA256 {meta["sha256"]}'))
    finally:
        session.close()
        partial.unlink(missing_ok=True)
        manifest.with_name(manifest.name + '.partial').unlink(missing_ok=True)


def _serve_chunk(session: Session, path: Path, length: int, digest: str) -> None:
    from proven_backend import TftpResult, local_ip_for, serve_tftp_get
    bind_ip = local_ip_for(session.host)
    remote_name = f'ursus-restore-{time.monotonic_ns():x}.bin'
    ready = threading.Event()
    result = TftpResult()
    thread = threading.Thread(target=serve_tftp_get,
                              args=(bind_ip, PORT, path, remote_name, session.host, ready, result),
                              kwargs={'timeout': 120}, daemon=True)
    thread.start()
    if not ready.wait(5) or result.error:
        raise RuntimeError(f'TFTP GET server failed: {result.error}')
    session.command(f'tftpboot 0x{RAM_ADDR:x} {bind_ip}:{PORT}:{remote_name}',
                    max(120, length // 10000))
    thread.join(timeout=10)
    if thread.is_alive() or result.error or result.bytes_transferred != length:
        raise RuntimeError(f'TFTP GET incomplete: {result.bytes_transferred}/{length}, {result.error}')
    if session.sha(RAM_ADDR, length) != digest:
        raise RuntimeError('UrsusBoot RAM SHA256 differs from the PC chunk')


def _current_bad(session: Session, master: str) -> tuple[int, ...]:
    report = session.command(f'mtd bad {master}', 120)
    if f'MTD device {master} bad blocks list:'.encode() not in report:
        raise RuntimeError('could not recheck the NAND bad-block map')
    return tuple(sorted({int(n, 16) for n in re.findall(
        rb'^\s+0x([0-9a-fA-F]+)\s*$', report, re.M)}))


def restore(host: str, status: dict, image: Path) -> None:
    image = image.expanduser().resolve()
    meta = json.loads(_metadata_path(image).read_text(encoding='utf-8'))
    region_data = meta.get('region') or {}
    region = Region(str(region_data.get('name')), int(region_data.get('offset')),
                    int(region_data.get('size')))
    if meta.get('schema') != 1 or meta.get('format') != 'ursus-nand-main-area-ecc':
        raise RuntimeError('unsupported NAND backup manifest')
    if (not image.is_file() or image.stat().st_size != region.size or
            _hash_file(image) != meta.get('sha256')):
        raise RuntimeError('NAND image size or SHA256 does not match its manifest')
    session = Session(host)
    try:
        geo = discover(session, status)
        if (region != Region('entire-nand', 0, geo.size) and region not in geo.parts):
            raise RuntimeError('backup region is not present in the current layout')
        if (meta.get('board') != status.get('board') or meta.get('soc') != status.get('soc') or
                meta.get('flash_chip') != status.get('flash_chip') or
                meta.get('flash_id') != status.get('flash_id') or
                meta.get('flash_size') != geo.size or meta.get('erase_size') != geo.erase or
                meta.get('page_size') != geo.page or tuple(meta.get('bad_blocks', [])) != geo.bad):
            raise RuntimeError('board, NAND geometry or bad-block map differs from backup')
        print(tr(f'ЗАЛИВКА {region.name}: 0x{region.offset:x} + 0x{region.size:x} '
                 f'из {image}\nПлата: {status.get("board")}, NAND: {geo.master} '
                 f'{geo.size >> 20} МиБ, плохих блоков {len(geo.bad)}. '
                 'OOB не восстанавливается. Прерывание записи может лишить устройство загрузки.',
                 f'RESTORE {region.name}: 0x{region.offset:x} + 0x{region.size:x} '
                 f'from {image}\nBoard: {status.get("board")}, NAND: {geo.master} '
                 f'{geo.size >> 20} MiB, {len(geo.bad)} bad blocks. '
                 'OOB is not restored. Interrupting a write can prevent boot.'))
        answer = input(tr('Начать запись с проверкой каждого фрагмента? [y/N]: ',
                          'Start writing with readback of every chunk? [y/N]: ')).strip().lower()
        if answer not in ('y', 'yes', 'д', 'да'):
            return
        # Detach UBI before touching its backing MTD. The U-Boot session itself
        # remains in RAM and the live WebSocket is kept open.
        session.command('ubi detach', 30) if status.get('ubi_attached') else None
        runs = _runs(region, geo)
        # The boot area is written last during a whole-chip restore.
        if region.name == 'entire-nand':
            runs.sort(key=lambda pair: pair[0] == 0)
        chunk = image.with_name(image.name + '.restore-chunk')
        if chunk.exists():
            raise FileExistsError(chunk)
        try:
            with image.open('rb') as source:
                for off, length in runs:
                    source.seek(off - region.offset)
                    data = source.read(length)
                    if len(data) != length:
                        raise RuntimeError('short source image')
                    digest = hashlib.sha256(data).hexdigest()
                    chunk.write_bytes(data)
                    try:
                        _serve_chunk(session, chunk, length, digest)
                    finally:
                        chunk.unlink(missing_ok=True)
                    # The generic U-Boot mtd writer skips marked bad blocks.
                    # Write only one eraseblock at a time, and check BBT around
                    # it so a new bad block cannot shift a whole chunk.
                    for block_off in range(off, off + length, geo.erase):
                        ram = RAM_ADDR + block_off - off
                        block = data[block_off - off:block_off - off + geo.erase]
                        block_hash = hashlib.sha256(block).hexdigest()
                        session.command(f'mtd erase {geo.master} 0x{block_off:x} 0x{geo.erase:x}', 120)
                        if _current_bad(session, geo.master) != geo.bad:
                            raise RuntimeError('NAND bad-block map changed during erase; restore stopped')
                        session.command(f'mtd write {geo.master} 0x{ram:x} 0x{block_off:x} 0x{geo.erase:x}', 120)
                        if _current_bad(session, geo.master) != geo.bad:
                            raise RuntimeError('NAND bad-block map changed during write; restore stopped')
                        session.command(f'mtd read {geo.master} 0x{VERIFY_ADDR:x} 0x{block_off:x} 0x{geo.erase:x}', 120)
                        if session.sha(VERIFY_ADDR, geo.erase) != block_hash:
                            raise RuntimeError(f'NAND readback differs at physical offset 0x{block_off:x}')
                    print(f'[NAND] verified 0x{off:x} + 0x{length:x}')
        finally:
            chunk.unlink(missing_ok=True)
        print(tr('[ГОТОВО] Все записанные фрагменты прошли чтение и SHA256.',
                 '[DONE] Every written chunk passed readback and SHA256.'))
    finally:
        session.close()


def menu(host: str) -> None:
    from proven_backend import local_ip_for
    from ursus_web_client import status
    st = status(host)
    session = Session(host)
    try:
        geo = discover(session, st)
    finally:
        session.close()
    print(tr(f'NAND {geo.master}: {geo.size >> 20} МиБ, блок 0x{geo.erase:x}, '
             f'плохих блоков {len(geo.bad)}. Основная область с ECC, без OOB.',
             f'NAND {geo.master}: {geo.size >> 20} MiB, block 0x{geo.erase:x}, '
             f'{len(geo.bad)} bad blocks. ECC-corrected main area, no OOB.'))
    print(tr(f'Сеть: ПК {local_ip_for(host)} ⇄ UrsusBoot {host}, проводной Ethernet; '
             f'разрешите UDP {PORT} в firewall ПК. Отключите мешающие VPN/Wi-Fi интерфейсы.',
             f'Network: PC {local_ip_for(host)} ⇄ UrsusBoot {host}, wired Ethernet; '
             f'allow UDP {PORT} in the PC firewall. Disable interfering VPN/Wi-Fi interfaces.'))
    print(tr('1 Снять весь NAND · 2 Снять раздел · 3 Залить раздел из архива · '
             '4 Залить весь NAND из архива',
             '1 Back up whole NAND · 2 Back up partition · 3 Restore partition archive · '
             '4 Restore whole NAND archive'))
    choice = input(tr('Выбор [Enter — назад]: ', 'Choice [Enter — back]: ')).strip()
    if choice in ('1', '2'):
        if choice == '1':
            region = Region('entire-nand', 0, geo.size)
        else:
            if not geo.parts:
                raise RuntimeError('no validated partitions in this MTD layout')
            for i, p in enumerate(geo.parts, 1):
                print(f'{i:2}. {p.name:24} 0x{p.offset:08x} + 0x{p.size:08x}')
            index = int(input(tr('Номер раздела [Enter — назад]: ',
                                 'Partition number [Enter — back]: ')).strip() or '0')
            if not 1 <= index <= len(geo.parts):
                return
            region = geo.parts[index - 1]
        from ursus_web_client import KIT
        default = KIT / 'work' / 'backups' / f'ursus-{region.name}-{int(time.time())}.bin'
        raw = input(tr(f'Файл архива [{default}]: ', f'Backup file [{default}]: ')).strip().strip('"')
        backup(host, st, region, Path(raw) if raw else default)
    elif choice in ('3', '4'):
        raw = input(tr('Путь к .bin архиву (рядом должен быть .bin.json): ',
                       'Path to .bin image (matching .bin.json alongside): ')).strip().strip('"')
        if not raw:
            return
        manifest = json.loads(_metadata_path(Path(raw).expanduser()).read_text(encoding='utf-8'))
        whole = (manifest.get('region') or {}).get('name') == 'entire-nand'
        if whole != (choice == '4'):
            raise RuntimeError('selected preset does not match the archive region')
        restore(host, st, Path(raw))
