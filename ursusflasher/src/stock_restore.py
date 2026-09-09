#!/usr/bin/env python3
from __future__ import annotations

import builtins
import os
import re
import shlex
import threading
from contextlib import contextmanager
from pathlib import Path

import board_profiles as bp
import console_ui as ui
import proven_backend as proven
import ui_terms as terms


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _family_from_state(state) -> str | None:
    match = bp.match_profile(
        model=str(getattr(state, "model", "") or ""),
        soc=str(getattr(state, "soc", "") or ""),
        board=str((getattr(state, "evidence", {}) or {}).get("openwrt_board") or ""),
    )
    return match[0] if match else None


def _require_family(value: str) -> str:
    family = str(value or "").strip().lower()
    if family not in ("md", "mf"):
        raise proven.Error(tr(
            "семья устройства MD/MF не определена; восстановление заблокировано",
            "the MD/MF device family is unknown; restore is blocked",
        ))
    return family


def _verify_exact(path: Path, size: int, digest: str, label: str) -> None:
    if not path.is_file():
        raise proven.Error(tr(f"отсутствует {label}: {path}", f"missing {label}: {path}"))
    actual_size = path.stat().st_size
    if actual_size != int(size):
        raise proven.Error(tr(
            f"неверный размер {label}: {actual_size} != {size}",
            f"wrong {label} size: {actual_size} != {size}",
        ))
    actual_sha = proven.sha_file(path).lower()
    if actual_sha != str(digest).lower():
        raise proven.Error(tr(
            f"SHA256 {label} не совпадает: {actual_sha} != {digest}",
            f"{label} SHA256 mismatch: {actual_sha} != {digest}",
        ))


def _verify_stock_restore_runtime() -> None:
    """Verify the narrow payload set actually used by EXPERT item 6.

    Do not call the inherited MedveFlasher ``verify_kit()`` here: that verifier
    also requires its installer bundles and Medve release identity, neither of
    which is part of the UrsusFlasher stock-restore contract.
    """
    _verify_exact(
        proven.RECOVERY_PRELOADER,
        proven.BACKUP_RECOVERY_PRELOADER_SIZE,
        proven.RECOVERY_PRELOADER_SHA,
        "MD BootROM recovery preloader",
    )
    _verify_exact(proven.RECOVERY_FIP, proven.RECOVERY_FIP_SIZE, proven.RECOVERY_FIP_SHA, "MD RECOVERY_SAFE FIP")
    _verify_exact(
        proven.RECOVERY_INITRAMFS,
        proven.RECOVERY_INITRAMFS_SIZE,
        proven.RECOVERY_INITRAMFS_SHA,
        "MD stock recovery initramfs",
    )
    _verify_exact(
        proven.RECOVERY_TFTP_CLIENT, 7792, proven.RECOVERY_TFTP_CLIENT_SHA,
        "AArch64 nokia-tftp",
    )
    _verify_exact(
        proven.RECOVERY_SCP_CLIENT, 6072, proven.RECOVERY_SCP_CLIENT_SHA,
        "AArch64 nokia-scp",
    )
    proven._load_mf_snapshot_metadata()
    _verify_exact(
        proven.MF_RECOVERY_PRELOADER, proven.MF_RECOVERY_PRELOADER_SIZE,
        proven.MF_RECOVERY_PRELOADER_SHA, "MF BootROM recovery preloader",
    )
    _verify_exact(
        proven.MF_RECOVERY_FIP, proven.MF_RECOVERY_FIP_SIZE,
        proven.MF_RECOVERY_FIP_SHA, "MF RECOVERY_SAFE FIP",
    )
    _verify_exact(
        proven.MF_STOCK_RECOVERY_INITRAMFS, proven.MF_STOCK_RECOVERY_INITRAMFS_SIZE,
        proven.MF_STOCK_RECOVERY_INITRAMFS_SHA, "MF stock recovery initramfs",
    )
    proven._write_session_only("[RESTORE] narrow runtime payload verification PASS md=1 mf=1")


def _recovery_initramfs(family: str) -> tuple[Path, str]:
    family = _require_family(family)
    profile = proven.recovery_profile_for_family(family)
    image = Path(profile["initramfs"])
    expected_sha = str(profile.get("initramfs_sha") or "").lower()
    if not image.is_file():
        raise proven.Error(tr(
            f"отсутствует recovery-initramfs для {family.upper()}: {image}",
            f"the {family.upper()} recovery initramfs is missing: {image}",
        ))
    actual_sha = proven.sha_file(image).lower()
    if not expected_sha or actual_sha != expected_sha:
        raise proven.Error(tr(
            f"SHA256 recovery-initramfs {family.upper()} не совпадает: {actual_sha} != {expected_sha or 'UNKNOWN'}",
            f"{family.upper()} recovery-initramfs SHA256 mismatch: {actual_sha} != {expected_sha or 'UNKNOWN'}",
        ))
    return image, actual_sha


