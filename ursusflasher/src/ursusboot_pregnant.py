#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path

import console_ui as ui
import one_key
import proven_backend as pb
import ursus_web_client as uw
import ursusboot_install as boot_install
import ursusboot_release


MODEL = {"md": "Nokia XG-040G-MD", "mf": "Nokia XG-040G-MF"}
SUPPORTED_PROFILES = {"xg040-md": "md", "xg040-mf": "mf"}


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


def _select_backup_policy(family: str = "md") -> tuple[bool, Path | None]:
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
    found = str(validation.get("stock_restore", {}).get("device_family") or "").lower()
    model = MODEL[family]
    if found != family:
        raise RuntimeError(pb.tr(
            f"Выбранный backup относится к {found or 'unknown'}, нужен {model}.",
            f"The selected backup belongs to {found or 'unknown'}; {model} is required.",
        ))
    all_flash_sha = str(validation.get("stock_restore", {}).get("all_flash_sha256") or "")
    ui.status("PASS", pb.tr(
        f"Существующий stock backup прошёл restore-validator: {path} · all_flash {all_flash_sha}",
        f"Existing stock backup passed the restore validator: {path} · all_flash {all_flash_sha}",
    ))
    pb._write_session_only(f"[ITEM4_DIRECT_UBI] existing_full_backup={path} validator=PASS family={family} all_flash_sha256={all_flash_sha}")
    return True, path


def run_expert(*, host: str, profile: str) -> int:
    family = SUPPORTED_PROFILES.get(profile)
    if family is None:
        raise RuntimeError(
            "Direct UrsusBoot stock->UBI orchestration is enabled only for "
            "Nokia XG-040G-MD and XG-040G-MF."
        )
    if family == "mf":
        return _run_expert_mf(host)

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
        "Пункт 4: UrsusBoot → штатная миграция STOCK→UBI → OpenWrt, затем (одно подтверждение) UrsusBoot заменяется "
        "закреплённым Vanilla OpenWrt U-Boot. Pregnant initramfs и bootm не используются.",
        "Item 4: UrsusBoot -> native STOCK->UBI migration -> OpenWrt, then (one confirmation) UrsusBoot is replaced by "
        "the pinned Vanilla OpenWrt U-Boot. No pregnant initramfs or bootm is used.",
    ))
    reuse_backup, _backup_path = _select_backup_policy("md")

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
        "OpenWrt UBI записан и проверен.",
        "OpenWrt UBI was written and verified.",
    ))
    return _finish_on_vanilla(host, "md")


def _vanilla_fip(family: str) -> tuple[Path, str]:
    """The Vanilla FIP of this kit's UrsusBoot release, verified against the release descriptor."""
    board = ursusboot_release.board(family) or {}
    path = ursusboot_release.path(family, "vanilla_fip")
    want = str(board.get("vanilla_fip_sha256") or "")
    if not path or not path.is_file() or not want or pb.sha_file(path) != want:
        raise RuntimeError(pb.tr(
            f"В комплекте нет закреплённого Vanilla FIP для {MODEL[family]} (нужен UrsusBoot TEST64+).",
            f"The kit has no pinned Vanilla FIP for {MODEL[family]} (UrsusBoot TEST64+ required).",
        ))
    return path, want


