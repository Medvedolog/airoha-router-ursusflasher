#!/usr/bin/env python3
"""Identify a UrsusBoot FIP and let the operator choose which one gets written.

Every UrsusBoot install/update/restore path used to write one fixed file without
saying which version that was.  This module gives those paths two things:

* ``identify()``: read a FIP without trusting its name -- size, SHA256, whether
  it is structurally a bootable Airoha FIP, and the UrsusBoot version string
  inside its compressed BL33 (the FIP has no version field of its own).
* ``choose()``: show what each candidate is *before* anything is written, and
  offer "my own FIP file" behind an explicit, typed risk acceptance.

Nothing here writes to a router.  ``identify()`` is a host-side plausibility
check, not a compatibility proof: a valid FIP can still be the wrong one for the
BL2 already on the board.  The device-side ``ursusupdate write`` and the
byte-for-byte readback remain the gates that actually protect the flash.
"""
from __future__ import annotations

import hashlib
import lzma
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import ui_terms as terms

FIP_MAGIC = 0xAA640001
FIP_SERIAL = 0x12345678
NT_FW_UUID = bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
NT_FW_OFFSET_MD = 0x27800
LZMA_PROPS = 0x9B            # lc=2 lp=2 pb=3, what the SoC's BL31 decompressor expects
LZMA_DICT = 0x100000
STOCK_FIP_OFF = 0x800
STOCK_ENV_OFF = 0x7C000
STOCK_FIP_WINDOW = STOCK_ENV_OFF - STOCK_FIP_OFF
MIN_FIP_SIZE = 0x10000
MAX_BL33_RAW = 8 << 20
CUSTOM_TOKEN = 'CUSTOM FIP'

_VERSION_RE = re.compile(rb'UrsusBoot (\d+\.\d+\.\d+[-\w.]*)')


class Cancelled(Exception):
    """The operator backed out before anything was written."""


def _t(ru: str, en: str) -> str:
    return terms.tr(ru, en)


@dataclass
class FipInfo:
    size: int = 0
    sha256: str = ''
    crc32: str = ''
    version: str | None = None       # UrsusBoot version found inside BL33, if decodable
    label: str | None = None         # name from the known-hash table, if listed
    bl33_sha256: str | None = None
    bl33_size: int | None = None
    nt_offset: int | None = None
    problems: list[str] = field(default_factory=list)   # any of these blocks a write
    rejected: bool = False           # on the project's known-bad list

    @property
    def ok(self) -> bool:
        return not self.problems and not self.rejected

    @property
    def title(self) -> str:
        if self.version:
            return f'UrsusBoot {self.version}'
        return _t('версия не определена', 'version not identified')


