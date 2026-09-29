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
    b'\x1b[15~': 'nand',  # F5
    b'\x1b[21~': 'quit', b'\x1b[10~': 'quit',  # F10
}
_ARROWS = {b'\x1b[A': 'up', b'\x1b[B': 'down', b'\x1bOA': 'up', b'\x1bOB': 'down'}
_FULLSCREEN = re.compile(rb'\x1b\[\?(?:1049|1047|47)h')
_ALT_OFF = re.compile(rb'\x1b\[\?(?:1049|1047|47)l')
_PROMPT = b'UrsusBoot> '
# UrsusBoot t77 echoes a deleted character with printf("\\b \\b"): the two-character
# text backslash-b instead of the BS byte.  Repaired here; harmless once fixed there.
_BROKEN_ERASE = b'\\b \\b'
_CTRL_C_CONFIRM_S = 2.0

# Console colours: dark green screen, light green text (the UrsidoFlasher look).
# Everything drawn around it (bars, prompts) uses other colours on purpose.
_BG = '7;32;17'
_FG = '158;222;168'
_BODY = f'\x1b[0;38;2;{_FG};48;2;{_BG}m'          # reset, then the screen colours
_SGR_RESET = re.compile(rb'\x1b\[0?m')
_ARROWS_LR = {b'\x1b[C', b'\x1b[D', b'\x1bOC', b'\x1bOD'}   # the device shell has no cursor editing


class _ConsoleInputMode:
    """Windows: deliver Ctrl-C as a key instead of raising KeyboardInterrupt.

    In the live console Ctrl-C is a device key.  With ENABLE_PROCESSED_INPUT on,
    the same press also interrupts the flasher itself, which used to tear the
    session down while the byte still reached the router.
    """

    def __enter__(self):
        self.handle = self.old = None
        if os.name == 'nt':
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                handle = k32.GetStdHandle(-10)
                mode = ctypes.c_uint32()
                if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                    self.handle, self.old = handle, mode.value
                    k32.SetConsoleMode(handle, mode.value & ~0x0001)
            except Exception:
                self.handle = None
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            try:
                import ctypes
                ctypes.windll.kernel32.SetConsoleMode(self.handle, self.old)
            except Exception:
                pass


class SerialLink:
    """The terminal's link interface (send / recv_message / close) over a COM port.

    ``recv_message`` returns b'' when the line is idle, which the reader loop
    treats as "nothing yet", so the same terminal serves WebSocket and UART.
    """

    def __init__(self, sp):
        self.sp = sp
        self.closed = False

    def send(self, data: bytes) -> None:
        self.sp.write(bytes(data))

    def recv_message(self) -> bytes:
        if self.closed:
            raise EOFError('UART closed')
        return self.sp.read(4096, .1)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.sp.close()


