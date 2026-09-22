#!/usr/bin/env python3
from __future__ import annotations

import time

import console_ui as ui
import proven_backend as pb
import stock_ab_pregnant as pregnant
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
    ui.section(pb.tr("ВРЕМЕННЫЙ URSUSBOOT RECOVERY", "TEMPORARY URSUSBOOT RECOVERY"), style="amber2")
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
                "Остановлено после проверенной записи временного UrsusBoot; повторная запись mtd0 не нужна.",
                "Stopped after the temporary UrsusBoot write passed readback; do not rewrite mtd0.",
            ))


def run_expert(*, host: str, profile: str) -> int:
    policy = pregnant._policy(profile)
    if policy.family != "md":
        raise RuntimeError(
            "Temporary TEST62 mtd0 bootstrap is currently hardware-proven only for XG-040G-MD; "
            "MF item4 stays blocked until its persistent bootstrap contract is proven."
        )

    files, meta = pregnant._load_payload(policy)
    image = files["pregnant_itb"]
    spec = meta["files"]["pregnant_itb"]

    ui.section(pb.tr(
        "ЧИСТЫЙ OPENWRT ЧЕРЕЗ ВРЕМЕННЫЙ URSUSBOOT RECOVERY",
        "CLEAN OPENWRT VIA TEMPORARY URSUSBOOT RECOVERY",
    ), style="amber2")
    ui.status("READY", f"{policy.model}")
    ui.status("READY", f"Autonomous pregnant ITB: {image.stat().st_size} bytes; SHA256 {spec['sha256']}")
    ui.status("READY", f"Pinned production: SHA256 {meta['unameone_sha256']}")
    ui.note(pb.tr(
        "UrsusBoot используется только как временный Recovery-загрузчик. Pregnant initramfs автономен: production, Vanilla FIP и Vanilla BL2/preloader уже находятся внутри ITB. После успешной миграции UrsusBoot стирается, а загрузчик и Recovery становятся штатными OpenWrt с Fudan-патчем.",
        "UrsusBoot is used only as a temporary Recovery loader. The pregnant initramfs is autonomous: production, Vanilla FIP and Vanilla BL2/preloader are already inside the ITB. After migration UrsusBoot is erased and the bootloader/Recovery become standard OpenWrt with the Fudan patch.",
    ))
    answer = ui.prompt(pb.tr(
        "Preflight payload пройден. Записать временный UrsusBoot в mtd0 и запустить полную автономную миграцию? [y/N]: ",
        "Payload preflight passed. Write temporary UrsusBoot to mtd0 and start the complete autonomous migration? [y/N]: ",
    )).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        ui.status("STOP", pb.tr("Операция отменена до записи.", "Operation cancelled before any write."))
        return 0

    # This is the only persistent write before the autonomous installer starts.
    # run_install performs its own stock identity/geometry/backup/readback proof.
    rc = boot_install.run_install(
        unattended=True,
        host=host,
        recovery_after=True,
        recovery_host=host,
        route="stock",
        skip_full_backup=False,
    )
    if rc:
        raise RuntimeError(f"temporary UrsusBoot installation failed rc={rc}")

    st = _wait_recovery(host, 90)
    if st is None:
        st = _manual_recovery(host)
    version = str(st.get("version") or "")
    ui.status("PASS", pb.tr(
        f"Временный UrsusBoot Recovery найден: {version or 'version unknown'}.",
        f"Temporary UrsusBoot Recovery detected: {version or 'version unknown'}.",
    ))

    ui.status("ACTION", pb.tr(
        "Передаю автономный pregnant initramfs в RAM. NAND на этом шаге не записывается.",
        "Uploading the autonomous pregnant initramfs to RAM. No NAND write occurs in this step.",
    ))
    upload = uw.upload(host, image, "initramfs", progress=True)
    if upload.get("result") != "VALID":
        raise RuntimeError(f"UrsusBoot rejected pregnant initramfs: {upload}")

    check = uw.status(host)
    if not check.get("expert_valid"):
        raise RuntimeError("UrsusBoot status does not confirm the uploaded initramfs as bootable")
    ui.status("PASS", pb.tr(
        "ITB полностью принят и валидирован UrsusBoot.",
        "The complete ITB was received and validated by UrsusBoot.",
    ))

    armed = uw.boot_once(host)
    ui.status("ACTION", pb.tr(
        "Pregnant initramfs запущен из RAM. С этого момента UrsusFlasher только наблюдает за status/log по SSH; сетевой канал не является частью write path.",
        "Pregnant initramfs is booting from RAM. From this point UrsusFlasher only observes status/log over SSH; the network is not part of the write path.",
    ))
    pb._write_session_only(f"[PREGNANT_BOOT_ONCE] {armed!r}")

    pregnant._monitor(host, policy, meta)
    return 0