def identify(data: bytes, *, known: dict[str, str] | None = None, rejected=(),
             expect_nt_offset: int | None = NT_FW_OFFSET_MD,
             window: int = STOCK_FIP_WINDOW, exact_end: bool = True) -> FipInfo:
    """Describe ``data`` as a FIP.  ``known`` maps sha256 (or crc32) -> label.

    ``exact_end=False`` accepts trailing bytes after the FIP's declared end
    (a slice out of a boot-area image); ``size`` is then the declared end.
    ``expect_nt_offset=None`` skips the NT_FW placement check (MF layouts).
    """
    info = FipInfo()
    p = info.problems
    table = {k.lower(): v for k, v in (known or {}).items()}
    bad = {str(x).lower() for x in rejected}

    def stamp(blob: bytes) -> None:
        info.size = len(blob)
        info.sha256 = hashlib.sha256(blob).hexdigest()
        info.crc32 = f'{zlib.crc32(blob) & 0xFFFFFFFF:08x}'
        info.label = table.get(info.sha256) or table.get(info.crc32)
        info.rejected = info.sha256 in bad

    stamp(data)

    if len(data) < MIN_FIP_SIZE:
        p.append(_t(f'файл слишком мал для FIP: 0x{len(data):x} байт',
                    f'file is too small to be a FIP: 0x{len(data):x} bytes'))
        return info
    if struct.unpack_from('<I', data, 0)[0] != FIP_MAGIC:
        p.append(_t('нет сигнатуры Airoha FIP (0xAA640001)', 'no Airoha FIP signature (0xAA640001)'))
        return info
    if struct.unpack_from('<I', data, 4)[0] != FIP_SERIAL:
        p.append(_t('неверный serial в заголовке FIP', 'wrong serial in the FIP header'))
        return info

    nt = None
    declared_end = None
    pos = 16
    for _ in range(32):
        if pos + 40 > len(data):
            p.append(_t('таблица FIP оборвана', 'FIP table of contents is truncated'))
            return info
        uuid = data[pos:pos + 16]
        off, size, _flags = struct.unpack_from('<QQQ', data, pos + 16)
        if uuid == b'\0' * 16:
            declared_end = off
            break
        if off < 0x400 or not size or off + size > len(data):
            p.append(_t(f'запись FIP выходит за файл: off=0x{off:x} size=0x{size:x}',
                        f'FIP entry lies outside the file: off=0x{off:x} size=0x{size:x}'))
            return info
        if uuid == NT_FW_UUID:
            if nt is not None:
                p.append(_t('в FIP больше одного NT_FW', 'the FIP has more than one NT_FW'))
                return info
            nt = (off, size)
        pos += 40
    if declared_end is None:
        p.append(_t('в таблице FIP нет завершающей записи', 'the FIP table has no terminator'))
        return info
    if exact_end and declared_end != len(data):
        p.append(_t(f'заявленный конец FIP 0x{declared_end:x} != размер файла 0x{len(data):x}',
                    f'declared FIP end 0x{declared_end:x} != file size 0x{len(data):x}'))
    if declared_end > len(data):
        p.append(_t('FIP заявляет больше данных, чем есть в файле', 'the FIP declares more data than the file holds'))
        return info
    if not exact_end:
        data = data[:declared_end]      # trailing bytes belong to whatever follows the FIP
        stamp(data)
    if info.size > window:
        p.append(_t(f'FIP не помещается в окно 0x{window:x}: 0x{info.size:x}',
                    f'the FIP does not fit the 0x{window:x} window: 0x{info.size:x}'))
    if nt is None:
        p.append(_t('в FIP нет NT_FW/BL33', 'the FIP has no NT_FW/BL33'))
        return info
    info.nt_offset = nt[0]
    if expect_nt_offset is not None and nt[0] != expect_nt_offset:
        p.append(_t(f'NT_FW по смещению 0x{nt[0]:x}, ожидалось 0x{expect_nt_offset:x}',
                    f'NT_FW at offset 0x{nt[0]:x}, expected 0x{expect_nt_offset:x}'))

    blob = data[nt[0]:nt[0] + nt[1]]
    if len(blob) < 14:
        p.append(_t('NT_FW слишком короткий', 'NT_FW is too short'))
        return info
    props = blob[0]
    dictionary = struct.unpack_from('<I', blob, 1)[0]
    usize = struct.unpack_from('<Q', blob, 5)[0]
    if props != LZMA_PROPS:
        p.append(_t(f'параметры LZMA 0x{props:02x}, нужны 0x9b', f'LZMA properties 0x{props:02x}, 0x9b required'))
        return info
    if dictionary != LZMA_DICT:
        p.append(_t(f'словарь LZMA 0x{dictionary:x}, нужен 0x100000', f'LZMA dictionary 0x{dictionary:x}, 0x100000 required'))
        return info
    if not 0 < usize <= MAX_BL33_RAW:
        p.append(_t(f'размер распакованного BL33 неправдоподобен: {usize}', f'implausible decompressed BL33 size: {usize}'))
        return info
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
            {'id': lzma.FILTER_LZMA1, 'dict_size': dictionary, 'lc': 2, 'lp': 2, 'pb': 3}])
        raw = dec.decompress(blob[13:], max_length=usize + 1)
    except lzma.LZMAError as exc:
        p.append(_t(f'BL33 не распаковывается: {exc}', f'BL33 does not decompress: {exc}'))
        return info
    if len(raw) != usize:
        p.append(_t(f'BL33 распаковался в {len(raw)} байт, заявлено {usize}',
                    f'BL33 decompressed to {len(raw)} bytes, {usize} declared'))
        return info
    info.bl33_size = usize
    info.bl33_sha256 = hashlib.sha256(raw).hexdigest()
    m = _VERSION_RE.search(raw)
    if m:
        info.version = m.group(1).decode('ascii', 'replace')
    return info


