#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

_ENABLED = False
_STARTUP_BEAR_SHOWN = False

STYLES = {
    # UrsusBoot WebFailsafe palette, mirrored in the terminal with 24-bit ANSI.
    # CSS source: webfailsafe-alpha4.html
    'reset': '0',
    'bold': '1',
    'ink': '38;2;242;232;218',       # #F2E8DA
    'muted': '38;2;168;145;121',     # #A89179
    'amber': '1;38;2;217;154;77',    # #D99A4D
    'amber2': '1;38;2;200;135;58',   # #C8873A
    'sand': '1;38;2;239;192;121',    # #EFC079
    'ok': '1;38;2;124;196;147',      # #7CC493
    'bad': '1;38;2;232;131;122',     # #E8837A

    # Compatibility aliases for older call sites. They intentionally map to
    # the UrsusBoot palette; no cyan/blue/magenta is emitted.
    'dim': '38;2;168;145;121',
    'cyan': '1;38;2;217;154;77',
    'blue': '1;38;2;200;135;58',
    'green': '1;38;2;124;196;147',
    'yellow': '1;38;2;239;192;121',
    'red': '1;38;2;232;131;122',
    'magenta': '1;38;2;239;192;121',
    'white': '38;2;242;232;218',
}



def _enable_windows_ansi() -> None:
    if os.name != 'nt':
        return
    try:
        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def enable() -> bool:
    global _ENABLED
    _enable_windows_ansi()
    _ENABLED = bool(getattr(sys.stdout, 'isatty', lambda: False)()) and not os.environ.get('NO_COLOR')
    return _ENABLED


def enabled() -> bool:
    return _ENABLED


def paint(text: str, style: str = 'reset') -> str:
    if not _ENABLED or not text:
        return text
    code = STYLES.get(style, style)
    return f'\x1b[{code}m{text}\x1b[0m'


def _glyph(preferred: str, fallback: str) -> str:
    enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        preferred.encode(enc)
        return preferred
    except Exception:
        return fallback


def width() -> int:
    cols = shutil.get_terminal_size((100, 30)).columns
    return max(72, min(cols - 2, 104))


def rule(title: str | None = None, *, style: str = 'amber') -> None:
    ch = _glyph('─', '-')
    n = width()
    if title:
        label = f' {title} '
        remaining = max(4, n - len(label))
        left = min(4, remaining // 2)
        text = ch * left + label + ch * (remaining - left)
    else:
        text = ch * n
    print(paint(text, style))


def startup_bear() -> None:
    """Print the fixed-width UrsusFlasher startup mark once per process.

    The bear itself deliberately uses printable ASCII only.  Every face row is
    exactly 11 columns wide: no tabs, box-drawing characters or Unicode glyphs
    whose terminal width differs between Windows/Linux consoles.
    """
    global _STARTUP_BEAR_SHOWN
    if _STARTUP_BEAR_SHOWN:
        return
    _STARTUP_BEAR_SHOWN = True

    face = (
        r"[\]_____[/]",
        r"|         |",
        r"|  ^   ^  |",
        r"|    Y    |",
        r"|  \___/  |",
        r" '-------' ",
    )
    assert all(len(row) == 11 for row in face)

    print()
    for row in face:
        print(paint(row, 'amber'))
    print()
    print(paint('URSUSFLASHER', 'amber'))
    print(paint('BEAR METAL TOOL', 'sand'))
    print()


def banner(title: str, *, version: str = '', subtitle: str = '') -> None:
    print()
    rule(style='amber')
    line = title + (f'  {version}' if version else '')
    print(paint(line, 'amber'))
    if subtitle:
        print(paint(subtitle, 'dim'))
    rule(style='amber')


def section(title: str, *, style: str = 'amber') -> None:
    print()
    rule(title.upper(), style=style)


def menu_item(number: int | str, title: str, detail: str | None = None, *, tone: str = 'normal',
              write_capable: bool = False, enabled: bool = True, reason: str = '') -> None:
    num_style = 'amber'
    title_style = 'ink'
    if not enabled:
        num_style = title_style = 'muted'
    elif tone == 'danger':
        num_style = title_style = 'bad'
    elif tone == 'warning':
        num_style = title_style = 'sand'
    elif tone == 'safe':
        num_style = 'ok'
    marker = '!' if write_capable else ' '
    print(f" {paint(marker, 'sand' if write_capable else 'muted')} {paint(str(number).rjust(2), num_style)}  {paint(title, title_style)}")
    if detail:
        print(f"       {paint(detail, 'dim')}")
    if reason:
        print(f"       {paint(reason, 'dim')}")


def status(label: str, text: str, *, stream=None) -> None:
    stream = stream or sys.stdout
    style = {
        'ШАГ': 'amber', 'STEP': 'amber', 'BACKUP': 'amber',
        'ГОТОВО': 'ok', 'READY': 'ok', 'OK': 'ok', 'PASS': 'ok', 'DONE': 'ok',
        'ИНФО': 'ink', 'INFO': 'ink', 'ФАКТ': 'ink', 'FACT': 'ink',
        'ЖДУ': 'amber2', 'WAIT': 'amber2',
        'СДЕЛАЙТЕ': 'sand', 'ACTION': 'sand',
        'ВНИМАНИЕ': 'sand', 'WARNING': 'sand',
        'СТОП': 'bad', 'STOP': 'bad',
        'ОШИБКА': 'bad', 'ERROR': 'bad',
        'UART': 'sand', 'XMODEM': 'sand',
    }.get(label.upper(), 'ink')
    print(f"{paint('[' + label + ']', style)} {text}", file=stream)


def note(text: str) -> None:
    print(paint(text, 'dim'))


def info(text: str) -> None:
    print(paint(text, 'ink'))


def danger_block(title: str, lines: list[str]) -> None:
    print()
    rule(title, style='bad')
    for line in lines:
        print(paint(line, 'bad' if line.startswith('!') else 'ink'))
    rule(style='bad')


def prompt(text: str) -> str:
    return input(paint(text, 'sand'))


def package_version(root: Path) -> str:
    try:
        return (root / 'VERSION').read_text(encoding='utf-8').strip().split('-md-', 1)[0]
    except Exception:
        return 'dev'
