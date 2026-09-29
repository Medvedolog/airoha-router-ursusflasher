#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import socket
import struct
import sys
import threading
import tempfile
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

import ursus_web_client as uw
from ursus_ws_terminal import LiveTerminal
from ursus_ws_xmodem import WebSocketSerial, _wait_ready
from ursus_ws_nand import Geometry, Region, _parse_list, _runs


def terminal_key_contract() -> None:
    class FakeSocket:
        def __init__(self):
            self.sent = []

        def send(self, data: bytes) -> None:
            self.sent.append(data)

    sock = FakeSocket()
    term = LiveTerminal(sock, '127.0.0.1')
    term._write = lambda data: None
    term._keys(b'version\r\x1bOQ')
    assert sock.sent == [b'version\r']  # paste is batched, F2 is local
    assert term.action == 'upload' and term.stop.is_set()

    sock = FakeSocket()
    term = LiveTerminal(sock, '127.0.0.1')
    term._write = lambda data: None
    term._keys(b'\x1bOS')  # F4: line editing
    term._keys(b'version\r\x1b[A')
    assert sock.sent == [b'version\r'] and term.line == 'version'
    term._keys(b'\x1b[B\x03\x1d')  # history down, remote Ctrl-C, local menu
    term._keys(b'd')
    assert sock.sent == [b'version\r', b'\x03']
    assert term.action == 'download' and term.stop.is_set()

    sock = FakeSocket()
    term = LiveTerminal(sock, '127.0.0.1')
    term._write = lambda data: None
    term._keys(b'\x1b[15~')
    assert term.action == 'nand' and term.stop.is_set() and sock.sent == []


def nand_geometry_contract() -> None:
    listing = (b'List of MTD devices:\r\n* spi-nand0\r\n'
               b'  - type: NAND flash\r\n  - block size: 0x20000 bytes\r\n'
               b'  - min I/O: 0x800 bytes\r\n'
               b'  - 0x000000000000-0x000010000000 : "spi-nand0"\r\n'
               b'\t  - 0x000000000000-0x000000080000 : "bl2"\r\n'
               b'\t  - 0x000000080000-0x000010000000 : "ubi"\r\n'
               b'\t\t  - 0x000000080000-0x0000000a0000 : "nested-relative"\r\n')
    master, size, erase, page, parts = _parse_list(
        listing, {'flash_size_mib': 256, 'flash_erase_size': 0x20000,
                  'flash_page_size': 0x800, 'soc': 'AN7581', 'current_layout': 'OPENWRT_UBI'})
    assert (master, size, erase, page) == ('spi-nand0', 256 << 20, 0x20000, 0x800)
    assert parts[0] == Region('bl2', 0, 0x80000)
    assert [p.name for p in parts] == ['bl2', 'ubi']
    assert _parse_list(listing, {'flash_size_mib': 256, 'flash_erase_size': 0x20000,
                                 'flash_page_size': 0x800, 'soc': 'AN7583',
                                 'current_layout': 'STOCK'})[-1] == ()
    geo = Geometry(master, size, erase, page, parts, (0x20000,))
    assert _runs(Region('bl2', 0, 0x80000), geo) == [(0, 0x20000), (0x40000, 0x40000)]
    try:
        _parse_list(listing.replace(b'0x20000 bytes', b'0x40000 bytes'),
                    {'flash_size_mib': 256, 'flash_erase_size': 0x20000,
                     'flash_page_size': 0x800})
    except RuntimeError:
        pass
    else:
        raise AssertionError('geometry mismatch must fail')