@contextmanager
def _legacy_restore_confirmation_adapter(*, already_confirmed: bool = False):
    """Translate the retained Medve backend codeword into UrsusFlasher's one y/N."""
    original = getattr(proven, "input", builtins.input)
    had_override = "input" in proven.__dict__
    seen = False

    def adapted(prompt: str = "") -> str:
        nonlocal seen
        if "RESTORE STOCK BACKUP" not in str(prompt):
            return original(prompt)
        if seen:
            raise proven.Error(tr(
                "внутренняя ошибка: backend запросил повторное destructive-подтверждение",
                "internal error: the backend requested a second destructive confirmation",
            ))
        seen = True
        if already_confirmed:
            proven._write_session_only("[RESTORE-CONFIRM] legacy backend token satisfied by prior UrsusFlasher y/N")
            return "RESTORE STOCK BACKUP"
        answer = ui.prompt(tr(
            "Начать восстановление stock из проверенной резервной копии? [y/N]: ",
            "Start restoring stock from the validated backup? [y/N]: ",
        )).strip().lower()
        if answer in ("y", "yes", "д", "да"):
            proven._write_session_only("[RESTORE-CONFIRM] operator accepted one UrsusFlasher y/N")
            return "RESTORE STOCK BACKUP"
        proven._write_session_only("[RESTORE-CONFIRM] operator declined UrsusFlasher y/N")
        return ""

    proven.input = adapted
    try:
        yield
    finally:
        if had_override:
            proven.input = original
        else:
            proven.__dict__.pop("input", None)


def _one_yn_before_recovery_handoff(*, family: str, backup_sha: str, image: Path, image_sha: str) -> bool:
    ui.rule(tr("ПРЕДЗАПИСНАЯ СВОДКА", "PRE-WRITE SUMMARY"), style="amber2")
    print("  " + tr("Действие: восстановить заводскую прошивку Nokia", "Action: restore Nokia stock firmware"))
    print("  " + tr(f"Плата: {family.upper()}", f"Board family: {family.upper()}"))
    print("  " + tr(f"Backup all_flash SHA256: {backup_sha}", f"Backup all_flash SHA256: {backup_sha}"))
    print("  " + tr(
        f"Переход: U-Boot → {image.name} только в RAM; затем IBU → readback → BL2 ПОСЛЕДНИМ",
        f"Handoff: U-Boot → {image.name} in RAM only; then IBU → readback → BL2 LAST",
    ))
    print("  " + tr(f"Recovery image SHA256: {image_sha}", f"Recovery image SHA256: {image_sha}"))
    ui.note(tr(
        "Одно подтверждение разрешает всю эту операцию. Любая смена family/layout/backup в последующих автоматических preflight остановит запись.",
        "This single confirmation authorizes this exact operation. Any later family/layout/backup mismatch stops writing during automatic preflight.",
    ))
    answer = ui.prompt(tr("Начать? [y/N]: ", "Start? [y/N]: ")).strip().lower()
    return answer in ("y", "yes", "д", "да")


def _arm_one_shot_recovery_boot_once(host: str, expected_bootcmd: str, local_ip: str, router_ip: str, bootfile: str) -> None:
    """Perform exactly one persistent bootcmd write and verify it.

    A transport/status failure after ``fw_setenv`` is WRITE_STATE_UNKNOWN and
    must never trigger another automatic writer. U-Boot restores the ordinary
    bootcmd before attempting TFTP, so network retries do not rewrite flash.
    """
    retry_numbers = " ".join(str(i) for i in range(1, 21))
    temporary = (
        f"setenv bootcmd '{expected_bootcmd}'; saveenv; "
        "setenv ethaddr 02:00:00:04:0d:10; setenv eth1addr 02:00:00:04:0d:11; "
        f"setenv ipaddr {router_ip}; setenv serverip {local_ip}; setenv netmask 255.255.255.0; "
        "setenv autoload no; "
        f"for n in {retry_numbers}; do echo NOKIA_RECOVERY_TFTP_ATTEMPT_$n; "
        f"tftpboot 0x90000000 {bootfile} && bootm 0x90000000#config-1; sleep 2; done; "
        "run boot_ubi"
    )
    command = (
        f"fw_setenv bootcmd {shlex.quote(temporary)} && sync && "
        "printf 'ARMED_BOOTCMD='; fw_printenv -n bootcmd"
    )
    rc, output = proven.ssh_run(host, command, timeout=120, allow_disconnect=True, quiet=True)
    values = proven.parse_shell_assignments(output, ("ARMED_BOOTCMD",))
    if rc == 0 and values.get("ARMED_BOOTCMD") == temporary:
        proven._write_session_only("[RESTORE] one-shot bootcmd persistent write COMPLETION_PROVEN")
        return
    proven._write_session_only(
        f"[RESTORE] one-shot bootcmd WRITE_STATE_UNKNOWN rc={rc} verified={values.get('ARMED_BOOTCMD') == temporary}"
    )
    raise proven.Error(tr(
        "не удалось доказать запись одноразового bootcmd; состояние записи неизвестно. Автоматический повтор запрещён",
        "the one-shot bootcmd write could not be proven; write state is unknown. Automatic retry is forbidden",
    ))