class LiveTerminal:
    def __init__(self, ws, host: str, *, uart: str | None = None):
        self.ws, self.host = ws, host
        self.uart = uart                # COM port name: same terminal, no network functions
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
        self.tail_line = b''            # device output after its last newline
        self.rawline = ''               # what the device's line buffer holds (RAW mode)
        self.ctrlc_at = 0.0
        self.resize_at = 0.0
        self.chrome = False
        self.suspended = False
        self.ansi_tail = b''
        self.keybuf = bytearray()
        self.key_at = 0.0
        self.menu = False
        self.action: str | None = None

    @staticmethod
    def _style(text: str, fg: str = '214;240;218', bg: str = '18;74;38') -> str:
        return f'\x1b[38;2;{fg};48;2;{bg}m{text}{_BODY}'

    def _bars(self) -> bytes:
        cols = self.cols
        mode = 'RAW' if self.raw else 'LINE'
        if self.uart:
            header = f' UrsusFlasher  ·  UART {self.uart}  ●  115200 8N1  ·  {mode} '
        else:
            header = f' UrsusFlasher  ·  UrsusBoot {self.host}  ●  WebSocket  ·  {mode} '
        rule = tr('── ЖИВАЯ КОНСОЛЬ ', '── LIVE CONSOLE ')
        rule += '─' * max(0, cols - len(rule))
        if self.uart:
            hints = tr(' F4 строки/RAW · Ctrl+P пейджер · F10 выход ', ' F4 line/RAW · Ctrl+P pager · F10 quit ')
        else:
            hints = tr(' F2 ↑файл · F3 ↓файл · F4 строки/RAW · F5 NAND · F10 выход ',
                       ' F2 ↑file · F3 ↓file · F4 line/RAW · F5 NAND · F10 quit ')
        if self.pager:
            hints += tr(' [ВКЛ]', ' [ON]')
        footer = hints[:cols].ljust(cols)
        return (f'\x1b[1;1H\x1b[2K{self._style(header[:cols].ljust(cols), "226;246;228", "18;74;38")}'
                f'\x1b[2;1H\x1b[2K{self._style(rule[:cols], "110;176;122", _BG)}'
                f'\x1b[{self.rows-1};1H\x1b[2K{self._style("─" * cols, "110;176;122", _BG)}'
                f'\x1b[{self.rows};1H\x1b[2K{self._style(footer, "226;246;228", "18;74;38")}').encode('utf-8')

    def _write(self, data: bytes) -> None:
        out = getattr(sys.stdout, 'buffer', None)
        if out is None:                 # a wrapper without a byte layer: fall back to text
            sys.stdout.write(data.decode('utf-8', 'replace'))
            sys.stdout.flush()
            return
        out.write(data)
        out.flush()

    def _refresh(self, stale_rows: tuple = ()) -> None:
        if not self.chrome or self.suspended:
            return
        erase = b''.join(f'\x1b[{r};1H\x1b[2K'.encode() for r in stale_rows)
        self._write(b'\x1b7\x1b[r' + erase + self._bars() + f'\x1b[3;{self.rows-2}r'.encode() + b'\x1b8')

    def _check_resize(self, *, force: bool = False) -> None:
        """Follow the window size, also while the device is silent."""
        now = time.monotonic()
        if not force and now - self.resize_at < .15:
            return
        self.resize_at = now
        with self.lock:
            if not self.chrome or self.suspended:
                return
            size = shutil.get_terminal_size((100, 30))
            if size == (self.cols, self.rows):
                return
            old_rows = self.rows
            self.cols, self.rows = size
            if self.cols < 40 or self.rows < 10:
                self._end()
                return
            # bars drawn for the old size are now in the middle of the screen
            self._refresh(stale_rows=tuple(r for r in (old_rows - 1, old_rows) if r <= self.rows - 2))

    def _start(self) -> None:
        self.cols, self.rows = shutil.get_terminal_size((100, 30))
        if not sys.stdout.isatty() or os.environ.get('NO_COLOR') or self.cols < 40 or self.rows < 10:
            return
        ui._enable_windows_ansi()
        self.chrome = True
        self.suspended = False
        self._write(b'\x1b[r' + b'\r\n' * self.rows + b'\x1b[H' + _BODY.encode() + b'\x1b[2J' + self._bars()
                    + f'\x1b[3;{self.rows-2}r\x1b[3;1H'.encode())

    def _end(self) -> None:
        if self.chrome:
            self._write(b'\x1b[r\x1b[0m' + f'\x1b[{self.rows};1H\r\n'.encode())
            self.chrome = False

    def _output(self, data: bytes) -> None:
        with self.lock:
            self._check_resize(force=True)
            data = data.replace(_BROKEN_ERASE, b'\x08 \x08')
            if self.chrome:
                data = _SGR_RESET.sub(_BODY.encode(), data)
            self.tail_line = (self.tail_line + data).rsplit(b'\n', 1)[-1][-200:]
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
        elif key == b'\x15':
            self.line = ''
        elif len(key) == 1 and 32 <= key[0] < 127:
            self.line += key.decode('ascii')
        else:
            return
        with self.lock:
            self._write(b'\r\x1b[2K] ' + self.line.encode('ascii'))

    def _request_action(self, action: str) -> None:
        if self.uart:
            with self.lock:
                self._write(tr('\r\n[Отправка файла, приём и NAND работают по Ethernet (WebSocket); на UART доступен только терминал.]\r\n',
                               '\r\n[File transfer and NAND work over Ethernet (WebSocket); on the UART this is a terminal only.]\r\n').encode())
            return
        self.action = action
        self.stop.set()

    def _menu_choice(self, key: bytes) -> None:
        self.menu = False
        if key in (b'q', b'Q'):
            self.stop.set()
        elif key in (b's', b'S'):
            self._request_action('upload')
        elif key in (b'd', b'D'):
            self._request_action('download')
        elif key in (b'n', b'N'):
            self._request_action('nand')
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
                self._write(tr('\r\n[меню: S отправить · D скачать · N NAND · L строки/RAW · P пейджер · Q выход]\r\n',
                               '\r\n[menu: S send · D save · N NAND · L line/RAW · P pager · Q quit]\r\n').encode())
        elif key == b'\x10':
            self._toggle_pager()
        elif key in (b'\x1bOQ', b'\x1b[12~'):
            self._request_action('upload')
        elif key in (b'\x1bOR', b'\x1b[13~'):
            self._request_action('download')
        elif key in (b'\x1bOS', b'\x1b[14~'):
            self.raw = not self.raw
            self.line = ''
            with self.lock:
                self._refresh()
        elif key == b'\x1b[15~':
            self._request_action('nand')
        elif key == b'\x03':
            self._ctrl_c()
        elif self.paused and key in (b'\r', b'\n'):
            with self.lock:
                self.paused = False
                self.lines = 0
                self._pager_page()
        elif self.paused:
            return
        elif key in _ARROWS_LR:
            return
        elif self.raw:
            if key in _ARROWS:
                self._raw_history(_ARROWS[key])
            else:
                self._track_raw(key)
                self.ws.send(key)
        else:
            self._line_key(key)

    def _track_raw(self, chunk: bytes) -> None:
        """Mirror the device's line buffer so history can replace it."""
        for b in chunk:
            if b in (13, 10):
                if self.rawline and (not self.history or self.history[-1] != self.rawline):
                    self.history.append(self.rawline)
                self.index = len(self.history)
                self.rawline = ''
            elif b in (8, 127):
                self.rawline = self.rawline[:-1]
            elif b in (3, 21):
                self.rawline = ''
            elif 32 <= b < 127:
                self.rawline += chr(b)

    def _raw_history(self, action: str) -> None:
        """Up/Down in RAW mode: the device shell has no history, so replace its line locally."""
        if not self._idle_at_prompt() or not self.history and action == 'up':
            return
        if action == 'up':
            self.index = max(0, self.index - 1)
        else:
            self.index = min(len(self.history), self.index + 1)
        line = self.history[self.index] if self.index < len(self.history) else ''
        self.ws.send(b'\x15' + line.encode('ascii', 'replace'))    # Ctrl-U erases the device line
        self.rawline = line

    def _idle_at_prompt(self) -> bool:
        return self.tail_line.startswith(_PROMPT)

    def _ctrl_c(self) -> None:
        """Ctrl-C interrupts a running command.  At the idle prompt it would make
        UrsusBoot stop WebFailsafe -- this connection and every later one dies
        until `ursusweb` is started again on the UART -- so it needs a second press."""
        now = time.monotonic()
        if not self.uart and self._idle_at_prompt() and now - self.ctrlc_at > _CTRL_C_CONFIRM_S:
            self.ctrlc_at = now
            with self.lock:
                self._write(tr(
                    '\r\n[Ctrl-C на приглашении остановил бы WebFailsafe и оборвал эту консоль до `ursusweb` на UART. '
                    'НЕ отправлено. Выход из консоли: F10. Отправить всё равно: Ctrl-C ещё раз за 2 с.]\r\n',
                    '\r\n[Ctrl-C at the idle prompt would stop WebFailsafe and drop this console until `ursusweb` is '
                    'run on the UART. NOT sent. Leave the console: F10. Send anyway: press Ctrl-C again within 2 s.]\r\n').encode()
                    + self.tail_line)
            return
        self.ctrlc_at = 0.0
        self.line = ''
        self.rawline = ''
        self.ws.send(b'\x03')

    def _keys(self, data: bytes, *, flush: bool = False) -> None:
        self.keybuf.extend(data)
        while self.keybuf:
            if self.raw and not self.menu and not self.paused and self.keybuf[0] != 27:
                end = next((i for i, b in enumerate(self.keybuf) if b in (27, 29, 17, 16, 3)), len(self.keybuf))
                if end:
                    chunk = bytes(self.keybuf[:end])
                    self._track_raw(chunk)
                    self.ws.send(chunk)
                    del self.keybuf[:end]
                    continue
            if self.keybuf[0] != 27:
                key = bytes(self.keybuf[:1])
                del self.keybuf[:1]
                self._input(key)
                continue
            buf = bytes(self.keybuf)
            seqs = (*_FKEYS, *_ARROWS, *_ARROWS_LR)
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
        input_mode = _ConsoleInputMode().__enter__()
        try:
            if os.name != 'nt':
                tty.setraw(fd)
            with self.lock:
                self._start()
                self._write(hello + (b'\r\n' if hello and not hello.endswith(b'\n') else b''))
                if self.uart:
                    self._write(tr(f'UART {self.uart} · 115200 8N1 · F4 строки/RAW · F10 выход\r\n',
                                   f'UART {self.uart} · 115200 8N1 · F4 line/RAW · F10 quit\r\n').encode())
                else:
                    self._write(tr('WebSocket · F2 HTTP/XMODEM в RAM · F3 TFTP/диагностика · F4 строки/RAW · F5 NAND · F10 выход\r\n',
                                   'WebSocket · F2 HTTP/XMODEM to RAM · F3 TFTP/diagnostics · F4 line/RAW · F5 NAND · F10 quit\r\n').encode())
                self._write(tr('Ожидаем вывод устройства. Enter покажет приглашение; команды записи не ограничены.\r\n',
                               'Waiting for device output. Enter requests a prompt; flash commands are unrestricted.\r\n').encode())
            reader = threading.Thread(target=self._reader, name='ursus-ws-console-rx', daemon=True)
            reader.start()
            while not self.stop.is_set():
                try:
                    self._pump_input(msvcrt if os.name == 'nt' else None, fd if os.name != 'nt' else None)
                except KeyboardInterrupt:
                    # Console mode could not be changed: still treat it as the Ctrl-C key.
                    self._ctrl_c()
        finally:
            input_mode.__exit__()
            self.stop.set()
            self.ws.close()
            if 'reader' in locals():
                reader.join(timeout=1)
            with self.lock:
                self._end()
            if os.name != 'nt':
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _pump_input(self, msvcrt, fd) -> None:
        """One pass of the keyboard loop; sets ``stop`` when the keyboard is gone."""
        self._check_resize()
        if msvcrt is not None:
            if not msvcrt.kbhit():
                time.sleep(.03)
                return
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                scan = msvcrt.getwch()
                key = {'<': b'\x1bOQ', '=': b'\x1bOR', '>': b'\x1bOS', '?': b'\x1b[15~', 'D': b'\x1b[21~',
                       'H': b'\x1b[A', 'P': b'\x1b[B'}.get(scan)
            else:
                key = ch.encode('utf-8', 'replace')
            if key:
                self._keys(key)
            return
        ready, _, _ = select.select([fd], [], [], .05)
        if ready:
            data = os.read(fd, 4096)
            if not data:
                self.stop.set()
                return
            self.key_at = time.monotonic()
            self._keys(data)
        elif self.keybuf and time.monotonic() - self.key_at > .05:
            self._keys(b'', flush=True)


