"""NAND backup by streaming over UrsusBoot's recovery HTTP server (t77+).

One HTTP request per dump: the router reads flash as the connection drains, so
there is no RAM staging, no TFTP receiver on this PC and no UDP port to open.
Discovery comes from `GET /api/backup/catalog`, not from parsing `mtd list`.

The archive is the same pair the console presets write -- a `.bin` with
physical offsets and 0xFF for bad eraseblocks, plus a `.bin.json` -- so the
existing restore accepts it unchanged.  Main area only, ECC-corrected: no OOB,
no OTP, and the real content of a bad block is not recovered.

Two things still use the WebSocket console and so cannot overlap the download
(UrsusBoot refuses every other HTTP request while the console is connected):
the bad-block list, and an independent check of the downloaded file against
U-Boot's own `mtd read` + `hash sha256`.  The stream is produced by different
firmware code than that check, which is the point of it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import shutil
import time
from typing import Callable

import ui_terms as terms
import ursus_ws_nand as nand
from ursus_ws_nand import Geometry, Region

# The catalog and the main-loop stream first shipped in T77.  t76 has the
# endpoint but produces the body inside lwIP callbacks and must not be used.
GENERATION = 77
READ_BLOCK = 1 << 20
MAX_ATTEMPTS = 6
# The router aborts a stream that makes no progress for 60 s; wait a little
# longer than that for a stuck predecessor to be released before giving up.
BUSY_WAIT = 75.0
SAMPLED_BLOCKS = 24


# 409 reasons that clear by themselves: a previous stream still being torn
# down, the live console a moment after it closed, a flash pass finishing.
_TRANSIENT = ('stream', 'control plane', 'servicing the network')


class BackupError(RuntimeError):
    """A failure that retrying will not fix."""


class _Retry(Exception):
    """A transfer failure worth another attempt (the router is fine)."""


class _Busy(_Retry):
    """The router still holds a previous stream."""


def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


def available(status: dict) -> bool:
    """Whether this UrsusBoot serves the catalog and the main-loop stream."""
    declared = status.get('http_backup_available')
    if isinstance(declared, bool):
        return declared
    match = nand.GENERATION.search(str(status.get('version') or '').strip())
    return bool(match) and int(match.group(1)) >= GENERATION


# --------------------------------------------------------------- catalog ----

@dataclass(frozen=True)
class Device:
    name: str
    root: str
    offset: int
    size: int
    erase: int
    page: int
    whole: bool


@dataclass(frozen=True)
class Catalog:
    devices: tuple[Device, ...]
    ubi_attached: bool
    volumes: tuple[tuple[str, int], ...]   # (name, size)


def parse_catalog(data: object) -> Catalog:
    """Validate the catalog JSON; anything unexpected is an error, not a guess."""
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise BackupError('unsupported catalog schema')
    devices = []
    for raw in data.get('mtd') or []:
        try:
            dev = Device(str(raw['name']), str(raw['root']), int(raw['offset']),
                         int(raw['size']), int(raw['erase']), int(raw['page']),
                         bool(raw['whole']))
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(f'malformed catalog entry: {raw!r}') from exc
        if not (nand.NAME.fullmatch(dev.name) and nand.NAME.fullmatch(dev.root)):
            raise BackupError(f'unsafe name in catalog: {dev.name!r}')
        if dev.size <= 0 or dev.erase <= 0 or dev.offset < 0:
            raise BackupError(f'implausible catalog entry: {dev}')
        devices.append(dev)
    ubi = data.get('ubi') or {}
    volumes = tuple((str(v['name']), int(v['size'])) for v in (ubi.get('volumes') or [])
                    if nand.NAME.fullmatch(str(v.get('name', ''))))
    return Catalog(tuple(devices), bool(ubi.get('attached')), volumes)


def fetch_catalog(host: str, *, port: int = 80, timeout: float = 10.0) -> Catalog:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request('GET', '/api/backup/catalog', headers={'Connection': 'close'})
        resp = conn.getresponse()
        body = resp.read(256 * 1024)
    finally:
        conn.close()
    if resp.status != 200:
        raise BackupError(f'catalog refused: HTTP {resp.status} {_reason(body)}')
    try:
        return parse_catalog(json.loads(body))
    except ValueError as exc:
        raise BackupError('catalog is not valid JSON') from exc


def _reason(body: bytes) -> str:
    try:
        return str(json.loads(body).get('reason') or '')
    except (ValueError, AttributeError):
        return body[:120].decode('utf-8', 'replace')


def plan(status: dict, catalog: Catalog) -> tuple[Device, tuple[Region, ...]]:
    """The whole NAND device and the partitions worth offering on it.

    The device is the one whose size, erase size and page size all agree with
    UrsusBoot's own status; anything ambiguous is refused rather than picked.
    """
    size = int(status.get('flash_size_mib') or 0) << 20
    erase = int(status.get('flash_erase_size') or 0)
    page = int(status.get('flash_page_size') or 0)
    wholes = [d for d in catalog.devices if d.whole and d.offset == 0 and
              d.size == size and d.erase == erase and d.page == page]
    if not size or len(wholes) != 1:
        raise BackupError('cannot uniquely identify the physical NAND in the catalog')
    master = wholes[0]
    children = tuple(Region(d.name, d.offset, d.size) for d in catalog.devices
                     if not d.whole and d.root == master.name)
    return master, nand._layout_parts(children, status, master.size, master.erase)


def read_bad_blocks(host: str, master: Device, status: dict) -> tuple[int, ...]:
    """The bad-eraseblock list, from the console (the catalog does no flash I/O)."""
    session = nand.Session(host)
    try:
        bad = nand._current_bad(session, master.name)
    finally:
        session.close()
    if any(n < 0 or n >= master.size or n % master.erase for n in bad):
        raise BackupError('bad-block map has invalid offsets')
    if len(bad) != int(status.get('bad_blocks') or 0):
        raise BackupError('bad-block count differs from UrsusBoot status')
    return bad


def discover(host: str, status: dict) -> tuple[Device, Geometry]:
    """Everything a backup needs to know about this unit, before any download."""
    if not available(status):
        raise BackupError(
            f'HTTP backup needs UrsusBoot T{GENERATION} or later; this bootloader '
            f'reports {str(status.get("version") or "no version")!r}')
    identity = (str(status.get('board') or ''), str(status.get('soc') or ''))
    if identity not in (('Nokia XG-040G-MD', 'Airoha AN7581'),
                        ('Nokia XG-040G-MF', 'Airoha AN7583')):
        raise BackupError(f'backup is limited to identified MD/MF boards: {identity}')
    if status.get('operation_active') or status.get('bootloader_update_active'):
        raise BackupError('UrsusBoot has an active flash operation')
    catalog = fetch_catalog(host)
    master, parts = plan(status, catalog)
    bad = read_bad_blocks(host, master, status)
    return master, Geometry(master.name, master.size, master.erase, master.page, parts, bad)


# -------------------------------------------------------------- download ----

def _hash_prefix(path: Path, length: int) -> 'hashlib._Hash':
    h = hashlib.sha256()
    left = length
    with path.open('rb') as stream:
        while left:
            part = stream.read(min(READ_BLOCK, left))
            if not part:
                raise BackupError('partial file is shorter than its recorded length')
            h.update(part)
            left -= len(part)
    return h


def _stream(host: str, port: int, master: str, offset: int, size: int, partial: Path,
            hasher: 'hashlib._Hash', progress: Callable[[int], None] | None) -> int:
    """One request for [offset, offset+size); returns the bytes appended."""
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.request('GET', f'/api/backup/mtd/{master}?offset={offset}&size={size}',
                     headers={'Connection': 'close'})
        resp = conn.getresponse()
        if resp.status != 200:
            reason = _reason(resp.read(4096))
            if resp.status == 409 and any(k in reason for k in _TRANSIENT):
                raise _Busy(reason)
            if resp.status == 409:
                raise BackupError(f'UrsusBoot refused the backup: {reason}')
            raise BackupError(f'UrsusBoot refused the backup: HTTP {resp.status} {reason}')
        if int(resp.getheader('Content-Length') or -1) != size:
            raise BackupError('UrsusBoot announced an unexpected length')
        got = 0
        with partial.open('ab') as out:
            while got < size:
                chunk = resp.read(min(READ_BLOCK, size - got))
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                got += len(chunk)
                if progress:
                    progress(len(chunk))
            out.flush()
            os.fsync(out.fileno())
        if got != size:
            raise _Retry(f'the connection ended after {got} of {size} bytes')
        return got
    except (OSError, http.client.HTTPException) as exc:
        raise _Retry(str(exc)) from exc
    finally:
        conn.close()


def _settle(partial: Path, erase: int) -> int:
    """Trust only whole eraseblocks: drop a torn tail, return the kept length."""
    have = partial.stat().st_size if partial.exists() else 0
    keep = have - have % erase
    if keep != have:
        with partial.open('r+b') as f:
            f.truncate(keep)
    return keep


def download(host: str, master: str, offset: int, size: int, erase: int, partial: Path, *,
             port: int = 80, progress: Callable[[int], None] | None = None,
             attempts: int = MAX_ATTEMPTS, sleep: Callable[[float], None] = time.sleep) -> str:
    """Stream the range into `partial`, resuming after any failure; returns SHA-256.

    Resume is by `offset`/`size` at eraseblock granularity -- the router has no
    HTTP Range support -- so the kept prefix is re-hashed and the rest re-read.
    """
    have = _settle(partial, erase)
    if have > size:
        raise BackupError('partial file is longer than the requested range')
    hasher = _hash_prefix(partial, have) if have else hashlib.sha256()
    if progress and have:
        progress(have)
    failures = 0
    busy_until = time.monotonic() + BUSY_WAIT
    while have < size:
        try:
            have += _stream(host, port, master, offset + have, size - have, partial, hasher, progress)
        except _Busy as exc:
            if time.monotonic() >= busy_until:
                raise BackupError(f'UrsusBoot still holds another backup stream: {exc}') from exc
            sleep(3)
        except _Retry as exc:
            failures += 1
            if failures >= attempts:
                raise BackupError(f'download failed after {failures} attempts: {exc}') from exc
            print(tr(f'[NAND] обрыв ({exc}); продолжаю с уже записанного',
                     f'[NAND] interrupted ({exc}); resuming from what is on disk'))
            have = _settle(partial, erase)
            hasher = _hash_prefix(partial, have) if have else hashlib.sha256()
            sleep(min(2 * failures, 10))
    return hasher.hexdigest()


# ---------------------------------------------------------------- verify ----

def _slice_hash(path: Path, start: int, length: int) -> str:
    with path.open('rb') as stream:
        stream.seek(start)
        return hashlib.sha256(stream.read(length)).hexdigest()


def check_bad_fill(path: Path, region: Region, geo: Geometry) -> None:
    """Every bad eraseblock of the region must be exactly 0xFF in the file."""
    blank = b'\xff' * geo.erase
    with path.open('rb') as stream:
        for off in geo.bad:
            if region.offset <= off < region.offset + region.size:
                stream.seek(off - region.offset)
                if stream.read(geo.erase) != blank:
                    raise BackupError(f'bad eraseblock 0x{off:x} is not 0xFF in the file')


def choose_blocks(region: Region, geo: Geometry, samples: int | None) -> list[int]:
    """Good eraseblocks to cross-check: the first, the last and a seeded spread."""
    bad = set(geo.bad)
    good = [o for o in range(region.offset, region.offset + region.size, geo.erase) if o not in bad]
    if not good:
        return []
    if samples is None or samples >= len(good):
        return good
    picked = {good[0], good[-1]}
    rng = random.Random(region.size ^ region.offset)
    picked.update(rng.sample(good, min(max(samples - 2, 0), len(good))))
    return sorted(picked)


def cross_check(host: str, region: Region, geo: Geometry, path: Path,
                blocks: list[int]) -> int:
    """Compare eraseblocks of the file with U-Boot's own `mtd read` + `hash`.

    A skipped or repeated span in the stream shifts everything after it, so even
    a modest sample catches that class of fault.  It is a sample, not a proof:
    pass every good block to verify the whole file.
    """
    if not blocks:
        return 0
    session = nand.Session(host)
    try:
        for i, off in enumerate(blocks, 1):
            session.command(f'mtd read {geo.master} 0x{nand.RAM_ADDR:x} 0x{off:x} 0x{geo.erase:x}', 120)
            want = session.sha(nand.RAM_ADDR, geo.erase)
            got = _slice_hash(path, off - region.offset, geo.erase)
            if want != got:
                raise BackupError(
                    f'the file differs from a direct read at physical offset 0x{off:x}; '
                    f'block {i} of {len(blocks)} checked')
    finally:
        session.close()
    return len(blocks)


# ---------------------------------------------------------------- backup ----

def _progress_printer(total: int) -> Callable[[int], None]:
    done = 0
    started = time.monotonic()
    last = 0.0

    def tick(n: int) -> None:
        nonlocal done, last
        done += n
        now = time.monotonic()
        if now - last >= 1.0 or done >= total:
            last = now
            rate = done / max(now - started, 1e-6) / (1 << 20)
            print(f'[NAND] {done * 100 // total:3d}%  {done >> 20}/{total >> 20} MiB  {rate:.1f} MiB/s')

    return tick


def _identity(status: dict, geo: Geometry, region: Region) -> dict:
    return {'board': status.get('board'), 'soc': status.get('soc'),
            'flash_id': status.get('flash_id'), 'master': geo.master,
            'offset': region.offset, 'size': region.size, 'erase': geo.erase,
            'bad_blocks': list(geo.bad)}


def _claim_partial(partial: Path, ident: dict) -> None:
    """Resume a leftover .partial only if it was started for exactly this request.

    Resuming bytes that belong to another region, board or bad-block map would
    produce a well-formed archive of the wrong data.
    """
    sidecar = partial.with_name(partial.name + '.json')
    if partial.exists():
        try:
            recorded = json.loads(sidecar.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            recorded = None
        if recorded != ident:
            raise BackupError(
                f'{partial} is left over from a different request; delete it (and '
                f'{sidecar.name}) to start over')
    sidecar.write_text(json.dumps(ident, sort_keys=True) + '\n', encoding='utf-8')


def backup(host: str, status: dict, region: Region, output: Path, *,
           geo: Geometry | None = None, verify_all: bool = False, port: int = 80,
           samples: int = SAMPLED_BLOCKS) -> None:
    output = output.expanduser().resolve()
    manifest = nand._metadata_path(output)
    partial = output.with_name(output.name + '.partial')
    if output.exists() or manifest.exists():
        raise FileExistsError('image or manifest already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    if geo is None:
        _master, geo = discover(host, status)
    if region.name == 'entire-nand':
        region = Region(region.name, 0, geo.size)
    elif region not in geo.parts:
        raise BackupError('selected partition is absent from the current layout')
    if shutil.disk_usage(output.parent).free < region.size + 16 * 1024 * 1024:
        raise BackupError('not enough free space on the PC for this NAND backup')

    _claim_partial(partial, _identity(status, geo, region))
    print(nand.tr(f'Читаю {region.name}: 0x{region.offset:x} + 0x{region.size:x}, '
                  f'плохих блоков {len(geo.bad)}. Потоком по HTTP; OOB не входит.',
                  f'Reading {region.name}: 0x{region.offset:x} + 0x{region.size:x}, '
                  f'{len(geo.bad)} bad blocks. Streamed over HTTP; OOB is excluded.'))
    digest = download(host, geo.master, region.offset, region.size, geo.erase, partial,
                      port=port, progress=_progress_printer(region.size))
    if partial.stat().st_size != region.size:
        raise BackupError('backup image has an unexpected length')
    try:
        check_bad_fill(partial, region, geo)
        blocks = choose_blocks(region, geo, None if verify_all else samples)
        print(nand.tr(f'Сверяю {len(blocks)} блоков с прямым чтением U-Boot…',
                      f'Cross-checking {len(blocks)} blocks against U-Boot direct reads…'))
        checked = cross_check(host, region, geo, partial, blocks)
    except BackupError as exc:
        bad_name = output.with_name(output.name + '.unverified')
        os.replace(partial, bad_name)
        partial.with_name(partial.name + '.json').unlink(missing_ok=True)
        raise BackupError(f'verification failed: {exc}. The file was kept as {bad_name} and '
                          'no manifest was written. Do not restore from it.') from None

    meta = {
        'schema': 1, 'format': 'ursus-nand-main-area-ecc',
        'region': {'name': region.name, 'offset': region.offset, 'size': region.size},
        'board': status.get('board'), 'soc': status.get('soc'),
        'flash_chip': status.get('flash_chip'), 'flash_id': status.get('flash_id'),
        'flash_size': geo.size, 'erase_size': geo.erase, 'page_size': geo.page,
        'bad_blocks': list(geo.bad), 'sha256': digest,
        'oob': False, 'bad_block_fill': 'ff', 'ursusboot_version': status.get('version'),
        'transport': 'http-stream',
        'verify': {'mode': 'full' if verify_all else 'sampled', 'blocks': checked},
    }
    tmp = manifest.with_name(manifest.name + '.partial')
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(partial, output)
    os.replace(tmp, manifest)
    partial.with_name(partial.name + '.json').unlink(missing_ok=True)
    print(nand.tr(f'[ГОТОВО] {output} и {manifest}; SHA256 {digest}; сверено блоков: {checked}',
                  f'[DONE] {output} and {manifest}; SHA256 {digest}; blocks cross-checked: {checked}'))