def _boot_family_recovery_once(host: str, local_ip: str, router_ip: str, family: str, image: Path) -> None:
    """One verified production-OpenWrt -> U-Boot -> RAM recovery handoff."""
    family = _require_family(family)
    if proven.wait_for_stable_openwrt(host, 120, expected_mode="production") != "production":
        raise proven.Error(tr(
            "установленная OpenWrt не стала устойчиво доступна; recovery handoff не выполнялся",
            "installed OpenWrt did not become stably available; recovery handoff was not attempted",
        ))

    env_cmd = (
        "echo BOOTCMD=$(fw_printenv -n bootcmd 2>/dev/null || true); "
        "echo BOARD=$(cat /tmp/sysinfo/board_name 2>/dev/null || true)"
    )
    _, env_out = proven.ssh_run(host, env_cmd, timeout=60, quiet=True)
    values = proven.parse_shell_assignments(env_out, ("BOOTCMD", "BOARD"))
    expected_board = f"nokia,xg-040g-{family}-ubi"
    board = str(values.get("BOARD") or "")
    normal_bootcmd = str(values.get("BOOTCMD") or "")
    expected_normal_bootcmd = "run check_buttons ; run boot_ubi"
    if board != expected_board:
        raise proven.Error(tr(
            f"production board изменился перед recovery handoff: {board or 'UNKNOWN'} != {expected_board}",
            f"production board changed before recovery handoff: {board or 'UNKNOWN'} != {expected_board}",
        ))
    if normal_bootcmd != expected_normal_bootcmd:
        raise proven.Error(tr(
            f"bootcmd изменился перед recovery handoff: {normal_bootcmd or '[пусто]'}",
            f"bootcmd changed before recovery handoff: {normal_bootcmd or '[empty]'}",
        ))

    bootfile = f"ursus-stock-recovery-{family}.itb"
    ready = threading.Event()
    result = proven.TftpResult()
    thread = threading.Thread(
        target=proven.serve_tftp_get,
        args=(local_ip, 69, image, bootfile, router_ip, ready, result),
        kwargs={"timeout": 360, "maximum_block_size": 1468}, daemon=True,
    )
    thread.start()
    if not ready.wait(10):
        raise proven.Error(tr("TFTP/69 для recovery-initramfs не запустился", "recovery-initramfs TFTP/69 did not start"))
    if result.error:
        raise proven.Error(f"TFTP/69: {result.error}")

    proven._write_session_only(
        f"[RESTORE] one-shot family={family} recovery={image.name} bootfile={bootfile} server={local_ip} router={router_ip}"
    )
    _arm_one_shot_recovery_boot_once(host, expected_normal_bootcmd, local_ip, router_ip, bootfile)
    try:
        proven.ssh_run(host, "sync; reboot -f", timeout=30, allow_disconnect=True, quiet=True)
    except proven.Error:
        pass

    while thread.is_alive() and not result.error:
        thread.join(0.5)
    if result.error:
        raise proven.Error(tr(
            f"recovery-initramfs TFTP завершился ошибкой после one-shot bootcmd: {result.error}. Автоматический повтор запрещён.",
            f"recovery-initramfs TFTP failed after the one-shot bootcmd: {result.error}. Automatic retry is forbidden.",
        ))
    if result.bytes_transferred != image.stat().st_size:
        raise proven.Error(tr(
            f"recovery-initramfs передан не полностью: {result.bytes_transferred}/{image.stat().st_size}. Автоматический повтор запрещён.",
            f"recovery-initramfs transfer was incomplete: {result.bytes_transferred}/{image.stat().st_size}. Automatic retry is forbidden.",
        ))
    if proven.wait_for_stable_openwrt(router_ip, 480, expected_mode="recovery") != "recovery":
        mode = proven.wait_for_stable_openwrt(router_ip, 90, expected_mode="production")
        detail = tr(
            "обычная OpenWrt вернулась; запустите пункт восстановления ещё раз после проверки сети" if mode == "production" else
            "не подтверждена ни recovery, ни production OpenWrt; используйте UART/BootROM",
            "installed OpenWrt returned; run restore again after checking the network" if mode == "production" else
            "neither recovery nor production OpenWrt was proven; use UART/BootROM",
        )
        raise proven.Error(tr(
            "RAM recovery не подтверждена после one-shot handoff; второй bootcmd writer автоматически не запускается. " + detail,
            "RAM recovery was not proven after the one-shot handoff; a second bootcmd writer is not started automatically. " + detail,
        ))
    print(tr(
        f"[OK] {family.upper()} recovery-initramfs запущена из RAM; image во flash не записывался.",
        f"[OK] {family.upper()} recovery initramfs is running from RAM; the image was not written to flash.",
    ))