def identify_file(path: Path, **kw) -> FipInfo:
    return identify(Path(path).read_bytes(), **kw)


def describe(info: FipInfo, path: Path | None = None, *, indent: str = '    ') -> list[str]:
    """Lines telling the operator exactly what this candidate is."""
    lines = []
    head = info.title
    if info.label:
        head += f' — {info.label}'
    lines.append(head)
    if path is not None:
        lines.append(f'{indent}{_t("файл", "file")}: {path}')
    lines.append(f'{indent}{_t("размер", "size")}: {info.size} {_t("байт", "bytes")} (0x{info.size:x})')
    lines.append(f'{indent}SHA256: {info.sha256}')
    if info.bl33_sha256:
        lines.append(f'{indent}BL33 SHA256: {info.bl33_sha256} ({info.bl33_size} {_t("байт", "bytes")})')
    if not info.label and info.ok:
        lines.append(indent + _t('нет в списке известных сборок проекта', 'not in the project\'s list of known builds'))
    if info.rejected:
        lines.append(indent + _t('В ЧЁРНОМ СПИСКЕ: эта сборка известна как непригодная', 'ON THE REJECT LIST: this build is known to be unusable'))
    for reason in info.problems:
        lines.append(f'{indent}{_t("ПРОБЛЕМА", "PROBLEM")}: {reason}')
    return lines


@dataclass
class Option:
    kind: str                                   # 'bundled' | 'pinned' | 'derived' (menu entries other than custom)
    label_ru: str
    label_en: str
    path: Path | None = None
    factory: Callable[[], Path] | None = None   # builds the file when chosen (device-derived candidates)
    note_ru: str = ''
    note_en: str = ''
    advisory: bool = False                      # built by the project itself: problems are shown, the device still gates


@dataclass
class Choice:
    kind: str            # the Option kind, or 'custom'
    path: Path
    info: FipInfo

    @property
    def custom(self) -> bool:
        return self.kind == 'custom'


def _say(out, text: str = '') -> None:
    out(text)


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ('y', 'yes', 'д', 'да')


def choose(options: list[Option], *, known: dict[str, str] | None = None, rejected=(),
           expect_nt_offset: int | None = NT_FW_OFFSET_MD, allow_custom: bool = True,
           context_ru: str = '', context_en: str = '',
           ask: Callable[[str], str] | None = None, out: Callable[[str], None] = print) -> Choice:
    """Show what would be written, let the operator pick, return the choice.

    Enter takes the first option.  Raises ``Cancelled`` if the operator backs out.
    A blocking problem in a *listed* option (bundled/pinned) is shown and the
    option stays selectable only for inspection -- it is refused on selection.
    """
    ask = ask or input
    kw = dict(known=known, rejected=rejected, expect_nt_offset=expect_nt_offset)
    shown: list[tuple[Option, FipInfo | None]] = []
    for opt in options:
        info = None
        if opt.path is not None:
            try:
                info = identify_file(opt.path, **kw)
            except OSError as exc:
                info = FipInfo(problems=[str(exc)])
        shown.append((opt, info))

    while True:
        _say(out)
        _say(out, _t('Какой UrsusBoot будет записан:', 'Which UrsusBoot will be written:'))
        if context_ru or context_en:
            _say(out, '  ' + _t(context_ru, context_en))
        for i, (opt, info) in enumerate(shown, 1):
            _say(out, f'  {i}. {_t(opt.label_ru, opt.label_en)}')
            if info is not None:
                for k, line in enumerate(describe(info, opt.path, indent='       ')):
                    _say(out, ('     ' if k == 0 else '') + line)
            if opt.note_ru or opt.note_en:
                _say(out, '       ' + _t(opt.note_ru, opt.note_en))
        custom_no = len(shown) + 1
        if allow_custom:
            _say(out, f'  {custom_no}. {_t("Свой FIP-файл (на свой страх и риск)", "My own FIP file (at your own risk)")}')
        raw = ask(_t(f'Выбор [1]: ', f'Choice [1]: ')).strip().lower()
        if raw in ('q', 'quit', 'cancel', 'отмена', 'в'):
            raise Cancelled()
        if raw == '':
            raw = '1'
        if not raw.isdigit() or not 1 <= int(raw) <= custom_no - (0 if allow_custom else 1):
            _say(out, _t('Введите номер из списка.', 'Enter a number from the list.'))
            continue
        n = int(raw)
        if n < custom_no:
            opt, info = shown[n - 1]
            path = opt.path
            if opt.factory is not None and path is None:
                path = opt.factory()
                info = identify_file(path, **kw)
                for line in describe(info, path, indent='    '):
                    _say(out, line)
            assert info is not None and path is not None
            if info.rejected or (info.problems and not opt.advisory):
                _say(out, _t('Этот файл не прошёл проверку и не будет записан.',
                             'This file failed validation and will not be written.'))
                continue
            return Choice(opt.kind, path, info)

        choice = _choose_custom(kw, ask, out)
        if choice is not None:
            return choice


