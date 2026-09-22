#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path

import console_ui as ui
import one_key
import proven_backend as pb
import ursus_web_client as uw
import ursusboot_install as boot_install


def _wait_recovery(host: str, seconds: int = 90) -> dict | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return uw.status(host)
        except Exception:
            time.sleep(2)
    return None


def _manual_recovery(host: str) -> dict:
    ui.section(pb.tr("URSUSBOOT RECOVERY", "URSUSBOOT RECOVERY"), style="amber2")
    ui.status("ACTION", pb.tr(
        "После включения/перезагрузки зажмите Reset и держите до входа в UrsusBoot Recovery: 2 коротких + 3 длинных красных мигания, затем постоянный красный свет.",
        "After power-on/reboot hold Reset until UrsusBoot Recovery: 2 short + 3 long red flashes, then steady red.",
    ))
    ui.note(pb.tr(
        "Не зажимайте Reset до подачи питания: это может открыть Airoha BootROM вместо UrsusBoot Recovery.",
        "Do not hold Reset before applying power: that may enter Airoha BootROM instead of UrsusBoot Recovery.",
    ))
    while True:
        ui.prompt(pb.tr(
            "Нажмите Enter, когда красный индикатор горит постоянно: ",
            "Press Enter when the red status LED is steady: ",
        ))
        st = _wait_recovery(host, 25)
        if st is not None:
            return st
        again = ui.prompt(pb.tr(
            "Recovery пока не найден. Повторить проверку [Enter], 0 — остановиться без новых записей: ",
            "Recovery not found yet. Retry [Enter], 0 — stop without further writes: ",
        )).strip()
        if again == "0":
            raise RuntimeError(pb.tr(
                "Остановлено после проверенной записи UrsusBoot; повторная запись mtd0 не нужна.",
                "Stopped after the UrsusBoot write passed readback; do not rewrite mtd0.",
            ))


