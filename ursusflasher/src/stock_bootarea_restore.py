#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import console_ui as ui
import uart_bootarea_restore as ubr

HERE = Path(__file__).resolve().parent


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
        if path.is_file():
            return path.resolve()
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
    else:
        ui.status(tr("НЕТ В КОМПЛЕКТЕ", "NOT BUNDLED"), tr(
            "Для этой модели canonical заводской mtd0 ещё не включён в пакет. Можно указать проверенный 512-КиБ mtd0 вручную.",
            "The canonical factory mtd0 for this model is not bundled yet. A validated 512-KiB mtd0 may be selected manually.",
        ))
        image = ubr.choose_image()

    ubr.restore(family, image)
