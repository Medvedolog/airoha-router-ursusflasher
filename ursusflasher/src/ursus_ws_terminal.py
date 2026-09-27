"""UrsidoRescue-inspired terminal for the UrsusBoot live WebSocket console.

Only the transport differs from the UART terminal: keyboard input and device
output remain byte streams.  Local controls are never sent to the bootloader.
"""
from __future__ import annotations

import os
import re
import select
import shutil
import sys
import threading
import time
from pathlib import Path

import console_ui as ui
import ui_terms as terms


def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


_FKEYS = {
    b'\x1bOQ': 'upload', b'\x1b[12~': 'upload',  # F2
    b'\x1bOR': 'download', b'\x1b[13~': 'download',  # F3
    b'\x1bOS': 'mode', b'\x1b[14~': 'mode',  # F4
    b'\x1b[21~': 'quit', b'\x1b[10~': 'quit',  # F10
}
_ARROWS = {b'\x1b[A': 'up', b'\x1b[B': 'down', b'\x1bOA': 'up', b'\x1bOB': 'down'}
_FULLSCREEN = re.compile(rb'\x1b\[\?(?:1049|1047|47)h')
_ALT_OFF = re.compile(rb'\x1b\[\?(?:1049|1047|47)l')


class LiveTerminal:
    def __init__(self, ws, host: str):
        self.ws, self.host = ws, host
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.raw = True
        self.pager = False
        self.paused = False
        self.pending = bytearray()
        self.lines = 0
        self.history: list[str] = []
        self.index = 0
        self.line = ''
        self.cols = self.rows = 0
        self.chrome = False
        self.suspended = False
        self.ansi_tail = b''
        self.keybuf = bytearray()
        self.key_at = 0.0
        self.menu = False
        self.action: str | None = None

    @staticmethod
    def _style(text: str, fg: str = '242;232;218', bg: str = '36;24;14') -> str:
        return f'\x1b[38;2;{fg};48;2;{bg}m{text}\x1b[0m'

    def _bars(self) -> bytes:
        cols = self.cols
        mode = 'RAW' if self.raw else 'LINE'
        header = f' UrsusFlasher  ·  UrsusBoot {self.host}  ●  WebSocket  ·  {mode} '
        rule = tr('── ЖИВАЯ КОНСОЛЬ ', '── LIVE CONSOLE ')
        rule += '─' * max(0, cols - len(rule))
        hints = tr(' F2 ↑HTTP · F3 ↓логи · F4 строки/RAW · F10 выход · Ctrl+] меню ',
                   ' F2 ↑HTTP · F3 ↓logs · F4 line/RAW · F10 quit · Ctrl+] menu ')
        if self.pager:
            hints += tr(' [ВКЛ]', ' [ON]')
        footer = hints[:cols].ljust(cols)
        return (f'\x1b[1;1H\x1b[2K{self._style(header[:cols].ljust(cols), "217;154;77")}'
                f'\x1b[2;1H\x1b[2K{self._style(rule[:cols], "168;145;121")}'
                f'\x1b[{self.rows-1};1H\x1b[2K{self._style("─" * cols, "168;145;121")}'
                f'\x1b[{self.rows};1H\x1b[2K{self._style(footer, "239;192;121")}').encode('utf-8')

    def _write(self, data: bytes) -> None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def _refresh(self) -> None:
        if not self.chrome or self.suspended:
            return
        self._write(b'\x1b7' + self._bars() + f'\x1b[3;{self.rows-2}r'.encode() + b'\x1b8')

    def _start(self) -> None:
        self.cols, self.rows = shutil.get_terminal_size((100, 30))
        if not sys.stdout.isatty() or os.environ.get('NO_COLOR') or self.cols < 40 or self.rows < 10:
            return
        ui._enable_windows_ansi()
        self.chrome = True
        self.suspended = False
        self._write(b'\x1b[r' + b'\r\n' * self.rows + b'\x1b[H\x1b[2J' + self._bars()
                    + f'\x1b[3;{self.rows-2}r\x1b[3;1H'.encode())

    def _end(self) -> None:
        if self.chrome:
            self._write(b'\x1b[r' + f'\x1b[{self.rows};1H\r\n'.encode())
            self.chrome = False

    def _output(self, data: bytes) -> None:
        with self.lock:
            if self.chrome and not self.suspended:
                size = shutil.get_terminal_size((100, 30))
                if size != (self.cols, self.rows):
                    self.cols, self.rows = size
                    if self.cols < 40 or self.rows < 10:
                        self._end()
                    else:
                        self._refresh()
            probe = self.ansi_tail + data
            self.ansi_tail = probe[-64:]
            if _FULLSCREEN.search(probe):
                self._flush_pager()
                self.pager = self.paused = False
                if self.chrome and not self.suspended:
                    self._write(b'\x1b7\x1b[r\x1b8')
                    self.suspended = True
            if self.suspended and _ALT_OFF.search(probe):
                self.suspended = False
                self._refresh()
            if not self.pager:
                self._write(data)
                return
            self.pending.extend(data)
            if len(self.pending) > 4 * 1024 * 1024:
                self._flush_pager()
                self.pager = self.paused = False
                self._refresh()
            elif not self.paused:
                self._pager_page()

    def _flush_pager(self) -> None:
        if self.pending:
            self._write(bytes(self.pending))
            self.pending.clear()
        self.lines = 0

    def _pager_page(self) -> None:
        quota = max(1, (self.rows - 5 if self.chrome else self.rows - 2) - self.lines)
        pos = 0
        for _ in range(quota):
            i = self.pending.find(b'\n', pos)
            if i < 0:
                break
            pos = i + 1
        if pos:
            count = self.pending[:pos].count(b'\n')
            self._write(bytes(self.pending[:pos]))
            del self.pending[:pos]
            self.lines += count
        if self.lines >= (self.rows - 5 if self.chrome else self.rows - 2) and self.pending:
            self.paused = True
            self._write(tr('\r\n-- ещё: Enter продолжить · Ctrl+P выключить --',
                           '\r\n-- More: Enter continue · Ctrl+P disable --').encode())
        elif not pos and self.pending:
            self._flush_pager()

    def _reader(self) -> None:
        try:
            while not self.stop.is_set():
                data = self.ws.recv_message()
                if data:
                    self._output(data)
        except EOFError:
            pass
        except Exception as exc:
            if not self.stop.is_set():
                with self.lock:
                    self._write(f'\r\n[WebSocket: {exc}]\r\n'.encode())
        finally:
            self.stop.set()

    def _line_key(self, key: bytes) -> None:
        if key in _ARROWS:
            action = _ARROWS[key]
            if action == 'up' and self.history:
                self.index = max(0, self.index - 1)
            elif action == 'down':
                self.index = min(len(self.history), self.index + 1)
            else:
                return
            self.line = self.history[self.index] if self.index < len(self.history) else ''
        elif key in (b'\r', b'\n'):
            if self.line and (not self.history or self.history[-1] != self.line):
                self.history.append(self.line)
            self.index = len(self.history)
            self.ws.send(self.line.encode('ascii') + b'\r')
            self.line = ''
            self._write(b'\r\n')
            return
        elif key in (b'\x7f', b'\x08'):
            self.line = self.line[:-1]
        elif key == b'\x03':
            self.ws.send(key)
            self.line = ''
        elif key == b'\x15':
            self.line = ''
        elif len(key) == 1 and 32 <= key[0] < 127:
            self.line += key.decode('ascii')
        else:
            return
        with self.lock:
            self._write(b'\r\x1b[2K] ' + self.line.encode('ascii'))

    def _menu_choice(self, key: bytes) -> None:
        self.menu = False
        if key in (b'q', b'Q'):
            self.stop.set()
        elif key in (b's', b'S'):
            self.action = 'upload'
            self.stop.set()
        elif key in (b'd', b'D'):
            self.action = 'download'
            self.stop.set()
        elif key in (b'l', b'L', b'r', b'R'):
            self.raw = not self.raw
            self.line = ''
        elif key in (b'p', b'P'):
            self._toggle_pager()
        with self.lock:
            self._refresh()

    def _toggle_pager(self) -> None:
        with self.lock:
            self.pager = not self.pager
            self.paused = False
            self.lines = 0
            if not self.pager:
                self._flush_pager()
            self._refresh()

    def _input(self, key: bytes) -> None:
        if self.menu:
            self._menu_choice(key)
        elif key in (b'\x11', b'\x1b[21~', b'\x1b[10~'):
            self.stop.set()
        elif key == b'\x1d':
            self.menu = True
            with self.lock:
                self._write(tr('\r\n[меню: S отправить HTTP · D скачать логи · L строки/RAW · P пейджер · Q выход]\r\n',
                               '\r\n[menu: S send HTTP · D save logs · L line/RAW · P pager · Q quit]\r\n').encode())
        elif key == b'\x10':
            self._toggle_pager()
        elif key in (b'\x1bOQ', b'\x1b[12~'):
            self.action = 'upload'
            self.stop.set()
        elif key in (b'\x1bOR', b'\x1b[13~'):
            self.action = 'download'
            self.stop.set()
        elif key in (b'\x1bOS', b'\x1b[14~'):
            self.raw = not self.raw
            self.line = ''
            with self.lock:
                self._refresh()
        elif self.paused and key in (b'\r', b'\n'):
            with self.lock:
                self.paused = False
                self.lines = 0
                self._pager_page()
        elif self.paused:
            return
        elif self.raw:
            self.ws.send(key)
        else:
            self._line_key(key)

    def _keys(self, data: bytes, *, flush: bool = False) -> None:
        self.keybuf.extend(data)
        while self.keybuf:
            if self.raw and not self.menu and not self.paused and self.keybuf[0] != 27:
                end = next((i for i, b in enumerate(self.keybuf) if b in (27, 29, 17, 16)), len(self.keybuf))
                if end:
                    self.ws.send(bytes(self.keybuf[:end]))
                    del self.keybuf[:end]
                    continue
            if self.keybuf[0] != 27:
                key = bytes(self.keybuf[:1])
                del self.keybuf[:1]
                self._input(key)
                continue
            buf = bytes(self.keybuf)
            seqs = (*_FKEYS, *_ARROWS)
            match = next((s for s in seqs if buf.startswith(s)), None)
            if match:
                del self.keybuf[:len(match)]
                self._input(match)
            elif not flush and len(buf) < 12 and any(s.startswith(buf) for s in seqs):
                break
            else:
                # Unknown escape sequences remain device input in raw mode.
                end = next((i for i, b in enumerate(buf[2:], 2) if 64 <= b <= 126), 0)
                n = end + 1 if len(buf) > 2 and buf[1:2] in (b'[', b'O') and end else 1
                key = buf[:n]
                del self.keybuf[:n]
                self._input(key)

    def run(self, hello: bytes) -> None:
        if not sys.stdin.isatty():
            raise RuntimeError(tr('Живой консоли нужен интерактивный терминал.',
                                  'The live console requires an interactive terminal.'))
        if os.name == 'nt':
            import msvcrt
        else:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
        try:
            if os.name != 'nt':
                tty.setraw(fd)
            with self.lock:
                self._start()
                self._write(hello + (b'\r\n' if hello and not hello.endswith(b'\n') else b''))
                self._write(tr('WebSocket · F2 файл через HTTP · F3 логи на ПК · F4 строки/RAW · F10 выход · Ctrl+] меню\r\n',
                               'WebSocket · F2 file over HTTP · F3 save logs · F4 line/RAW · F10 quit · Ctrl+] menu\r\n').encode())
                self._write(tr('Ожидаем вывод устройства. Enter покажет приглашение; команды записи не ограничены.\r\n',
                               'Waiting for device output. Enter requests a prompt; flash commands are unrestricted.\r\n').encode())
            reader = threading.Thread(target=self._reader, name='ursus-ws-console-rx', daemon=True)
            reader.start()
            while not self.stop.is_set():
                if os.name == 'nt':
                    if not msvcrt.kbhit():
                        time.sleep(.03)
                        continue
                    ch = msvcrt.getwch()
                    if ch in ('\x00', '\xe0'):
                        scan = msvcrt.getwch()
                        key = {'<': b'\x1bOQ', '=': b'\x1bOR', '>': b'\x1bOS', 'D': b'\x1b[21~',
                               'H': b'\x1b[A', 'P': b'\x1b[B'}.get(scan)
                    else:
                        key = ch.encode('utf-8', 'replace')
                    if key:
                        self._keys(key)
                else:
                    ready, _, _ = select.select([fd], [], [], .05)
                    if ready:
                        data = os.read(fd, 4096)
                        if not data:
                            break
                        self.key_at = time.monotonic()
                        self._keys(data)
                    elif self.keybuf and time.monotonic() - self.key_at > .05:
                        self._keys(b'', flush=True)
        finally:
            self.stop.set()
            self.ws.close()
            if 'reader' in locals():
                reader.join(timeout=1)
            with self.lock:
                self._end()
            if os.name != 'nt':
                termios.tcsetattr(fd, termios.TCSADRAIN, old)