def _select_backup_policy() -> tuple[bool, Path | None]:
    candidates = []
    try:
        candidates = sorted(
            (
                p for p in boot_install.FULL_BACKUPS.iterdir()
                if p.is_dir() and (p / "BACKUP_COMPLETE").is_file()
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except FileNotFoundError:
        pass

    choice = ui.prompt(pb.tr(
        "Backup: Enter — снять новый полный mtd0..mtd16; e — использовать существующий проверенный backup: ",
        "Backup: Enter — create a new full mtd0..mtd16 backup; e — use an existing verified backup: ",
    )).strip().lower()
    if choice not in ("e", "existing", "с", "существующий"):
        return False, None

    default = candidates[0] if candidates else None
    prompt = (
        pb.tr(f"Путь к существующему backup [{default}]: ", f"Existing backup path [{default}]: ")
        if default is not None
        else pb.tr("Путь к существующему backup: ", "Existing backup path: ")
    )
    raw = ui.prompt(prompt).strip().strip('"')
    path = Path(raw) if raw else default
    if path is None:
        raise RuntimeError(pb.tr("Не указан существующий backup.", "No existing backup was selected."))
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(pb.tr(f"Каталог backup не найден: {path}", f"Backup directory not found: {path}"))

    validation = pb.verify_stock_restore_backup(path)
    family = str(validation.get("stock_restore", {}).get("device_family") or "").lower()
    if family != "md":
        raise RuntimeError(pb.tr(
            f"Выбранный backup относится к {family or 'unknown'}, нужен Nokia XG-040G-MD.",
            f"The selected backup belongs to {family or 'unknown'}; Nokia XG-040G-MD is required.",
        ))
    all_flash_sha = str(validation.get("stock_restore", {}).get("all_flash_sha256") or "")
    ui.status("PASS", pb.tr(
        f"Существующий stock backup прошёл restore-validator: {path} · all_flash {all_flash_sha}",
        f"Existing stock backup passed the restore validator: {path} · all_flash {all_flash_sha}",
    ))
    pb._write_session_only(f"[ITEM4_DIRECT_UBI] existing_full_backup={path} validator=PASS family=md all_flash_sha256={all_flash_sha}")
    return True, path


def run_expert(*, host: str, profile: str) -> int:
    if profile != "xg040-md":
        raise RuntimeError(
            "Direct UrsusBoot stock->UBI orchestration is currently enabled only for "
            "hardware-proven Nokia XG-040G-MD."
        )

    production = one_key.require_bundle_role("OPENWRT_UBI_SYSUPGRADE")
    preloader = one_key.require_bundle_role("STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")

    ui.section(pb.tr(
        "УСТАНОВИТЬ ЧИСТЫЙ OPENWRT С URSUSBOOT RECOVERY",
        "INSTALL CLEAN OPENWRT WITH URSUSBOOT RECOVERY",
    ), style="amber2")
    ui.status("READY", "Nokia XG-040G-MD / AN7581")
    ui.status("READY", f"OpenWrt: {production.name} · SHA256 {pb.sha_file(production)}")
    ui.status("READY", f"UBI transition preloader: {preloader.name} · SHA256 {pb.sha_file(preloader)}")
    ui.note(pb.tr(
        "Item 4 использует штатный UrsusBoot STOCK→UBI migration backend. Pregnant initramfs и bootm не используются. "
        "После установки OpenWrt UrsusBoot остаётся рабочим Recovery-загрузчиком. Переход на чистый Vanilla OpenWrt U-Boot выполняется отдельно.",
        "Item 4 uses the native UrsusBoot STOCK->UBI migration backend. No pregnant initramfs or bootm is used. "
        "After OpenWrt installation, UrsusBoot remains the working Recovery bootloader. Switching to the Vanilla OpenWrt U-Boot is a separate operation.",
    ))
    reuse_backup, _backup_path = _select_backup_policy()

    answer = ui.prompt(pb.tr(
        "Preflight payload пройден. Установить UrsusBoot, затем перевести Nokia STOCK в OpenWrt UBI? [y/N]: ",
        "Payload preflight passed. Install UrsusBoot, then migrate Nokia STOCK to OpenWrt UBI? [y/N]: ",
    )).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        ui.status("STOP", pb.tr("Операция отменена до записи.", "Operation cancelled before any write."))
        return 0

    rc = boot_install.run_install(
        unattended=True,
        host=host,
        recovery_after=True,
        recovery_host=host,
        route="stock",
        skip_full_backup=reuse_backup,
    )
    if rc:
        raise RuntimeError(f"UrsusBoot installation failed rc={rc}")

    st = _wait_recovery(host, 90)
    if st is None:
        st = _manual_recovery(host)
    version = str(st.get("version") or "")
    if str(st.get("current_layout") or "") != "STOCK":
        raise RuntimeError(f"expected STOCK layout in UrsusBoot Recovery, got {st.get('current_layout')!r}")
    ui.status("PASS", pb.tr(
        f"UrsusBoot Recovery найден: {version or 'version unknown'}.",
        f"UrsusBoot Recovery detected: {version or 'version unknown'}.",
    ))

    ui.status("ACTION", pb.tr(
        "Передаю production FIT и проверенный UBI transition preloader в существующие RAM upload-сессии.",
        "Uploading the production FIT and validated UBI transition preloader through the existing RAM upload sessions.",
    ))
    result = uw.update_firmware(
        host,
        production,
        confirm=False,
        preloader=preloader,
        keep_settings=False,
    )
    if not result.get("operation_complete"):
        raise RuntimeError(f"UrsusBoot migration did not reach COMPLETE: {result}")

    pb._write_session_only("[ITEM4_DIRECT_UBI] migration_complete=1 bootloader=URSUSBOOT retained=1")
    ui.status("PASS", pb.tr(
        "OpenWrt UBI записан и проверен. UrsusBoot Recovery сохранён.",
        "OpenWrt UBI was written and verified. UrsusBoot Recovery is retained.",
    ))
    ui.note(pb.tr(
        "Отдельная операция Vanilla заменит UrsusBoot только после дополнительной проверки Vanilla FIP/BL2. "
        "До неё текущий Recovery остаётся известным рабочим состоянием.",
        "A separate Vanilla operation will replace UrsusBoot only after additional Vanilla FIP/BL2 validation. "
        "Until then, the current Recovery remains the known-good state.",
    ))

    try:
        uw.reboot(host)
    except Exception:
        pass
    return 0
