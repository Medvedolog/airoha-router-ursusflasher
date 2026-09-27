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

    def fake_send(session, path, length, digest):
        nonlocal current_digest
        assert path.read_bytes() and length == path.stat().st_size
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
                assert 'bad-block map' in str(exc)
            else:
                raise AssertionError('changed bad-block map must stop restore')
            assert not any(x.startswith(('mtd erase ', 'mtd write ')) for x in calls)


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

    def fake_receive(host, address, size, path, *, link):
        assert address == nand.RAM_ADDR and size in (erase, 2 * erase)
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


def main() -> int:
    terminal_key_contract()
    nand_geometry_contract()
    nand_restore_contract()
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
    print("URSUS_WS_TFTPPUT_SELFTEST=PASS ram_range=1 size=1 sha256=1")
    print("URSUS_WS_NAND_SELFTEST=PASS f5_local=1 geometry=1 bad_block_runs=1")
    print("URSUS_WS_XMODEM_SELFTEST=PASS reused_uart_sender=1 blocks=3 crc_ack=1")
    print("URSUS_WS_CLIENT_SELFTEST=PASS handshake=accept+subprotocol+hello masked_tx=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