def live_console(host: str) -> None:
    # Import lazily: ursus_web_client owns the authenticated WebSocket framing.
    from ursus_web_client import UrsusLiveConsole, _session_log

    while True:
        ws, hello = UrsusLiveConsole.connect(host)
        terminal = LiveTerminal(ws, host)
        try:
            terminal.run(hello)
        finally:
            ws.close()
            _session_log(f'[URSUS_WS_DISCONNECTED] host={host}')
        if terminal.action is None:
            return
        # UrsusBoot explicitly locks other HTTP requests while a WebSocket
        # console owns the control plane.  The terminal has already detached.
        try:
            _wait_http_ready(host)
            if terminal.action == 'upload':
                _send_http(host)
            else:
                _save_diagnostics(host)
        except Exception as exc:
            print(tr(f'[ОШИБКА] {exc}', f'[ERROR] {exc}'))
        answer = input(tr('Вернуться к живой консоли? [Y/n]: ',
                          'Return to the live console? [Y/n]: ')).strip().lower()
        if answer in ('n', 'no', 'н', 'нет'):
            return


def _wait_http_ready(host: str) -> None:
    from ursus_web_client import status

    for attempt in range(20):
        try:
            status(host)
            return
        except Exception:
            if attempt == 19:
                raise
            time.sleep(.1)