def live_console_uart(port: str | None = None) -> None:
    """The live console terminal over a COM port -- a plain UART terminal, no network needed."""
    from proven_backend import RecoverySerial
    import ursusboot_update

    port = port or ursusboot_update.choose_port()
    sp = RecoverySerial(port)
    link = SerialLink(sp)
    terminal = LiveTerminal(link, port, uart=port)
    try:
        terminal.run(b'')
    finally:
        link.close()                # also closes the port: other tools can use it again


def _connect_hint(exc: Exception) -> str:
    """Say what the failure means: 409 is a live server whose console slot is taken, not a stopped one."""
    if '409' in str(exc):
        return tr(
            'Роутер отвечает, но прежняя консольная сессия ещё считается открытой (она не закрылась штатно). '
            'Закройте другие окна UrsusFlasher; UrsusBoot t79 и новее снимает такую сессию сам примерно через минуту, '
            'на более старом — выполните на UART `ursusweb` (Ctrl-C, затем `ursusweb`) или перезагрузите роутер.',
            'The router answers, but an earlier console session is still counted as open (it did not close cleanly). '
            'Close other UrsusFlasher windows; UrsusBoot t79 and later drops such a session by itself after about a minute; '
            'on an older one run `ursusweb` on the UART (Ctrl-C, then `ursusweb`) or reboot the router.')
    return tr(
        'Если консоль закрыли Ctrl-C на приглашении, UrsusBoot остановил WebFailsafe: '
        'на UART выполните `ursusweb` и подключитесь снова.',
        'If the console was left with Ctrl-C at the prompt, UrsusBoot stopped WebFailsafe: '
        'run `ursusweb` on the UART and connect again.')


