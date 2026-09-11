#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import console_ui as ui
import uart_bootarea_restore as ubr

HERE = Path(__file__).resolve().parent
BOOT_AREA_SIZE = 0x80000
MF_STOCK_MTD0_SHA256 = "144d63272049eeb7122a01f2f3a0192b874ca4c68c10a5b4726fa4c2e84ac1bf"


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def bundled_stock_mtd0(family: str) -> Path | None:
    family = family.strip().lower()
    payloads = ubr._runtime_payload_root()
    candidates: list[Path]
    if family == "md":
        candidates = [
            payloads / "md" / "ursusboot" / "stock_mtd0_reference.bin",
            HERE / "payloads" / "md" / "ursusboot" / "stock_mtd0_reference.bin",
        ]
    elif family == "mf":
        candidates = [
            payloads / "mf" / "stock" / "nokia-xg-040g-mf-stock-mtd0.bin",
            HERE / "payloads" / "mf" / "stock" / "nokia-xg-040g-mf-stock-mtd0.bin",
        ]
    else:
        raise RuntimeError(tr("Неизвестная модель Nokia.", "Unknown Nokia model."))
    for path in candidates:
        if not path.is_file():
            continue
        path = path.resolve()
        if path.stat().st_size != BOOT_AREA_SIZE:
            raise RuntimeError(f"bundled {family.upper()} stock mtd0 size mismatch: {path.stat().st_size} != {BOOT_AREA_SIZE}")
        if family == "mf":
            got = ubr.sha256(path)
            if got != MF_STOCK_MTD0_SHA256:
                raise RuntimeError(f"bundled MF stock mtd0 SHA256 mismatch: {got} != {MF_STOCK_MTD0_SHA256}")
        return path
    return None


def restore_factory_bootarea(family: str) -> None:
    family = family.strip().lower()
    profile = ubr.family_profile(family)
    image = bundled_stock_mtd0(family)

    ui.rule(tr("ЗАВОДСКОЙ ЗАГРУЗЧИК NOKIA", "NOKIA FACTORY BOOTLOADER"), style="amber2")
    ui.status("TARGET", f"{profile['model']} / {profile['soc']}")
    if image is not None:
        ui.status("SOURCE", tr(
            f"Комплектный заводской boot-area/mtd0: {image.name}",
            f"Bundled factory boot-area/mtd0: {image.name}",
        ))
        if family == "mf":
            ui.status("SHA256", MF_STOCK_MTD0_SHA256)
    else:
        ui.status(tr("НЕТ В КОМПЛЕКТЕ", "NOT BUNDLED"), tr(
            "Для этой модели canonical заводской mtd0 ещё не включён в пакет. Можно указать проверенный 512-КиБ mtd0 вручную.",
            "The canonical factory mtd0 for this model is not bundled yet. A validated 512-KiB mtd0 may be selected manually.",
        ))
        image = ubr.choose_image()

    ubr.restore(family, image)
