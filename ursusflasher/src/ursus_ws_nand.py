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
import socket
import threading
import time

import console_ui as ui
import ui_terms as terms
from ursus_ws_xmodem import WebSocketSerial


RAM_ADDR = 0x81800000
VERIFY_ADDR = 0x83800000
CHUNK_LIMIT = 8 * 1024 * 1024
PORT = 1069
# The `tftpput` RAM export these presets are built on first shipped in T75.
TFTPPUT_GENERATION = 75
GENERATION = re.compile(r'-t(\d+)$')
PROMPT = re.compile(rb'(?:^|[\r\n])UrsusBoot>\s*$')
NAME = re.compile(r'^[A-Za-z0-9_.-]+$')
RANGE = re.compile(r'0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+) : "([^"]+)"')
HEX64 = re.compile(rb'\b[0-9a-fA-F]{64}\b')


def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


def _tftpput_available(status: dict) -> bool:
    """Whether this UrsusBoot exports RAM over TFTP.

    A firmware that declares the capability decides for itself. Otherwise the
    `-tNN` runtime generation is compared, so a later release keeps working
    instead of being refused by an exact version match.
    """
    declared = status.get('tftpput_available')
    if isinstance(declared, bool):
        return declared
    match = GENERATION.search(str(status.get('version') or '').strip())
    return bool(match) and int(match.group(1)) >= TFTPPUT_GENERATION


def _transfer_port(preferred: int = PORT) -> int:
    """A UDP port the PC can actually bind for this transfer.

    The documented port is kept whenever it is free so firewall rules stay
    predictable; a busy one falls back instead of failing the whole preset.
    """
    for candidate in (preferred, 0):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(('', candidate))
            return int(probe.getsockname()[1])
        except OSError:
            continue
        finally:
            probe.close()
    raise RuntimeError(tr(
        'Не удалось занять ни один UDP-порт для передачи TFTP.',
        'No UDP port could be bound for the TFTP transfer.',
    ))


def _own_port(port: int | None) -> int:
    """Resolve the transfer port, naming it when this call had to choose one."""
    if port is not None:
        return port
    port = _transfer_port()
    if port == PORT:
        print(tr(f'[TFTP] Порт UDP {port}. Разрешите его в firewall ПК.',
                 f'[TFTP] UDP port {port}. Allow it in the PC firewall.'))
    else:
        print(tr(f'[TFTP] UDP {PORT} занят, использую UDP {port}. Разрешите в firewall ПК именно его.',
                 f'[TFTP] UDP {PORT} is busy, using UDP {port}. Allow this port in the PC firewall.'))
    return port


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

    def detach_ubi(self) -> None:
        """Make sure UBI is not holding the MTD; a no-op when nothing is attached."""
        try:
            self.command('ubi detach', 30)
        except RuntimeError:
            # `ubi detach` fails when there is nothing attached, which is the
            # state this call wants.  A real detach failure surfaces at the
            # first erase instead, where it is unambiguous.
            pass

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
    parts = _layout_parts(tuple(d['ranges'][1:]), status, size, erase)
    return d['name'], size, erase, page, parts