def _verify_vanilla_boot(host: str, want: str, seconds: int = 300) -> bool:
    """After reboot: OpenWrt answers over SSH and UBI 'fip' is exactly the pinned Vanilla FIP."""
    cmd = ("for d in /sys/class/ubi/ubi0_*; do n=$(cat $d/name 2>/dev/null); "
           "case $n in fip|fip.old) echo \"VOL $n $(sha256sum /dev/${d##*/} | cut -d' ' -f1)\";; esac; done")
    deadline = time.time() + seconds
    ui.status("WAIT", pb.tr(
        f"Жду загрузку OpenWrt через Vanilla U-Boot (до {seconds} с)...",
        f"Waiting for OpenWrt to boot through Vanilla U-Boot (up to {seconds} s)...",
    ))
    while time.time() < deadline:
        try:
            rc, out = pb.ssh_run(host, cmd, timeout=60, quiet=True, batch_mode=True)
        except Exception:
            rc, out = 255, ""
        vols = dict(line.split()[1:3] for line in out.splitlines() if line.startswith("VOL ") and len(line.split()) >= 3)
        if rc == 0 and "fip" in vols:
            pb._write_session_only(f"[ITEM4_VANILLA] openwrt_ssh=1 fip_sha256={vols.get('fip')} fip_old={'fip.old' in vols}")
            if vols["fip"] == want:
                ui.status("PASS", pb.tr(
                    "OpenWrt загрузился через Vanilla U-Boot; UBI fip = закреплённый Vanilla FIP.",
                    "OpenWrt booted through Vanilla U-Boot; UBI fip = the pinned Vanilla FIP.",
                ))
                return True
            raise RuntimeError(pb.tr(
                f"UBI fip после перезагрузки не совпадает с Vanilla FIP: {vols['fip']} != {want}",
                f"UBI fip after reboot is not the Vanilla FIP: {vols['fip']} != {want}",
            ))
        time.sleep(5)
    ui.status("WARNING", pb.tr(
        "OpenWrt не ответил по SSH. Запись Vanilla была проверена загрузчиком; проверьте загрузку по USB-UART.",
        "OpenWrt did not answer over SSH. The Vanilla write was verified by the bootloader; check the boot over USB-UART.",
    ))
    return False


def _finish_on_vanilla(host: str, family: str) -> int:
    """Item 4 last leg: UrsusBoot Recovery -> pinned Vanilla OpenWrt U-Boot (one-way, confirmed once)."""
    fip, want = _vanilla_fip(family)
    st = uw.status(host)
    if not st.get("vanilla_fip_pinned"):
        raise RuntimeError(pb.tr(
            "Запущенный UrsusBoot не содержит закреплённого Vanilla FIP (старее TEST64). OpenWrt установлен, UrsusBoot остаётся Recovery.",
            "The running UrsusBoot has no pinned Vanilla FIP (older than TEST64). OpenWrt is installed; UrsusBoot stays as Recovery.",
        ))
    ui.section(pb.tr("ЗАМЕНА URSUSBOOT НА VANILLA U-BOOT", "REPLACING URSUSBOOT WITH VANILLA U-BOOT"), style="amber2")
    ui.status("READY", f"Vanilla FIP: {fip.name} · SHA256 {want}")
    ui.note(pb.tr(
        "Однократный переход: Vanilla FIP записывается в UBI fip той же проверенной транзакцией, что и обновление UrsusBoot "
        "(fip.new, контрольное чтение, атомарная замена); UrsusBoot остаётся в fip.old. После перезагрузки WebFailsafe "
        "UrsusBoot недоступен: аварийное восстановление — пункты 5 и 9 через USB-UART.",
        "One-way: the Vanilla FIP is written to UBI fip by the same verified transaction as an UrsusBoot update "
        "(fip.new, readback, atomic swap); UrsusBoot is kept as fip.old. After reboot the UrsusBoot WebFailsafe is gone: "
        "emergency recovery is items 5 and 9 over USB-UART.",
    ))
    answer = ui.prompt(pb.tr(
        "Заменить UrsusBoot на Vanilla U-Boot сейчас? [y/N]: ",
        "Replace UrsusBoot with Vanilla U-Boot now? [y/N]: ",
    )).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        ui.status("STOP", pb.tr(
            "Vanilla не устанавливался. OpenWrt UBI установлен, UrsusBoot остаётся загрузчиком Recovery.",
            "Vanilla was not installed. OpenWrt UBI is installed; UrsusBoot stays as the Recovery bootloader.",
        ))
        try:
            uw.reboot(host)
        except Exception:
            pass
        return 0
    result = uw.replace_with_vanilla(host, fip, confirm=False)
    if not result.get("bootloader_update_complete"):
        raise RuntimeError(f"Vanilla replacement did not reach COMPLETE: {result}")
    pb._write_session_only(f"[ITEM4_VANILLA] family={family} replace_complete=1 fip_sha256={want} fip_old=URSUSBOOT")
    ui.status("PASS", pb.tr(
        "Vanilla U-Boot записан и проверен в UBI fip; UrsusBoot сохранён в fip.old. Перезагружаю.",
        "Vanilla U-Boot written and verified in UBI fip; UrsusBoot kept as fip.old. Rebooting.",
    ))
    try:
        uw.reboot(host)
    except Exception:
        pass
    _verify_vanilla_boot(host, want)
    return 0


