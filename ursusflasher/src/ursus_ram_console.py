#!/usr/bin/env python3
"""BootROM -> current UrsusBoot in RAM -> live console and transfers over LAN.

When the persistent UrsusBoot does not start, the UART is only needed to put a
working UrsusBoot into RAM.  After that everything -- the live console, F2/F3
file transfers and the F5 NAND presets -- runs over Ethernet at LAN speed
instead of 115200 baud.

Nothing here writes to NAND.  The RAM loader is chosen and shown like every
other FIP (version, size, SHA256); a custom file is allowed behind the usual
typed acceptance, because a wrong RAM loader costs only a power cycle.

Not proven on hardware for MD: the BootROM RAM path has so far carried only
the pinned alpha3 RAM installer.  Running the current persistent FIP the same
way is new; if it fails, power-cycle and nothing on the router has changed.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import console_ui as ui
import fip_choice as fc
import proven_backend as proven
import uart_bootarea_restore as ubr
import ui_terms as terms
import ursusboot_release

READY_MARKERS = (b'ursus_webfailsafe_ready', b'ursus_http_listen_ok')


def tr(ru: str, en: str) -> str:
    return terms.tr(ru, en)


def _loaders(family: str) -> tuple[Path, str, list]:
    """(preloader, its SHA256, RAM FIP options) for the family."""
    import ursusboot_update

    if family == 'md':
        profile = ubr.family_profile('md')
        preloader, pre_sha = Path(profile['preloader']), profile['preloader_sha']
        # The same FIP an ordinary update writes: the bundled release, or its historical default.
        current = ursusboot_update.PRODUCTION_PAYLOAD
        version = ursusboot_update.PRODUCTION_VERSION
    else:
        pre = ursusboot_release.path('mf', 'uart_preloader')
        current = ursusboot_release.path('mf', 'runtime_ram_fip')
        version = ursusboot_release.version('mf', '')
        if pre is not None and pre.is_file() and current is not None and current.is_file():
            preloader, pre_sha = pre, ursusboot_release.sha256('mf', 'uart_preloader')
        else:
            profile = ubr.family_profile('mf')
            preloader, pre_sha = Path(profile['preloader']), profile['preloader_sha']
            current, version = Path(profile['fip']), '0.1.0-TEST61'
    options = []
    if current is not None and current.is_file():
        options.append(fc.Option(
            'bundled', f'UrsusBoot {version} из комплекта (рекомендуется)',
            f'UrsusBoot {version} bundled with this kit (recommended)', path=current,
            note_ru='Только в RAM: NAND не пишется, после выключения питания ничего не остаётся.',
            note_en='RAM only: NAND is not written and nothing remains after a power-off.'))
    return preloader, pre_sha, options


def boot_to_lan(family: str | None = None, *, port: str | None = None,
                host: str | None = None, console: bool = True) -> None:
    import ursusboot_update

    family = family or ubr.choose_family()
    host = host or os.environ.get('NOKIA_ROUTER_IP', '192.168.1.1').strip() or '192.168.1.1'
    ui.rule(tr('BOOTROM → URSUSBOOT В RAM → КОНСОЛЬ ПО LAN', 'BOOTROM → URSUSBOOT IN RAM → CONSOLE OVER LAN'), style='amber2')
    ui.note(tr(
        'UART нужен только чтобы запустить UrsusBoot в оперативной памяти. Дальше консоль, файлы и NAND идут по Ethernet. '
        'NAND на этом шаге не пишется.',
        'The UART is only used to start UrsusBoot in RAM. After that the console, files and NAND go over Ethernet. '
        'Nothing is written to NAND by this step.'))
    preloader, pre_sha, options = _loaders(family)
    got = ubr.sha256(preloader)
    if got != str(pre_sha).lower():
        raise proven.Error(tr(f'UART preloader не совпадает с закреплённым: {got}',
                              f'UART preloader does not match its pin: {got}'))
    try:
        choice = fc.choose(options, known=ursusboot_update._known_fips(), rejected=ursusboot_update._rejected_fips(),
                           expect_nt_offset=fc.NT_FW_OFFSET_MD if family == 'md' else None,
                           context_ru='Загрузчик для RAM (во флеш не пишется):',
                           context_en='Loader for RAM (not written to flash):')
    except fc.Cancelled:
        ui.status(tr('СТОП', 'STOP'), tr('Отменено. Ничего не запускалось.', 'Cancelled. Nothing was started.'))
        return
    ui.status('RAM', f'{choice.info.title} · SHA256 {choice.info.sha256}')
    if choice.info.version and not _at_least(choice.info.version, 77):
        ui.status(tr('ВНИМАНИЕ', 'WARNING'), tr(
            'Живая консоль по сети и потоковый бэкап есть в UrsusBoot T77 и новее; этот загрузчик старше.',
            'The network live console and the streaming backup need UrsusBoot T77 or later; this loader is older.'))

    port = port or ursusboot_update.choose_port()
    proven.probe_serial_port(port)
    results = Path(__file__).resolve().parent.parent / 'results'
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / time.strftime(f'{family}-ram-console-%Y%m%d-%H%M%S.log')
    sp = proven.RecoverySerial(port)
    try:
        with log_path.open('ab', buffering=0) as log:
            ui.status(tr('СДЕЛАЙТЕ', 'ACTION'), tr(
                'Выключите роутер, зажмите Reset, включите питание и держите Reset до Press x / C.',
                'Power the router off, hold Reset, power it on and keep Reset held until Press x / C.'))
            proven.wait_bootrom_xmodem(sp, log, f'{family.upper()} preloader', discard_stale=False)
            proven.xmodem_send(sp, preloader, f'{family.upper()} UART preloader', log)
            proven.wait_bootrom_xmodem(sp, log, f'{family.upper()} RAM UrsusBoot FIP')
            proven.xmodem_send(sp, choice.path, f'{family.upper()} RAM {choice.info.title}', log)
            if proven.wait_uboot_prompt(sp, log) != 'prompt':
                raise proven.Error(tr(
                    'Приглашение U-Boot из RAM не перехвачено (началась обычная загрузка). NAND не изменялась.',
                    'The RAM U-Boot prompt was not captured (a normal boot started). NAND was not modified.'))
            start_webfailsafe(sp, log)
    finally:
        sp.close()
    ui.status(tr('ГОТОВО', 'READY'), tr(
        f'UrsusBoot работает из RAM; WebFailsafe на http://{host}/ . UART освобождён. Лог: {log_path}',
        f'UrsusBoot runs from RAM; WebFailsafe at http://{host}/ . The UART is free. Log: {log_path}'))
    if not console:
        return
    _wait_http(host)
    import ursus_web_client as uw
    uw.live_console(host)


def start_webfailsafe(sp, log, timeout: float = 90.0) -> None:
    """At a RAM U-Boot prompt: start `ursusweb` and wait until it listens on port 80."""
    proven._uboot_wait_quiet(sp, log, quiet=0.3, timeout=2.0)
    sp.reset_input()
    proven._uboot_send_line(sp, 'ursusweb')
    deadline = time.monotonic() + timeout
    tail = b''
    while time.monotonic() < deadline:
        data = sp.read(4096, 0.2)
        if not data:
            continue
        log.write(data)
        print(data.decode('utf-8', 'replace'), end='', flush=True)
        tail = (tail + data)[-8192:]
        low = tail.lower()
        if b"unknown command 'ursusweb'" in low:
            raise proven.Error(tr('Этот загрузчик не содержит ursusweb.', 'This loader has no ursusweb.'))
        if any(m in low for m in READY_MARKERS):
            print()
            return
    raise proven.Error(tr(
        'WebFailsafe не сообщил о готовности за 90 с. Проверьте кабель Ethernet (LAN2/LAN3).',
        'WebFailsafe did not report ready within 90 s. Check the Ethernet cable (LAN2/LAN3).'))


def _wait_http(host: str, timeout: float = 45.0) -> None:
    import ursus_web_client as uw

    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            uw.status(host)
            return
        except Exception as exc:
            last = exc
            time.sleep(1.0)
    raise proven.Error(tr(
        f'UrsusBoot в RAM не отвечает на http://{host}/ ({last}). ПК: статический IP в той же /24, кабель в LAN2/LAN3.',
        f'UrsusBoot in RAM does not answer at http://{host}/ ({last}). PC: static IP in the same /24, cable in LAN2/LAN3.'))


def _at_least(version: str, generation: int) -> bool:
    import re
    m = re.search(r'-t(\d+)$', version)
    return bool(m) and int(m.group(1)) >= generation