def _send_http(host: str) -> None:
    from ursus_web_client import upload

    print(tr('Передача по HTTP в RAM UrsusBoot. Flash не записывается.',
             'HTTP transfer into UrsusBoot RAM. Flash is not written.'))
    print(tr('1 initramfs · 2 прошивка OpenWrt · 3 UrsusBoot FIP · 4 Vanilla FIP · 5 UBI preloader',
             '1 initramfs · 2 OpenWrt firmware · 3 UrsusBoot FIP · 4 Vanilla FIP · 5 UBI preloader'))
    kind = {'1': 'initramfs', '2': 'firmware', '3': 'fip',
            '4': 'vanilla-fip', '5': 'preloader'}.get(input(tr('Тип файла [Enter — назад]: ',
                                                            'File type [Enter — back]: ')).strip())
    if kind is None:
        return
    name = input(tr('Путь к файлу [Enter — назад]: ', 'File path [Enter — back]: ')).strip().strip('"')
    if not name:
        return
    result = upload(host, Path(name).expanduser(), kind)
    print(tr(f'[ГОТОВО] Файл принят в RAM: {result.get("result")}. Запись и запуск не выполнялись.',
             f'[DONE] File accepted into RAM: {result.get("result")}. No write or boot was started.'))


def _save_diagnostics(host: str) -> None:
    from ursus_web_client import collect_diagnostics

    path = collect_diagnostics(host, 'live-console-operator-request')
    print(tr(f'[ГОТОВО] Диагностика сохранена: {path}', f'[DONE] Diagnostics saved: {path}'))
