"""Use UrsusFlasher's existing XMODEM sender over UrsusBoot live stdio."""
from __future__ import annotations

from collections import deque
import hashlib
import re
import threading
import time
from pathlib import Path

import ui_terms as terms


class WebSocketSerial:
    """The read/write/reset_input interface used by proven_backend.xmodem_send.

    A single reader owns WebSocket frames. XMODEM controls are delivered as
    bytes in order, independent of how the peer split its WebSocket frames.
    """

    def __init__(self, ws):
        self.ws = ws
        self.cv = threading.Condition()
        self.chunks: deque[bytes] = deque()
        self.error: BaseException | None = None
        self.reader = threading.Thread(target=self._reader, name='ursus-xmodem-rx', daemon=True)
        self.reader.start()

    def _reader(self) -> None:
        try:
            while True:
                data = self.ws.recv_message()
                if data:
                    with self.cv:
                        self.chunks.append(data)
                        self.cv.notify_all()
        except BaseException as exc:
            with self.cv:
                self.error = exc
                self.cv.notify_all()

    def read(self, size: int = 4096, timeout: float = .2) -> bytes:
        deadline = time.monotonic() + timeout
        with self.cv:
            while not self.chunks:
                if self.error:
                    raise EOFError('UrsusBoot WebSocket disconnected') from self.error
                remain = deadline - time.monotonic()
                if remain <= 0:
                    return b''
                self.cv.wait(remain)
            data = self.chunks.popleft()
            if len(data) > size:
                self.chunks.appendleft(data[size:])
                data = data[:size]
            return data

    def write(self, data: bytes) -> None:
        # UrsusBoot permits <=2048 bytes/frame; XMODEM-CRC packets are 133 B.
        for offset in range(0, len(data), 1024):
            self.ws.send(data[offset:offset + 1024])

    def reset_input(self) -> None:
        # The UART sender calls this before block 1. Never discard the C byte
        # emitted by loadx: it is the receiver's readiness indication.
        pass

    def close(self) -> None:
        self.ws.close()
        self.reader.join(timeout=1)


def _wait_ready(link: WebSocketSerial, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    output = bytearray()
    while time.monotonic() < deadline:
        output.extend(link.read(4096, .3))
        if len(output) > 4096:
            del output[:-4096]
        lower = output.lower()
        pos = lower.find(b'ready for binary (xmodem)')
        if pos >= 0 and b'C' in output[pos + 26:]:
            return
        if b'unknown command' in lower or b'usage:' in lower:
            raise RuntimeError('UrsusBoot rejected loadx')
    raise TimeoutError('UrsusBoot loadx did not request XMODEM-CRC')


def _prompt(link: WebSocketSerial, timeout: float = 20) -> bytes:
    deadline = time.monotonic() + timeout
    output = bytearray()
    while time.monotonic() < deadline:
        output.extend(link.read(4096, .3))
        if len(output) > 8192:
            del output[:-8192]
        if re.search(rb'(?:^|[\r\n])UrsusBoot>\s*$', output):
            return bytes(output)
    raise TimeoutError('UrsusBoot prompt did not return after XMODEM')


def send_file(host: str, path: Path, address: int = 0x81800000) -> None:
    from ursus_web_client import UrsusLiveConsole, _session_log
    from proven_backend import xmodem_send

    size = path.stat().st_size
    if not 0 < size <= 64 * 1024 * 1024:
        raise ValueError('XMODEM file size must be 1..64 MiB')
    if address != 0x81800000:
        raise ValueError('only the configured load address 0x81800000 is supported')
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    ws, _hello = UrsusLiveConsole.connect(host)
    link = WebSocketSerial(ws)
    try:
        link.write(f'loadx 0x{address:x}\r'.encode('ascii'))
        _wait_ready(link)
        print(terms.tr('[XMODEM] UrsusBoot готов; передаю файл в RAM.',
                       '[XMODEM] UrsusBoot is ready; sending the file to RAM.'))
        # Reuse the same sender, CRC, retries and CAN abort as the UART path.
        from ursus_web_client import KIT
        log_dir = KIT / 'work' / 'diagnostics'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'ws-xmodem-{int(time.time())}.log'
        with log_path.open('wb') as log:
            xmodem_send(link, path, path.name, log)
        try:
            _prompt(link, timeout=8)
        except TimeoutError:
            # The sender may have consumed the prompt alongside the EOT ACK.
            link.write(b'\r')
            _prompt(link, timeout=8)
        link.write(f'hash sha256 0x{address:x} 0x{size:x}\r'.encode('ascii'))
        result = _prompt(link, timeout=30).decode('ascii', 'replace')
        if expected not in result.lower():
            raise RuntimeError('UrsusBoot SHA256 does not match the local file')
        _session_log(f'[URSUS_WS_XMODEM_OK] file={path.name} bytes={size} sha256={expected} address=0x{address:x}')
        print(terms.tr(f'[ГОТОВО] {size} байт в RAM, SHA256 совпал. Flash не записывалась. Лог: {log_path}',
                       f'[DONE] {size} bytes in RAM, SHA256 matched. Flash was not written. Log: {log_path}'))
    finally:
        link.close()