def nand_restore_contract() -> None:
    import ursus_ws_nand as nand

    erase = 0x20000
    geo = Geometry('spi-nand0', 4 * erase, erase, 0x800, (),
                   (erase,))
    status = {'version': '0.1.0-alpha5-t75', 'board': 'XG-040G-MD',
              'soc': 'AN7581', 'flash_chip': 'FM25G02B', 'flash_id': 'abcd',
              'ubi_attached': False}
    calls: list[str] = []
    current_digest = ''
    last_read = 0
    image: Path

    class FakeSession:
        def __init__(self, host: str):
            assert host == '127.0.0.1'

        def close(self) -> None:
            pass

        def detach_ubi(self) -> None:
            calls.append('ubi detach')

        def command(self, cmd: str, timeout: float = 60) -> bytes:
            nonlocal last_read
            calls.append(cmd)
            if cmd.startswith('mtd bad '):
                return b'MTD device spi-nand0 bad blocks list:\r\n\t0x00020000\r\n'
            if cmd.startswith('mtd read '):
                last_read = int(cmd.split()[-2], 16)
            return b'UrsusBoot> '

        def sha(self, address: int, size: int) -> str:
            if address == nand.VERIFY_ADDR:
                return hashlib.sha256(image.read_bytes()[last_read:last_read + size]).hexdigest()
            return current_digest

    def fake_send(session, path, length, digest, port):
        nonlocal current_digest
        assert path.read_bytes() and length == path.stat().st_size
        assert 1024 <= port <= 65535, port
        current_digest = digest

    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / 'nand.bin'
        image.write_bytes(b'A' * erase + b'\xff' * erase + b'B' * (2 * erase))
        meta = {'schema': 1, 'format': 'ursus-nand-main-area-ecc',
                'region': {'name': 'entire-nand', 'offset': 0, 'size': 4 * erase},
                'board': status['board'], 'soc': status['soc'],
                'flash_chip': status['flash_chip'], 'flash_id': status['flash_id'],
                'flash_size': 4 * erase, 'erase_size': erase, 'page_size': 0x800,
                'bad_blocks': [erase], 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
        manifest = Path(str(image) + '.json')
        manifest.write_text(json.dumps(meta), encoding='utf-8')
        with mock.patch.object(nand, 'Session', FakeSession), \
                mock.patch.object(nand, 'discover', lambda session, st: geo), \
                mock.patch.object(nand, '_serve_chunk', fake_send), \
                mock.patch('builtins.input', return_value='y'):
            nand.restore('127.0.0.1', status, image)
            assert 'ubi detach' in calls, 'UBI must be detached before writing its MTD'
            erases = [i for i, x in enumerate(calls) if x.startswith('mtd erase ')]
            assert erases and calls.index('ubi detach') < erases[0]
            writes = [x for x in calls if x.startswith('mtd write ')]
            assert len(writes) == 3 and writes[0].split()[-2] == '0x40000' \
                   and writes[1].split()[-2] == '0x60000' and writes[2].split()[-2] == '0x0'
            assert all(x.split()[-2] != '0x20000' for x in writes)
            calls.clear()
            meta['bad_blocks'] = []
            manifest.write_text(json.dumps(meta), encoding='utf-8')
            try:
                nand.restore('127.0.0.1', status, image)
            except RuntimeError as exc:
                assert 'URSUS_NAND_BADBLOCK_MAP_CHANGED' in str(exc)
            else:
                raise AssertionError('changed bad-block map must stop restore')
            assert not any(x.startswith(('mtd erase ', 'mtd write ')) for x in calls)


def nand_skip_bad_contract() -> None:
    """Skip-bad restore: the archive's good blocks, in order, onto the target's good blocks."""
    import ursus_ws_nand as nand
    from ursus_ws_nand import Region

    E = 0x20000
    base = 0x100000                      # outside the 512 KiB boot area
    geo = Geometry('spi-nand0', 64 * E, E, 0x800, (), ())

    def reader(img):
        return lambda rel: img[rel:rel + E]

    def ubi_free():
        b = bytearray(b'\xff' * E)
        b[:4] = b'UBI#'
        b[16:20] = (0x800).to_bytes(4, 'big')
        return bytes(b)

    def ubi_used():
        b = bytearray(ubi_free())
        b[0x800:0x804] = b'UBI!'
        return bytes(b)

    # 1. the archive had a bad block, the target has none: data closes up, the tail is erased
    region = Region('p', base, 4 * E)
    img = b'A' * E + b'\xff' * E + b'C' * E + b'D' * E
    moves, rep = nand.plan_skip_bad(region, [base + E], [], geo, reader(img))
    assert moves == [(0, base), (2 * E, base + E), (3 * E, base + 2 * E), (None, base + 3 * E)], moves
    assert rep['shifted'] == 2 and rep['erased_only'] == 1 and not rep['boot_area_shifted']

    # 2. the target has a new bad block: later data moves past it, an erased tail block is left out
    img = b'A' * E + b'B' * E + b'C' * E + b'\xff' * E
    moves, rep = nand.plan_skip_bad(region, [], [base + E], geo, reader(img))
    assert moves == [(0, base), (E, base + 2 * E), (2 * E, base + 3 * E)], moves
    assert rep['dropped'] == 1
    # an erased block in the MIDDLE is not dropped (it would move everything after it twice)
    img = b'A' * E + b'\xff' * E + b'C' * E + b'D' * E
    try:
        nand.plan_skip_bad(region, [], [base + E], geo, reader(img))
    except RuntimeError as exc:
        assert 'URSUS_NAND_SKIPBAD_NO_ROOM' in str(exc)
    else:
        raise AssertionError('no room must refuse')

    # 3. a free UBI PEB may go from anywhere; a PEB with a VID header may not
    img = ubi_used() + ubi_free() + ubi_used() + ubi_used()
    moves, rep = nand.plan_skip_bad(region, [], [base + 3 * E], geo, reader(img))
    assert [m[0] for m in moves] == [0, 2 * E, 3 * E] and rep['dropped'] == 1, moves
    damaged = bytearray(ubi_used())
    damaged[0x800:0x804] = b'XXXX'
    img = ubi_used() * 3 + bytes(damaged)
    try:
        nand.plan_skip_bad(region, [], [base], geo, reader(img))
    except RuntimeError as exc:
        assert 'URSUS_NAND_SKIPBAD_NO_ROOM' in str(exc)
    else:
        raise AssertionError('UBI data blocks must never be dropped')

    # 4. whole chip: data never crosses a partition boundary
    parts = (Region('bl2', 0, 4 * E), Region('ubi', 4 * E, 4 * E))
    g2 = Geometry('spi-nand0', 8 * E, E, 0x800, parts, ())
    whole = Region('entire-nand', 0, 8 * E)
    img = b''.join(bytes([65 + i]) * E for i in range(7)) + b'\xff' * E
    moves, rep = nand.plan_skip_bad(whole, [], [5 * E], g2, reader(img))
    for src, dst in moves:
        if src is not None:
            assert (src < 4 * E) == (dst < 4 * E), (src, dst)
    assert rep['segments'] == 2 and not rep['boot_area_shifted']
    # a shift inside the boot area is reported, so the restore asks for SKIP BAD BOOT
    moves, rep = nand.plan_skip_bad(whole, [E], [], g2, reader(img))
    assert rep['boot_area_shifted']

    # 5. end to end against a fake flash: restore(skip_bad=True) writes the plan and verifies it
    status = {'version': '0.1.0-alpha5-t78', 'board': 'XG-040G-MD', 'soc': 'AN7581',
              'flash_chip': 'FM25G02B', 'flash_id': 'abcd'}
    geo5 = Geometry('spi-nand0', 64 * E, E, 0x800, (Region('p', base, 4 * E),), (base + E,))
    flash: dict = {}
    ram = bytearray(8 * E)
    verify = {'data': b''}
    calls: list[str] = []
    corrupt = False

    class FakeSession:
        def __init__(self, host):
            pass

        def close(self):
            pass

        def detach_ubi(self):
            calls.append('ubi detach')

        def command(self, cmd, timeout=60):
            calls.append(cmd)
            parts_ = cmd.split()
            if cmd.startswith('mtd bad '):
                return f'MTD device spi-nand0 bad blocks list:\r\n\t0x{base + E:08x}\r\n'.encode()
            if cmd.startswith('mtd erase '):
                flash[int(parts_[3], 16)] = b'\xff' * E
            elif cmd.startswith('mtd write '):
                a = int(parts_[3], 16) - nand.RAM_ADDR
                flash[int(parts_[4], 16)] = bytes(ram[a:a + E]) if not corrupt else b'X' * E
            elif cmd.startswith('mtd read '):
                verify['data'] = flash[int(parts_[4], 16)]
            return b'UrsusBoot> '

        def sha(self, address, size):
            return hashlib.sha256(verify['data'] if address == nand.VERIFY_ADDR else bytes(ram[:size])).hexdigest()

    def fake_send(session, path, length, digest, port):
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest and len(data) == length
        ram[:length] = data

    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / 'p.bin'
        image.write_bytes(b'A' * E + b'B' * E + b'C' * E + b'\xff' * E)   # taken where no block was bad
        meta = {'schema': 1, 'format': 'ursus-nand-main-area-ecc',
                'region': {'name': 'p', 'offset': base, 'size': 4 * E},
                'board': status['board'], 'soc': status['soc'], 'flash_chip': status['flash_chip'],
                'flash_id': status['flash_id'], 'flash_size': 64 * E, 'erase_size': E, 'page_size': 0x800,
                'bad_blocks': [], 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
        Path(str(image) + '.json').write_text(json.dumps(meta), encoding='utf-8')
        with mock.patch.object(nand, 'Session', FakeSession), \
                mock.patch.object(nand, 'discover', lambda session, st: geo5), \
                mock.patch.object(nand, '_serve_chunk', fake_send), \
                mock.patch('builtins.input', return_value='y'):
            try:                                   # physical mode still refuses the changed map
                nand.restore('127.0.0.1', status, image)
            except RuntimeError as exc:
                assert 'URSUS_NAND_BADBLOCK_MAP_CHANGED' in str(exc)
            else:
                raise AssertionError('physical mode must refuse')
            assert not flash
            nand.restore('127.0.0.1', status, image, skip_bad=True)
        assert flash[base] == b'A' * E and flash[base + 2 * E] == b'B' * E and flash[base + 3 * E] == b'C' * E
        assert base + E not in flash, 'the bad block is never erased or written'
        assert calls.index('ubi detach') < next(i for i, c in enumerate(calls) if c.startswith('mtd erase'))

        # a block that reads back differently stops the restore
        corrupt = True
        flash.clear()
        with mock.patch.object(nand, 'Session', FakeSession), \
                mock.patch.object(nand, 'discover', lambda session, st: geo5), \
                mock.patch.object(nand, '_serve_chunk', fake_send), \
                mock.patch('builtins.input', return_value='y'):
            try:
                nand.restore('127.0.0.1', status, image, skip_bad=True)
            except RuntimeError as exc:
                assert 'readback differs' in str(exc)
            else:
                raise AssertionError('a bad readback must stop the restore')
        corrupt = False

        # the boot area: a shift there needs the typed confirmation; anything else writes nothing
        geo6 = Geometry('spi-nand0', 64 * E, E, 0x800, (Region('bl2', 0, 4 * E),), (E,))
        meta['region'] = {'name': 'bl2', 'offset': 0, 'size': 4 * E}
        Path(str(image) + '.json').write_text(json.dumps(meta), encoding='utf-8')
        flash.clear()
        with mock.patch.object(nand, 'Session', FakeSession), \
                mock.patch.object(nand, 'discover', lambda session, st: geo6), \
                mock.patch.object(nand, '_serve_chunk', fake_send), \
                mock.patch('builtins.input', return_value='y'):
            nand.restore('127.0.0.1', status, image, skip_bad=True)
        assert not flash, 'without SKIP BAD BOOT nothing may be written to a shifted boot area'


def nand_backup_contract() -> None:
    import ursus_ws_nand as nand
    import ursus_ws_tftp

    erase = 0x20000
    geo = Geometry('spi-nand0', 4 * erase, erase, 0x800, (), (erase,))
    status = {'version': '0.1.0-alpha5-t75', 'board': 'Nokia XG-040G-MD',
              'soc': 'Airoha AN7581', 'flash_chip': 'FM25G02B', 'flash_id': 'abcd'}
    reads: list[str] = []

    class FakeSession:
        def __init__(self, host):
            self.link = object()

        def command(self, cmd, timeout=60):
            reads.append(cmd)
            return b'UrsusBoot> '

        def close(self):
            pass

    def fake_receive(host, address, size, path, *, port, link):
        assert address == nand.RAM_ADDR and size in (erase, 2 * erase)
        assert 1024 <= port <= 65535, port
        path.write_bytes(b'R' * size)

    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / 'nand.bin'
        with mock.patch.object(nand, 'Session', FakeSession), \
                mock.patch.object(nand, 'discover', lambda session, st: geo), \
                mock.patch.object(ursus_ws_tftp, 'receive_ram', fake_receive):
            nand.backup('127.0.0.1', status, Region('entire-nand', 0, geo.size), image)
        data = image.read_bytes()
        assert len(data) == geo.size
        assert data[:erase] == b'R' * erase
        assert data[erase:2 * erase] == b'\xff' * erase
        assert data[2 * erase:] == b'R' * (2 * erase)
        meta = json.loads(Path(str(image) + '.json').read_text())
        assert meta['sha256'] == hashlib.sha256(data).hexdigest()
        assert meta['bad_blocks'] == [erase] and meta['oob'] is False
        assert reads == ['mtd read spi-nand0 0x81800000 0x0 0x20000',
                         'mtd read spi-nand0 0x81800000 0x40000 0x40000']


def xmodem_transport_contract() -> None:
    class FakeWS:
        def __init__(self):
            self.messages = [b'Ready for binary (xmodem) download\r\n', b'C', b'\x06']
            self.sent = []
            self.cv = threading.Condition()
            self.closed = False

        def recv_message(self):
            with self.cv:
                while not self.messages and not self.closed:
                    self.cv.wait()
                if self.closed:
                    raise EOFError
                return self.messages.pop(0)

        def send(self, data):
            self.sent.append(data)

        def close(self):
            with self.cv:
                self.closed = True
                self.cv.notify_all()

    fake = FakeWS()
    link = WebSocketSerial(fake)
    try:
        _wait_ready(link, 2)
        assert link.read(1, 1) == b'\x06'
        link.write(b'A' * 2300)
        assert list(map(len, fake.sent)) == [1024, 1024, 252]
        link.reset_input()  # must preserve the next receiver byte
        with fake.cv:
            fake.messages.append(b'C')
            fake.cv.notify_all()
        assert link.read(1, 1) == b'C'
    finally:
        link.close()


def existing_xmodem_sender_over_ws() -> None:
    os.environ.setdefault('NOKIA_LANG', 'ru')
    from proven_backend import xmodem_send, crc16_xmodem

    class Receiver:
        def __init__(self):
            self.cv = threading.Condition()
            self.messages = []
            self.closed = False
            self.blocks = []
            self.eot = False

        def recv_message(self):
            with self.cv:
                while not self.messages and not self.closed:
                    self.cv.wait()
                if self.closed:
                    raise EOFError
                return self.messages.pop(0)

        def send(self, data):
            if data == b'\x04':
                self.eot = True
            else:
                assert len(data) == 133 and data[0] == 1
                assert data[1] ^ data[2] == 255
                assert int.from_bytes(data[-2:], 'big') == crc16_xmodem(data[3:-2])
                self.blocks.append(data[3:-2])
            with self.cv:
                self.messages.append(b'\x06')
                self.cv.notify_all()

        def close(self):
            with self.cv:
                self.closed = True
                self.cv.notify_all()

    receiver = Receiver()
    link = WebSocketSerial(receiver)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'test.bin'
            payload = bytes(range(256)) + b'!'  # three 128-byte blocks
            file.write_bytes(payload)
            xmodem_send(link, file, file.name, io.BytesIO())
            assert b''.join(receiver.blocks)[:len(payload)] == payload
            assert len(receiver.blocks) == 3 and receiver.eot
    finally:
        link.close()


def tftp_ram_export_contract() -> None:
    import proven_backend as proven
    from ursus_ws_tftp import receive_ram

    payload = b'UrsusBoot TFTP PUT' * 37
    digest = hashlib.sha256(payload).hexdigest()

    class FakeWS:
        def __init__(self):
            self.cv = threading.Condition()
            self.messages = []
            self.closed = False

        def recv_message(self):
            with self.cv:
                while not self.messages and not self.closed:
                    self.cv.wait()
                if self.closed:
                    raise EOFError
                return self.messages.pop(0)

        def send(self, data):
            with self.cv:
                if data.startswith(b'hash sha256'):
                    self.messages.append(f'SHA256 for RAM ==> {digest}\r\nUrsusBoot> '.encode())
                elif data.startswith(b'tftpput '):
                    assert b':1069:' in data
                    self.messages.append(b'TFTP done\r\nUrsusBoot> ')
                self.cv.notify_all()

        def close(self):
            with self.cv:
                self.closed = True
                self.cv.notify_all()

    def fake_receive(bind_ip, port, output, name, host, ready, result, **kwargs):
        assert port == 1069 and host == '127.0.0.1' and name.startswith('ursus-ram-')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        result.bytes_transferred = len(payload)
        ready.set()

    original_connect = uw.UrsusLiveConsole.connect
    original_receive = proven.receive_tftp_put
    original_ip = proven.local_ip_for
    uw.UrsusLiveConsole.connect = lambda *args, **kwargs: (FakeWS(), b'hello')
    proven.receive_tftp_put = fake_receive
    proven.local_ip_for = lambda host: '127.0.0.1'
    try:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'ram.bin'
            receive_ram('127.0.0.1', 0x81800000, len(payload), output)
            assert output.read_bytes() == payload
    finally:
        uw.UrsusLiveConsole.connect = original_connect
        proven.receive_tftp_put = original_receive
        proven.local_ip_for = original_ip


def _recv_headers(conn: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            raise RuntimeError("client closed during handshake")
        data.extend(chunk)
    return bytes(data)


def _server_frame(payload: bytes, opcode: int = 2) -> bytes:
    first = 0x80 | opcode
    n = len(payload)
    if n <= 125:
        return bytes((first, n)) + payload
    if n <= 0xffff:
        return bytes((first, 126)) + struct.pack("!H", n) + payload
    return bytes((first, 127)) + struct.pack("!Q", n) + payload


def _recv_client_frame(conn: socket.socket) -> tuple[int, bytes]:
    head = conn.recv(2)
    if len(head) != 2:
        raise RuntimeError("short client frame")
    opcode = head[0] & 0x0f
    masked = bool(head[1] & 0x80)
    n = head[1] & 0x7f
    if not masked:
        raise RuntimeError("client frame is not masked")
    if n == 126:
        n = struct.unpack("!H", conn.recv(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", conn.recv(8))[0]
    mask = conn.recv(4)
    if len(mask) != 4:
        raise RuntimeError("short client mask")
    payload = bytearray()
    while len(payload) < n:
        payload.extend(conn.recv(n - len(payload)))
    return opcode, bytes(ch ^ mask[i & 3] for i, ch in enumerate(payload))


def nand_generation_contract() -> None:
    """The presets must follow the tftpput capability, not one exact version."""
    import ursus_ws_nand as nand

    for version, want in (('0.1.0-alpha5-t75', True), ('0.1.0-alpha5-t76', True),
                          ('0.1.0-alpha5-t100', True), ('0.1.0-alpha5-t74', False),
                          ('0.1.0-alpha5-UBIUX1-TEST61', False), ('', False)):
        got = nand._tftpput_available({'version': version})
        assert got is want, (version, got, want)
    # An explicit capability flag wins over the inferred generation.
    assert nand._tftpput_available({'version': '0.1.0-alpha5-t74', 'tftpput_available': True})
    assert not nand._tftpput_available({'version': '0.1.0-alpha5-t99', 'tftpput_available': False})


def nand_transfer_port_contract() -> None:
    """A busy 1069 must fall back instead of ending the preset."""
    import socket as _socket

    import ursus_ws_nand as nand

    hog = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        hog.bind(('', nand.PORT))
    except OSError:
        # Something on this machine already holds 1069; the fallback is exactly
        # what ships for that case, so assert it rather than the preferred port.
        hog.close()
        assert 1024 <= nand._transfer_port() <= 65535
        return
    try:
        hog.close()
        assert nand._transfer_port() == nand.PORT, 'a free 1069 must be preferred'
        hog = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        hog.bind(('', nand.PORT))
        fallback = nand._transfer_port()
        assert fallback != nand.PORT and 1024 <= fallback <= 65535, fallback
    finally:
        hog.close()


def main() -> int:
    terminal_key_contract()
    nand_generation_contract()
    nand_transfer_port_contract()
    nand_geometry_contract()
    nand_restore_contract()
    nand_skip_bad_contract()
    nand_backup_contract()
    xmodem_transport_contract()
    existing_xmodem_sender_over_ws()
    tftp_ram_export_contract()
    ready = threading.Event()
    result: dict[str, object] = {}
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def fake_server() -> None:
        ready.set()
        conn, _ = listener.accept()
        try:
            raw = _recv_headers(conn)
            head = raw.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
            lines = head.split("\r\n")
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            assert lines[0] == "GET /ws/console HTTP/1.1"
            assert headers["sec-websocket-version"] == "13"
            assert headers["sec-websocket-protocol"] == "ursusboot-console-v1"
            key = headers["sec-websocket-key"]
            accept = base64.b64encode(
                hashlib.sha1((key + uw._WS_GUID).encode("ascii")).digest()
            ).decode("ascii")
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "Sec-WebSocket-Protocol: ursusboot-console-v1\r\n"
                "\r\n"
            ).encode("ascii")
            conn.sendall(response)
            hello = (
                b"URSUS_WS_HELLO protocol=1 product=UrsusBoot transport=live-stdio\r\n"
                b"[selftest]\r\nUrsusBoot> "
            )
            conn.sendall(_server_frame(hello))
            opcode, payload = _recv_client_frame(conn)
            assert opcode == 2
            assert payload == b"version\r"
            result["payload"] = payload
            conn.sendall(_server_frame(b"U-Boot selftest\r\nUrsusBoot> "))
        finally:
            conn.close()
            listener.close()

    th = threading.Thread(target=fake_server, daemon=True)
    th.start()
    ready.wait(2)

    ws, hello = uw.UrsusLiveConsole.connect("127.0.0.1", port=port, timeout=3)
    assert hello.startswith(uw._WS_HELLO)
    ws.send(b"version\r")
    reply = ws.recv_message()
    assert reply == b"U-Boot selftest\r\nUrsusBoot> "
    ws.close()
    th.join(timeout=2)
    assert result.get("payload") == b"version\r"
    # EXPERT wraps sys.stdout in proven_backend._ConsoleTee for the session log.
    # The live console writes raw bytes, so it must still reach the real stream
    # (item 14 failed with "_ConsoleTee has no attribute buffer").
    import proven_backend
    raw = io.BytesIO()
    text_out = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)
    tee = proven_backend._ConsoleTee(text_out, [])
    assert tee.buffer is text_out.buffer
    term = LiveTerminal(None, "127.0.0.1")
    with mock.patch.object(sys, "stdout", tee):
        term._write(b"UrsusBoot> \xd0\x9f")
    assert raw.getvalue() == b"UrsusBoot> \xd0\x9f", raw.getvalue()
    # a stream with no byte layer degrades to text instead of raising
    plain = io.StringIO()
    with mock.patch.object(sys, "stdout", plain):
        term._write(b"UrsusBoot> ")
    assert plain.getvalue() == "UrsusBoot> "

    # --- live terminal behaviour without a real console --------------------
    import shutil
    import time as _time

    class FakeWS:
        def __init__(self):
            self.sent = []
            self.closed = False

        def send(self, data):
            self.sent.append(bytes(data))

        def close(self):
            self.closed = True

    def make():
        ws = FakeWS()
        t = LiveTerminal(ws, "127.0.0.1")
        shown = bytearray()
        t._write = lambda data: shown.extend(data)
        return ws, t, shown

    # t77 firmware echoes a deleted character as the TEXT backslash-b: repaired for display
    ws, t, shown = make()
    t._output(b"UrsusBoot> ab" + b"\\b \\b")
    assert bytes(shown) == b"UrsusBoot> ab\x08 \x08", bytes(shown)
    ws, t, shown = make()
    t._output(b"a\\b c")                               # not the erase sequence: untouched
    assert bytes(shown) == b"a\\b c"

    # Ctrl-C at the idle prompt would stop WebFailsafe: needs a second press within 2 s
    ws, t, shown = make()
    t._output(b"\r\nUrsusBoot> ping")
    t._input(b"\x03")
    assert ws.sent == [] and (b"NOT sent" in bytes(shown) or "НЕ отправлено".encode() in bytes(shown))
    assert bytes(shown).endswith(b"UrsusBoot> ping")     # the typed line is redrawn
    t._input(b"\x03")
    assert ws.sent == [b"\x03"], ws.sent
    # while a command is running Ctrl-C goes straight through, in RAW and in LINE mode
    for raw in (True, False):
        ws, t, shown = make()
        t.raw = raw
        t._output(b"UrsusBoot> ping 1.2.3.4\r\nPING 1.2.3.4 ...")
        t._input(b"\x03")
        assert ws.sent == [b"\x03"], (raw, ws.sent)
    # a later confirmation window does not stay open forever
    ws, t, shown = make()
    t._output(b"UrsusBoot> ")
    t._input(b"\x03")
    t.ctrlc_at -= 3
    t._input(b"\x03")
    assert ws.sent == [], "an expired confirmation must ask again"
    # typed bytes around a Ctrl-C reach the router in order, the Ctrl-C goes through the guard
    ws, t, shown = make()
    t._output(b"UrsusBoot> ")
    t._keys(b"ab\x03cd")
    assert ws.sent == [b"ab", b"cd"], ws.sent

    # window resize is followed while the device is silent, and stale bars are erased
    ws, t, shown = make()
    real = shutil.get_terminal_size
    try:
        t.chrome, t.cols, t.rows = True, 100, 20
        shutil.get_terminal_size = lambda fallback=(100, 30): os.terminal_size((120, 40))
        t._check_resize(force=True)
        out = bytes(shown)
        assert (t.cols, t.rows) == (120, 40)
        assert b"\x1b[19;1H\x1b[2K" in out and b"\x1b[20;1H\x1b[2K" in out, out   # old footer rows erased
        assert b"\x1b[3;38r" in out and b"\x1b[40;1H" in out, out                 # new region and footer
        shown.clear()
        t._check_resize(force=True)
        assert bytes(shown) == b"", "no redraw without a size change"
        shutil.get_terminal_size = lambda fallback=(100, 30): os.terminal_size((30, 8))
        t._check_resize(force=True)
        assert t.chrome is False, "a window too small for the chrome switches it off"
    finally:
        shutil.get_terminal_size = real

    # RAW mode: the device shell has no history and no cursor editing, so Up/Down
    # replace its line locally (Ctrl-U + text) and Left/Right are dropped -- neither
    # may reach the device as the letters "[A" / "[D".
    ws, t, shown = make()
    t._output(b"\r\nUrsusBoot> ")
    t._keys(b"ping 1\rhelp\r")
    assert t.history == ["ping 1", "help"], t.history
    t._output(b"\r\nUrsusBoot> ")
    ws.sent.clear()
    for seq, expect in ((b"\x1b[A", b"\x15help"), (b"\x1b[A", b"\x15ping 1"), (b"\x1b[A", b"\x15ping 1"),
                        (b"\x1b[B", b"\x15help"), (b"\x1b[B", b"\x15")):
        ws.sent.clear()
        t._keys(seq)
        assert ws.sent == [expect], (seq, ws.sent)
    ws.sent.clear()
    t._keys(b"\x1b[C\x1b[D\x1bOC\x1bOD")
    assert ws.sent == [], ws.sent
    t._keys(b"ab")
    t._keys(b"\x1b[A")                     # replaces what was typed, from the tracked line
    assert ws.sent[-1] == b"\x15help", ws.sent
    assert not any(b"[" in x for x in ws.sent), ws.sent
    # while a command runs the arrows are not sent at all
    ws, t, shown = make()
    t.history = ["x"]
    t.index = 1
    t._output(b"UrsusBoot> ping 1.2.3.4\r\nPING ...")
    t._keys(b"\x1b[A\x1b[B")
    assert ws.sent == [], ws.sent
    # Backspace / Ctrl-U / Ctrl-C keep the tracked line in step with the device
    ws, t, shown = make()
    t._output(b"UrsusBoot> ")
    t._keys(b"abc\x7f")
    assert t.rawline == "ab"
    t._keys(b"\x15")
    assert t.rawline == ""

    # Colours: dark green screen; anything that would reset colours re-applies them.
    from ursus_ws_terminal import _BODY
    ws, t, shown = make()
    t.cols, t.rows, t.chrome = 100, 30, True
    bars = t._bars().decode("utf-8")
    assert bars.count(_BODY) == 4, "every bar must hand the screen colours back"
    assert "48;2;7;32;17" in _BODY
    t._output(b"\x1b[0mplain\x1b[m")
    assert bytes(shown).count(_BODY.encode()) == 2, bytes(shown)
    ws, t, shown = make()
    t._output(b"\x1b[0mplain")               # no chrome (small/no-colour terminal): untouched
    assert bytes(shown) == b"\x1b[0mplain"
    ws, t, shown = make()
    t.chrome, t.rows = True, 30
    t._end()
    assert b"\x1b[0m" in bytes(shown) and t.chrome is False

    # start-up paints the whole screen in the console colours before the bars are drawn
    class Tty(io.StringIO):
        def isatty(self):
            return True

    ws, t, shown = make()
    real_size = shutil.get_terminal_size
    try:
        shutil.get_terminal_size = lambda fallback=(100, 30): os.terminal_size((100, 30))
        with mock.patch.object(sys, "stdout", Tty()), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            t._start()
    finally:
        shutil.get_terminal_size = real_size
    started = bytes(shown)
    assert t.chrome and started.index(_BODY.encode()) < started.index(b"\x1b[2J"), started[:200]

    # The same terminal over a COM port: a plain UART terminal, no network functions.
    import inspect
    from ursus_ws_terminal import SerialLink

    class FakeSerial:
        def __init__(self):
            self.rx = [b"U-Boot> ", b""]
            self.tx = []
            self.closed = False

        def read(self, size=4096, timeout=0.2):
            return self.rx.pop(0) if self.rx else b""

        def write(self, data):
            self.tx.append(bytes(data))

        def close(self):
            self.closed = True

    sp = FakeSerial()
    link = SerialLink(sp)
    assert link.recv_message() == b"U-Boot> " and link.recv_message() == b""     # idle -> b"", never blocks forever
    link.send(b"help\r")
    assert sp.tx == [b"help\r"]
    t = LiveTerminal(link, "COM7", uart="COM7")
    shown = bytearray()
    t._write = lambda data: shown.extend(data)
    t.cols, t.rows = 100, 30
    assert "UART COM7" in t._bars().decode("utf-8") and "WebSocket" not in t._bars().decode("utf-8")
    assert "F2" not in t._bars().decode("utf-8") and "F5" not in t._bars().decode("utf-8")
    for key in (b"\x1bOQ", b"\x1b[13~", b"\x1b[15~"):       # F2, F3, F5 need the network: refused, not queued
        shown.clear()
        t._input(key)
        assert b"UART" in bytes(shown), (key, bytes(shown))
        assert t.action is None and not t.stop.is_set(), key
    t.menu = True
    t._input(b"n")
    assert t.action is None and not t.stop.is_set()
    # Ctrl-C at the prompt is a plain interrupt on a UART: no second press is asked for
    t._output(b"\r\nUrsusBoot> ")
    t._input(b"\x03")
    assert sp.tx[-1] == b"\x03", sp.tx
    # the WebSocket terminal still asks and still leaves for F2
    ws, t2, shown2 = make()
    t2._input(b"\x1bOQ")
    assert t2.action == "upload" and t2.stop.is_set()
    import expert_multi
    assert "live_console_uart" in inspect.getsource(expert_multi._run_live_console)
    link.close()
    assert sp.closed
    try:
        link.recv_message()
    except EOFError:
        pass
    else:
        raise AssertionError("a closed link must end the reader")

    # The connect failure names the real cause: 409 = slot taken, not "WebFailsafe stopped".
    from ursus_ws_terminal import _connect_hint
    assert "t79" in _connect_hint(RuntimeError("live console WebSocket upgrade failed: 'HTTP/1.1 409 Conflict'"))
    assert "409" not in _connect_hint(RuntimeError("timed out")) and "ursusweb" in _connect_hint(RuntimeError("timed out"))

    import inspect
    pump = inspect.getsource(LiveTerminal._pump_input)
    assert "_check_resize()" in pump, "the keyboard loop must poll the window size (silent device)"
    assert "_ConsoleInputMode" in inspect.getsource(LiveTerminal.run)
    assert "KeyboardInterrupt" in inspect.getsource(LiveTerminal.run)

    print("URSUS_WS_TFTPPUT_SELFTEST=PASS ram_range=1 size=1 sha256=1")
    print("URSUS_WS_NAND_SELFTEST=PASS f5_local=1 geometry=1 bad_block_runs=1")
    print("URSUS_WS_XMODEM_SELFTEST=PASS reused_uart_sender=1 blocks=3 crc_ack=1")
    print("URSUS_WS_CLIENT_SELFTEST=PASS handshake=accept+subprotocol+hello masked_tx=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