def restore_from_running(state) -> None:
    """Restore stock without UART from verified production OpenWrt/recovery."""
    _verify_stock_restore_runtime()
    state_family = _require_family(_family_from_state(state) or "")
    host = str(getattr(state, "host", "") or "192.168.1.1")
    proven.transition_lan_policy_notice()

    local_ip = ui.prompt(tr("Статический IP компьютера [192.168.1.254]: ", "Static PC IP [192.168.1.254]: ")).strip() or "192.168.1.254"
    port_text = ui.prompt(tr("Порт передачи restore [1069]: ", "Restore transfer port [1069]: ")).strip()
    restore_port = int(port_text) if port_text else 1069
    raw = ui.prompt(tr("Путь к полному stock backup: ", "Path to the complete stock backup: ")).strip().strip('"')
    backup_dir = Path(raw).expanduser()
    if not raw:
        raise proven.Error(tr("backup не выбран", "no backup was selected"))

    payload_dir, manifest = proven.prepare_stock_restore_payloads(backup_dir)
    backup_family = _require_family(str(manifest.get("source_validation", {}).get("device_family") or ""))
    if backup_family != state_family:
        raise proven.Error(tr(
            f"backup относится к {backup_family.upper()}, а устройство подтверждено как {state_family.upper()}; запись запрещена",
            f"the backup belongs to {backup_family.upper()}, while the device is proven as {state_family.upper()}; writing is blocked",
        ))
    backup_sha = str(manifest.get("all_flash_sha256") or "")
    mode, _ = proven.inspect_restore_environment(host, expected_family=state_family, quiet=True)

    if mode == "production":
        image, image_sha = _recovery_initramfs(state_family)
        if not _one_yn_before_recovery_handoff(family=state_family, backup_sha=backup_sha, image=image, image_sha=image_sha):
            ui.status(tr("СТОП", "STOP"), tr("Восстановление отменено; persistent write не начинался.", "Restore cancelled; no persistent write was started."))
            return
        try:
            _boot_family_recovery_once(host, local_ip, host, state_family, image)
        except PermissionError as exc:
            raise proven.Error(tr("нет прав на UDP/69; в Linux запустите UrsusFlasher через sudo", "permission denied for UDP/69; on Linux run UrsusFlasher with sudo")) from exc
        with _legacy_restore_confirmation_adapter(already_confirmed=True):
            proven.perform_stock_restore_over_ssh(host, local_ip, restore_port, backup_dir, payload_dir, manifest)
        return

    if mode == "recovery":
        with _legacy_restore_confirmation_adapter(already_confirmed=False):
            proven.perform_stock_restore_over_ssh(host, local_ip, restore_port, backup_dir, payload_dir, manifest)
        return

    raise proven.Error(tr("неподдерживаемая среда восстановления", "unsupported restore environment"))


def restore_over_uart() -> None:
    """BootROM/XMODEM restore using the family-aware proven backend."""
    _verify_stock_restore_runtime()
    original_verify = proven.verify_kit
    proven.verify_kit = _verify_stock_restore_runtime
    try:
        with _legacy_restore_confirmation_adapter(already_confirmed=False):
            proven.stock_recovery_wizard()
    finally:
        proven.verify_kit = original_verify


def restore_nokia(state) -> None:
    """Resolve the safest stock-restore route from current DeviceState."""
    system = str(getattr(state, "current_system", "") or "UNKNOWN")
    probe = str(getattr(state, "probe_status", "") or "")
    family = _family_from_state(state)

    if family and probe == "COMPLETE" and (system.startswith("OPENWRT") or system == "RECOVERY"):
        ui.status(tr("МЕТОД", "METHOD"), tr(
            "UART не требуется: проверенная OpenWrt/recovery → U-Boot one-shot → board-specific initramfs в RAM → restore",
            "UART is not required: verified OpenWrt/recovery → U-Boot one-shot → board-specific RAM initramfs → restore",
        ))
        restore_from_running(state)
        return

    ui.status(tr("МЕТОД", "METHOD"), tr(
        "Сетевая среда для безопасного no-UART restore не доказана; используется BootROM/XMODEM через USB-UART.",
        "A safe network environment for no-UART restore was not proven; using BootROM/XMODEM over USB-UART.",
    ))
    restore_over_uart()