def _layout_parts(candidates: tuple[Region, ...], status: dict, size: int,
                  erase: int) -> tuple[Region, ...]:
    """Which partitions to offer, from the MTD partitions U-Boot reports.

    Shared by the console (`mtd list`) and HTTP (catalog) discovery so the two
    cannot disagree about what a stock layout means.
    """
    parts = tuple(p for p in candidates if p.size > 0 and
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
    return tuple(unique.values())


def discover(session: Session, status: dict) -> Geometry:
    if not _tftpput_available(status):
        raise RuntimeError(
            f'NAND presets need the UrsusBoot tftpput RAM export (T{TFTPPUT_GENERATION} or later); '
            f'this bootloader reports {str(status.get("version") or "no version")!r}'
        )
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


def backup(host: str, status: dict, region: Region, output: Path, *, port: int | None = None) -> None:
    from ursus_ws_tftp import receive_ram
    port = _own_port(port)
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
                    receive_ram(host, RAM_ADDR, length, chunk, port=port, link=session.link)
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


def _serve_chunk(session: Session, path: Path, length: int, digest: str, port: int) -> None:
    from proven_backend import TftpResult, local_ip_for, serve_tftp_get
    bind_ip = local_ip_for(session.host)
    remote_name = f'ursus-restore-{time.monotonic_ns():x}.bin'
    ready = threading.Event()
    result = TftpResult()
    thread = threading.Thread(target=serve_tftp_get,
                              args=(bind_ip, port, path, remote_name, session.host, ready, result),
                              kwargs={'timeout': 120}, daemon=True)
    thread.start()
    if not ready.wait(5) or result.error:
        raise RuntimeError(
            f'TFTP GET server could not serve {bind_ip}:{port}: {result.error}; '
            'check that the PC firewall allows this UDP port'
        )
    session.command(f'tftpboot 0x{RAM_ADDR:x} {bind_ip}:{port}:{remote_name}',
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


def _assert_archive_matches(meta: dict, status: dict, geo: Geometry) -> None:
    """Refuse a foreign or stale archive, naming the field that disagrees."""
    for label, want, got in (
        ('board', meta.get('board'), status.get('board')),
        ('SoC', meta.get('soc'), status.get('soc')),
        ('NAND chip', meta.get('flash_chip'), status.get('flash_chip')),
        ('NAND id', meta.get('flash_id'), status.get('flash_id')),
        ('flash size', meta.get('flash_size'), geo.size),
        ('erase size', meta.get('erase_size'), geo.erase),
        ('page size', meta.get('page_size'), geo.page),
    ):
        if want != got:
            raise RuntimeError('URSUS_NAND_ARCHIVE_FOREIGN field=' + label.replace(' ', '_') + ': ' + tr(
                f'архив снят с другого устройства: {label} в архиве {want!r}, '
                f'а на этом аппарате {got!r}. Заливка остановлена.',
                f'the archive is from a different device: {label} is {want!r} in the archive '
                f'and {got!r} on this unit. Restore stopped.',
            ))
    archived = tuple(meta.get('bad_blocks', []))
    if archived != geo.bad:
        appeared = [x for x in geo.bad if x not in archived]
        vanished = [x for x in archived if x not in geo.bad]
        detail = []
        if appeared:
            detail.append(tr(f'новых {len(appeared)}: ' + ', '.join(f'0x{x:x}' for x in appeared[:8]),
                             f'{len(appeared)} new: ' + ', '.join(f'0x{x:x}' for x in appeared[:8])))
        if vanished:
            detail.append(tr(f'пропавших {len(vanished)}', f'{len(vanished)} no longer reported'))
        raise RuntimeError('URSUS_NAND_BADBLOCK_MAP_CHANGED: ' + tr(
            'карта плохих блоков изменилась с момента снятия архива (' + '; '.join(detail) + '). '
            'Этот архив больше не описывает физическую раскладку аппарата, и заливка по нему '
            'сдвинула бы данные. Снимите свежий архив этим же меню и восстанавливайтесь с него.',
            'the bad-block map changed since the archive was taken (' + '; '.join(detail) + '). '
            'The archive no longer describes this unit physically and restoring it would shift data. '
            'Take a fresh archive with this same menu and restore from that one.',
        ))


def restore(host: str, status: dict, image: Path, *, port: int | None = None) -> None:
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
        _assert_archive_matches(meta, status, geo)
        port = _own_port(port)
        print(tr(f'ЗАЛИВКА {region.name}: 0x{region.offset:x} + 0x{region.size:x} '
                 f'из {image}\nПлата: {status.get("board")}, NAND: {geo.master} '
                 f'{geo.size >> 20} МиБ, плохих блоков {len(geo.bad)}. '
                 'OOB не восстанавливается. Прерывание записи может лишить устройство загрузки.',
                 f'RESTORE {region.name}: 0x{region.offset:x} + 0x{region.size:x} '
                 f'from {image}\nBoard: {status.get("board")}, NAND: {geo.master} '
                 f'{geo.size >> 20} MiB, {len(geo.bad)} bad blocks. '
                 'OOB is not restored. Interrupting a write can prevent boot.'))
        answer = ui.prompt(tr('Начать запись с проверкой каждого фрагмента? [y/N]: ',
                          'Start writing with readback of every chunk? [y/N]: ')).strip().lower()
        if answer not in ('y', 'yes', 'д', 'да'):
            return
        # Detach UBI before touching its backing MTD. The U-Boot session itself
        # remains in RAM and the live WebSocket is kept open.  Detach
        # unconditionally over the session already in hand: the caller's status
        # snapshot predates discover()'s own commands, and a detach with nothing
        # attached is a no-op, so asking first only adds a way to be wrong.
        session.detach_ubi()
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
                        _serve_chunk(session, chunk, length, digest, port)
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


def _tftp_note(host: str, port: int) -> None:
    from proven_backend import local_ip_for
    print(tr(f'Сеть: ПК {local_ip_for(host)} ⇄ UrsusBoot {host}, проводной Ethernet; '
             f'разрешите UDP {port} в firewall ПК. Отключите мешающие VPN/Wi-Fi интерфейсы.',
             f'Network: PC {local_ip_for(host)} ⇄ UrsusBoot {host}, wired Ethernet; '
             f'allow UDP {port} in the PC firewall. Disable interfering VPN/Wi-Fi interfaces.'))
    if port != PORT:
        print(tr(f'(UDP {PORT} сейчас занят другой программой на ПК.)',
                 f'(UDP {PORT} is currently taken by another program on the PC.)'))


def menu(host: str) -> None:
    import ursus_http_backup as hb
    from ursus_web_client import status
    st = status(host)
    # T77+ streams backups over HTTP; older UrsusBoot keeps the TFTP path.
    use_http = hb.available(st)
    if use_http:
        _master, geo = hb.discover(host, st)
    else:
        session = Session(host)
        try:
            geo = discover(session, st)
        finally:
            session.close()
    print(tr(f'NAND {geo.master}: {geo.size >> 20} МиБ, блок 0x{geo.erase:x}, '
             f'плохих блоков {len(geo.bad)}. Основная область с ECC, без OOB.',
             f'NAND {geo.master}: {geo.size >> 20} MiB, block 0x{geo.erase:x}, '
             f'{len(geo.bad)} bad blocks. ECC-corrected main area, no OOB.'))
    port = _transfer_port()
    if use_http:
        print(tr('Снятие идёт потоком по HTTP (порт 80): UDP и firewall не нужны. '
                 'Заливка идёт по TFTP.',
                 'Backups stream over HTTP (port 80): no UDP or firewall rule needed. '
                 'Restore uses TFTP.'))
    else:
        _tftp_note(host, port)
    ui.section(tr('NAND: архив и восстановление', 'NAND: backup and restore'), style='amber2')
    ui.menu_item(1, tr('Снять весь NAND', 'Back up whole NAND'))
    ui.menu_item(2, tr('Снять раздел', 'Back up partition'))
    ui.menu_item(3, tr('Залить раздел из архива', 'Restore partition archive'), write_capable=True)
    ui.menu_item(4, tr('Залить весь NAND из архива', 'Restore whole NAND archive'), write_capable=True)
    choice = ui.prompt(tr('Выбор [Enter — назад]: ', 'Choice [Enter — back]: ')).strip()
    if choice in ('1', '2'):
        if choice == '1':
            region = Region('entire-nand', 0, geo.size)
        else:
            if not geo.parts:
                raise RuntimeError('no validated partitions in this MTD layout')
            for i, p in enumerate(geo.parts, 1):
                ui.menu_item(i, p.name, f'0x{p.offset:08x} + 0x{p.size:08x}')
            index = int(ui.prompt(tr('Номер раздела [Enter — назад]: ',
                                 'Partition number [Enter — back]: ')).strip() or '0')
            if not 1 <= index <= len(geo.parts):
                return
            region = geo.parts[index - 1]
        from ursus_web_client import KIT
        default = KIT / 'work' / 'backups' / f'ursus-{region.name}-{int(time.time())}.bin'
        raw = ui.prompt(tr(f'Файл архива [{default}]: ', f'Backup file [{default}]: ')).strip().strip('"')
        target = Path(raw) if raw else default
        if use_http:
            full = ui.prompt(tr('Сверить ВЕСЬ файл прямым чтением U-Boot? Долго. [y/N, Enter — выборочно]: ',
                            'Cross-check the WHOLE file against U-Boot direct reads? Slow. '
                            '[y/N, Enter = sampled]: ')).strip().lower() in ('y', 'yes', 'д', 'да')
            hb.backup(host, st, region, target, geo=geo, verify_all=full)
        else:
            backup(host, st, region, target, port=port)
    elif choice in ('3', '4'):
        raw = ui.prompt(tr('Путь к .bin архиву (рядом должен быть .bin.json): ',
                       'Path to .bin image (matching .bin.json alongside): ')).strip().strip('"')
        if not raw:
            return
        manifest = json.loads(_metadata_path(Path(raw).expanduser()).read_text(encoding='utf-8'))
        whole = (manifest.get('region') or {}).get('name') == 'entire-nand'
        if whole != (choice == '4'):
            raise RuntimeError('selected preset does not match the archive region')
        if use_http:
            _tftp_note(host, port)
        restore(host, st, Path(raw), port=port)