def _choose_custom(kw: dict, ask, out) -> Choice | None:
    _say(out)
    _say(out, _t('СВОЙ FIP — НА ВАШ СТРАХ И РИСК', 'YOUR OWN FIP — AT YOUR OWN RISK'))
    for ru, en in (
        ('UrsusFlasher проверяет только форму FIP и версию внутри. Он НЕ может проверить, что FIP работает с BL2 на вашей плате.',
         'UrsusFlasher checks only the shape of the FIP and the version inside it. It CANNOT check that the FIP works with the BL2 on your board.'),
        ('Несовместимый FIP может оставить роутер без загрузки; тогда нужен UART и BootROM-восстановление.',
         'An incompatible FIP can leave the router unable to boot; recovery then needs UART and BootROM.'),
    ):
        _say(out, '  ' + _t(ru, en))
    raw = ask(_t('Путь к FIP-файлу (пусто — назад): ', 'Path to the FIP file (empty = back): ')).strip().strip('"')
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        _say(out, _t(f'Файл не найден: {path}', f'File not found: {path}'))
        return None
    if not path.is_file():
        _say(out, _t(f'Это не файл: {path}', f'Not a file: {path}'))
        return None
    info = identify_file(path, **kw)
    for line in describe(info, path):
        _say(out, line)
    if not info.ok:
        _say(out, _t('Файл не прошёл проверку и не будет записан.', 'The file failed validation and will not be written.'))
        return None
    answer = ask(_t(f'Чтобы принять риск, наберите латиницей {CUSTOM_TOKEN}: ',
                    f'To accept the risk, type {CUSTOM_TOKEN}: ')).strip()
    if answer != CUSTOM_TOKEN:
        _say(out, _t('Риск не принят; файл не выбран.', 'Risk not accepted; file not selected.'))
        return None
    return Choice('custom', path, info)


def summary_lines(choice: Choice, *, installed: str | None = None) -> list[str]:
    """The one block every write path prints right before its own confirmation."""
    lines = [_t('БУДЕТ ЗАПИСАНО', 'WILL BE WRITTEN') + ': ' + choice.info.title
             + (' [' + _t('СВОЙ ФАЙЛ', 'CUSTOM FILE') + ']' if choice.custom else '')]
    if installed:
        lines.append(_t('Сейчас установлено', 'Currently installed') + f': {installed}')
    lines.append(f'  {_t("файл", "file")}: {choice.path.name}')
    lines.append(f'  SHA256: {choice.info.sha256}')
    lines.append(f'  {_t("размер", "size")}: {choice.info.size} {_t("байт", "bytes")}')
    return lines