def _run_expert_mf(host: str) -> int:
    """Item 4 for XG-040G-MF: same sequence as MD, with the MF persistent runtime.

    Nokia STOCK -> device-derived MF UrsusBoot FIP (mf_runtime_install, the ONE-CLICK
    MF installer) -> UrsusBoot Recovery -> native STOCK->UBI migration with the MF
    preloader UrsusBoot was built for -> COMPLETE. UrsusBoot Recovery is retained.
    """
    import mf_runtime_install
    import one_key_multi

    production = one_key_multi.require_role("mf", "OPENWRT_UBI_SYSUPGRADE")
    preloader = one_key_multi.require_role("mf", "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")
    bl33 = mf_runtime_install.require_bl33()

    ui.section(pb.tr(
        "УСТАНОВИТЬ ЧИСТЫЙ OPENWRT С URSUSBOOT RECOVERY",
        "INSTALL CLEAN OPENWRT WITH URSUSBOOT RECOVERY",
    ), style="amber2")
    ui.status("READY", "Nokia XG-040G-MF / AN7583")
    ui.status("READY", f"UrsusBoot MF runtime: {one_key_multi.MF_TARGET} · BL33 SHA256 {pb.sha_file(bl33)}")
    ui.status("READY", f"OpenWrt: {production.name} · SHA256 {pb.sha_file(production)}")
    ui.status("READY", f"UBI transition preloader: {preloader.name} · SHA256 {pb.sha_file(preloader)}")
    ui.note(pb.tr(
        "Item 4 (MF): FIP собирается из mtd0 этого устройства (native ранние компоненты и factory identity сохраняются), "
        "затем штатный UrsusBoot STOCK→UBI migration backend, затем (одно подтверждение) замена на закреплённый Vanilla OpenWrt U-Boot.",
        "Item 4 (MF): the FIP is derived from this device's mtd0 (native early components and factory identity are preserved), "
        "then the native UrsusBoot STOCK->UBI migration backend, then (one confirmation) the pinned Vanilla OpenWrt U-Boot replaces it.",
    ))
    reuse_backup, _backup_path = _select_backup_policy("mf")

    answer = ui.prompt(pb.tr(
        "Preflight payload пройден. Установить UrsusBoot, затем перевести Nokia STOCK в OpenWrt UBI? [y/N]: ",
        "Payload preflight passed. Install UrsusBoot, then migrate Nokia STOCK to OpenWrt UBI? [y/N]: ",
    )).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        ui.status("STOP", pb.tr("Операция отменена до записи.", "Operation cancelled before any write."))
        return 0

    rc = mf_runtime_install.run_install(
        host=host,
        route="stock",
        unattended=True,
        skip_full_backup=reuse_backup,
        recovery_after=True,
    )
    if rc:
        raise RuntimeError(f"MF UrsusBoot installation failed rc={rc}")

    st = _wait_recovery(host, 90)
    if st is None:
        st = _manual_recovery(host)
    if one_key_multi.mf_runtime_mode(st) != "PERSISTENT_RUNTIME":
        raise RuntimeError(pb.tr(
            "После записи запущен не persistent MF UrsusBoot (RAM-only/legacy). Миграция не начата.",
            "The running MF UrsusBoot is not the persistent runtime (RAM-only/legacy). Migration was not started.",
        ))
    version = str(st.get("version") or "")
    if str(st.get("current_layout") or "") != "STOCK":
        raise RuntimeError(f"expected STOCK layout in UrsusBoot Recovery, got {st.get('current_layout')!r}")
    ui.status("PASS", pb.tr(
        f"UrsusBoot Recovery (MF, persistent) найден: {version or 'version unknown'}.",
        f"UrsusBoot Recovery (MF, persistent) detected: {version or 'version unknown'}.",
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

    pb._write_session_only("[ITEM4_DIRECT_UBI] family=mf migration_complete=1 bootloader=URSUSBOOT retained=1")
    ui.status("PASS", pb.tr(
        "OpenWrt UBI записан и проверен.",
        "OpenWrt UBI was written and verified.",
    ))
    return _finish_on_vanilla(host, "mf")
