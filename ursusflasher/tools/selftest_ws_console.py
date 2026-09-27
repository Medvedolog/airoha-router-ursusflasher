#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

import ursus_web_client as uw
from ursus_ws_terminal import LiveTerminal


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
    print("URSUS_WS_CLIENT_SELFTEST=PASS handshake=accept+subprotocol+hello masked_tx=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
