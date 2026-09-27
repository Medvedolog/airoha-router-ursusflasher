"""Export an explicitly selected UrsusBoot RAM range with its existing TFTP server."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import threading
import time

import ui_terms as terms

from ursus_ws_xmodem import WebSocketSerial, _prompt


def receive_ram(host: str, address: int, size: int, output: Path, *,
                port: int = 1069, link: WebSocketSerial | None = None) -> None:
    from proven_backend import TftpResult, local_ip_for, receive_tftp_put
    from ursus_web_client import UrsusLiveConsole, _session_log

    if not (0x80000000 <= address < 0xC0000000 and
            0 < size <= 64 * 1024 * 1024 and address + size <= 0xC0000000):
        raise ValueError('specify a RAM range within 0x80000000..0xC0000000, at most 64 MiB')
    if not 1024 <= port <= 65535:
        raise ValueError('TFTP receiver port must be 1024..65535')
    if output.exists():
        raise FileExistsError(output)

    owned = link is None
    if owned:
        ws, _hello = UrsusLiveConsole.connect(host)
        link = WebSocketSerial(ws)
    assert link is not None
    partial = output.with_name(output.name + '.partial')
    if partial.exists():
        if owned:
            link.close()
        raise FileExistsError(partial)
    ready = threading.Event()
    cancel = threading.Event()
    result = TftpResult()
    thread = None
    try:
        # Hash before transfer proves what RAM held when the export started.
        link.write(f'hash sha256 0x{address:x} 0x{size:x}\r'.encode())
        digest_out = _prompt(link, timeout=60)
        match = re.search(rb'\b[0-9a-fA-F]{64}\b', digest_out)
        if not match:
            raise RuntimeError('UrsusBoot did not return a SHA256 for this RAM range')
        expected = match.group().decode('ascii').lower()

        bind_ip = local_ip_for(host)
        remote_name = f'ursus-ram-{int(time.time())}.bin'
        thread = threading.Thread(
            target=receive_tftp_put,
            args=(bind_ip, port, partial, remote_name, host, ready, result),
            kwargs={'cancel': cancel, 'timeout': 120},
            daemon=True,
        )
        thread.start()
        if not ready.wait(5) or result.error:
            raise RuntimeError(f'TFTP server could not bind {bind_ip}:{port}: {result.error}')
        print(terms.tr(f'[TFTP] Приём на {bind_ip}:{port}; ожидаю {size} байт из RAM.',
                       f'[TFTP] Receiving on {bind_ip}:{port}; expecting {size} RAM bytes.'))
        link.write(f'tftpput 0x{address:x} 0x{size:x} {bind_ip}:{port}:{remote_name}\r'.encode('ascii'))
        console = _prompt(link, timeout=max(90, size // 10000))
        thread.join(timeout=5)
        if thread.is_alive() or result.error:
            raise RuntimeError(f'TFTP receive failed: {result.error or "receiver did not finish"}')
        if result.bytes_transferred != size or not partial.is_file():
            raise RuntimeError(f'incomplete TFTP receive: {result.bytes_transferred}/{size}')
        got = hashlib.sha256(partial.read_bytes()).hexdigest()
        if got != expected:
            raise RuntimeError(f'RAM SHA256 {expected} differs from saved file {got}')
        if b'TFTP upload incomplete' in console or b'TFTP error' in console:
            raise RuntimeError('UrsusBoot reported a TFTP upload error')
        link.write(f'hash sha256 0x{address:x} 0x{size:x}\r'.encode())
        after = _prompt(link, timeout=60)
        if expected.encode() not in after.lower():
            raise RuntimeError('the RAM range changed during TFTP export')
        os.replace(partial, output)
        _session_log(f'[URSUS_TFTPPUT_OK] file={output} bytes={size} sha256={got} address=0x{address:x}')
        print(terms.tr(f'[ГОТОВО] {output} · {size} байт · SHA256 {got}. Flash не изменялась.',
                       f'[DONE] {output} · {size} bytes · SHA256 {got}. Flash was not modified.'))
    finally:
        cancel.set()
        if owned:
            link.close()
        if thread:
            thread.join(timeout=2)
        partial.unlink(missing_ok=True)