def live_console(host: str) -> None:
    # Import lazily: ursus_web_client owns the authenticated WebSocket framing.
    from ursus_web_client import UrsusLiveConsole, _session_log

    while True:
        try:
            ws, hello = UrsusLiveConsole.connect(host)
        except Exception as exc:
            raise RuntimeError(f'{exc}. ' + _connect_hint(exc)) from exc
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
            if terminal.action == 'upload':
                _send_file(host)
            elif terminal.action == 'nand':
                from ursus_ws_nand import menu
                menu(host)
            else:
                _receive_file(host)
        except Exception as exc:
            print(tr(f'[ОШИБКА] {exc}', f'[ERROR] {exc}'))
        answer = ui.prompt(tr('Вернуться к живой консоли? [Y/n]: ',
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


def _send_file(host: str) -> None:
    from ursus_web_client import upload

    ui.section(tr('Передача файла в RAM UrsusBoot', 'Send a file to UrsusBoot RAM'), style='amber2')
    ui.note(tr('Flash не записывается.', 'Flash is not written.'))
    for number, ru, en in ((1, 'initramfs', 'initramfs'), (2, 'прошивка OpenWrt', 'OpenWrt firmware'),
                           (3, 'UrsusBoot FIP', 'UrsusBoot FIP'), (4, 'Vanilla FIP', 'Vanilla FIP'),
                           (5, 'UBI preloader', 'UBI preloader'), (6, 'произвольный файл (XMODEM)', 'arbitrary file (XMODEM)')):
        ui.menu_item(number, tr(ru, en))
    choice = ui.prompt(tr('Тип файла [Enter — назад]: ', 'File type [Enter — back]: ')).strip()
    kind = {'1': 'initramfs', '2': 'firmware', '3': 'fip',
            '4': 'vanilla-fip', '5': 'preloader'}.get(choice)
    if kind is None and choice != '6':
        return
    name = ui.prompt(tr('Путь к файлу [Enter — назад]: ', 'File path [Enter — back]: ')).strip().strip('"')
    if not name:
        return
    if choice == '6':
        from ursus_ws_xmodem import send_file
        send_file(host, Path(name).expanduser())
        return
    _wait_http_ready(host)
    result = upload(host, Path(name).expanduser(), kind)
    print(tr(f'[ГОТОВО] Файл принят в RAM: {result.get("result")}. Запись и запуск не выполнялись.',
             f'[DONE] File accepted into RAM: {result.get("result")}. No write or boot was started.'))


def _receive_file(host: str) -> None:
    from ursus_web_client import collect_diagnostics, KIT

    ui.section(tr('Получить с роутера', 'Get from the router'), style='amber2')
    ui.menu_item(1, tr('Диагностика UrsusBoot по HTTP', 'UrsusBoot HTTP diagnostics'))
    ui.menu_item(2, tr('Диапазон RAM через TFTP PUT', 'RAM range over TFTP PUT'))
    choice = ui.prompt(tr('Что сохранить [Enter — назад]: ', 'Save what [Enter — back]: ')).strip()
    if choice == '1':
        _wait_http_ready(host)
        path = collect_diagnostics(host, 'live-console-operator-request')
        print(tr(f'[ГОТОВО] Диагностика сохранена: {path}', f'[DONE] Diagnostics saved: {path}'))
    elif choice == '2':
        from ursus_ws_tftp import receive_ram

        address = int(ui.prompt(tr('Адрес RAM [0x81800000]: ', 'RAM address [0x81800000]: ')).strip()
                      or '0x81800000', 0)
        size = int(ui.prompt(tr('Длина в байтах (например 0x100000): ',
                            'Length in bytes (e.g. 0x100000): ')).strip(), 0)
        default = KIT / 'work' / 'diagnostics' / f'ursus-ram-{int(time.time())}.bin'
        name = ui.prompt(tr(f'Файл на ПК [{default}]: ', f'PC output file [{default}]: ')).strip().strip('"')
        receive_ram(host, address, size, Path(name).expanduser() if name else default)
