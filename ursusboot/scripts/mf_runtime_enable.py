#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path

VERSION = "0.1.0-TEST61"
MD_PRELOADER_SHA = "6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808"
MF_PRELOADER_SHA = "778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e"
MD_BL2_SHA = "6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d"
MF_BL2_SHA = "c655479c4d14b4f6d1a7a5eb8de80bfb204b3cdf46c9e48a5c6f3aea22d98131"
MD_PRELOADER_SIZE = "113447"
MF_PRELOADER_SIZE = "118333"


def _load_validator_module() -> object:
    path = Path(__file__).with_name("mf3_persist2_validator.py")
    spec = importlib.util.spec_from_file_location("mf_runtime_validator", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load MF validator source: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rewrite_identity(text: str) -> str:
    replacements = (
        ("Nokia XG-040G-MD", "Nokia XG-040G-MF"),
        ("Nokia_XG-040G-MD", "Nokia_XG-040G-MF"),
        ("nokia_xg-040g-md", "nokia_xg-040g-mf"),
        ("nokia,xg-040g-md-ubi", "nokia,xg-040g-mf-ubi"),
        ("nokia,xg-040g-md", "nokia,xg-040g-mf"),
        ("xg-040g-md", "xg-040g-mf"),
        ("NOKIA_XG040GMD_STOCK", "NOKIA_XG040GMF_STOCK"),
        ("URSUSBOOT_MD", "URSUSBOOT_MF"),
        ("TCBOOT_MD", "TCBOOT_MF"),
        ("XG040GMC2P5G", "XG040GMF"),
        ("AN7581DT", "AN7583DT"),
        ("Airoha AN7581", "Airoha AN7583"),
        ("AN7581", "AN7583"),
        ("an7581", "an7583"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _byte_array(hexstr: str) -> str:
    return ", ".join("0x" + hexstr[i:i + 2] for i in range(0, len(hexstr), 2))


def _patch_mf_transition_constants(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    pairs = (
        ("preloader_sha_text", MD_PRELOADER_SHA, MF_PRELOADER_SHA),
        ("preloader_sha_bytes", _byte_array(MD_PRELOADER_SHA), _byte_array(MF_PRELOADER_SHA)),
        ("bl2_sha_text", MD_BL2_SHA, MF_BL2_SHA),
        ("bl2_sha_bytes", _byte_array(MD_BL2_SHA), _byte_array(MF_BL2_SHA)),
    )
    for label, old, new in pairs:
        counts[label] = text.count(old)
        text = text.replace(old, new)
    counts["preloader_size"] = text.count(MD_PRELOADER_SIZE)
    text = text.replace(MD_PRELOADER_SIZE, MF_PRELOADER_SIZE)
    return text, counts


def _restore_file(root: Path, pristine: Path, rel: str) -> Path:
    src = pristine / rel
    dst = root / rel
    if not src.is_file() or not dst.is_file():
        raise SystemExit(f"runtime restore source missing: {rel}")
    shutil.copy2(src, dst)
    return dst


def transform(root: Path, pristine: Path) -> None:
    root = root.resolve()
    pristine = pristine.resolve()

    # MF2 recovery deliberately amputates persistent entrypoints. Runtime starts
    # from the exact TEST61 implementations again, then applies only MF board
    # identity/transition constants. This keeps the MD implementation frozen.
    restored = (
        "cmd/ursusweb.c",
        "cmd/ursusubi.c",
        "cmd/ursusdispatch.c",
        "cmd/Makefile",
    )
    for rel in restored:
        _restore_file(root, pristine, rel)

    for rel in ("cmd/ursusweb.c", "cmd/ursusubi.c", "cmd/ursusdispatch.c", "cmd/ursusstock.c"):
        path = root / rel
        text = _rewrite_identity(path.read_text(encoding="utf-8"))
        text, counts = _patch_mf_transition_constants(text)
        path.write_text(text, encoding="utf-8")
        if rel in ("cmd/ursusweb.c", "cmd/ursusubi.c"):
            print(f"MF_RUNTIME_CONSTANTS file={rel} " + " ".join(f"{k}={v}" for k, v in counts.items()))

    # Keep the MF2 FIP writer blocked for runtime self-update, but restore the
    # general MF structural validator so STOCK->UBI migration can validate the
    # current device-derived 9-entry FIP without a build hash whitelist.
    validator = _load_validator_module()
    update = root / "cmd/ursusupdate.c"
    u = _rewrite_identity(update.read_text(encoding="utf-8"))
    u = validator.replace_func(u, "ursus_fip_parse", validator.FIP_PARSE)
    u = validator.replace_func(u, "ursus_fip_validate_current", validator.VALIDATE_CURRENT)
    u = validator.replace_func(u, "ursus_fip_validate_buf", validator.VALIDATE_BUF)
    u = validator.replace_func(u, "ursus_fip_validate", validator.VALIDATE)
    u = u.replace("MF2_STOCK_FIP_VALIDATION_DISABLED", "NOKIA_XG040GMF_STOCK")
    update.write_text(u, encoding="utf-8")

    # Runtime capability is explicit. Unlike RAM recovery, POST install/update
    # routes and the ordinary UBI diagnostic probe come from pristine TEST61.
    web = root / "cmd/ursusweb.c"
    w = web.read_text(encoding="utf-8")
    status_old = '"\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"'
    status_new = '"\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"ram_read_only\\\":false,\\\"persistent_write_enabled\\\":true,\\\"ram_boot_enabled\\\":true,\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"'
    if status_old in w:
        w = w.replace(status_old, status_new, 1)
    elif "persistent_write_enabled" not in w:
        raise SystemExit("MF runtime status capability anchor missing")
    web.write_text(w, encoding="utf-8")

    # The MF2 transform keeps the safe MF-native LED labels and removes AN7581
    # raw SCU/MT7531 MMIO. HWTEST8 is applied by the board build after this step.
    led = (root / "cmd/ursusled.c").read_text(encoding="utf-8")
    for token in ('#define LED_STATUS_RED "red:wan"', '#define LED_USB1_GREEN "green:usb-1"', '#define LED_USB2_GREEN "green:usb-2"'):
        if token not in led:
            raise SystemExit(f"MF runtime LED label missing: {token}")
    for token in ("0x1fa20000", "0x1fb58000"):
        if token in led:
            raise SystemExit(f"AN7581 raw LED MMIO survived MF runtime: {token}")

    make = (root / "cmd/Makefile").read_text(encoding="utf-8")
    if "ursusstock.o" not in make:
        raise SystemExit("MF runtime StockBridge object is not linked")

    dispatch = (root / "cmd/ursusdispatch.c").read_text(encoding="utf-8")
    if 'run_command("ursusstockboot", 0)' not in dispatch:
        raise SystemExit("MF runtime stock boot dispatch is missing")
    if "URSUS_MF2_STOCKBRIDGE_DISABLED" in dispatch:
        raise SystemExit("MF RAM-only StockBridge gate survived runtime transform")

    web_text = web.read_text(encoding="utf-8")
    ubi_text = (root / "cmd/ursusubi.c").read_text(encoding="utf-8")
    combined = web_text + ubi_text
    if "MF2 RAM-only build: persistent operations disabled" in combined:
        raise SystemExit("MF RAM-only HTTP POST gate survived runtime transform")
    for marker in (
        "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE",
        "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION",
        "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE_STEP",
        "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION_STEP",
        "URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND",
    ):
        if marker in combined:
            raise SystemExit(f"MF recovery write gate survived runtime transform: {marker}")

    # The exact production MF preloader + derived 128-KiB BL2 candidate are
    # hardware-proven in the retained Medve lineage. Require the constants to
    # actually reach source; silently keeping MD constants is forbidden.
    if MF_PRELOADER_SHA not in combined:
        raise SystemExit("MF production preloader SHA was not bound into runtime Web/UBI source")
    if MF_BL2_SHA not in combined:
        raise SystemExit("MF BL2 candidate SHA was not bound into runtime Web/UBI source")
    if MD_PRELOADER_SHA in combined or MD_BL2_SHA in combined:
        raise SystemExit("MD transition hash leaked into MF runtime Web/UBI source")

    version_h = root / "include/ursus_version.h"
    vh = version_h.read_text(encoding="utf-8")
    import re
    vh, n = re.subn(r'#define URSUS_VERSION "[^"]+"', f'#define URSUS_VERSION "{VERSION}"', vh, count=1)
    if n != 1:
        raise SystemExit("MF runtime version header anchor missing")
    version_h.write_text(vh, encoding="utf-8")
    (root / ".scmversion").write_text(f"-UrsusBoot-{VERSION}\n", encoding="ascii")

    identity_files = ("cmd/ursusweb.c", "cmd/ursusubi.c", "cmd/ursusdispatch.c", "cmd/ursusstock.c", "cmd/ursusupdate.c", "include/ursusweb_ui.inc")
    leaks: list[str] = []
    for rel in identity_files:
        data = (root / rel).read_text(encoding="utf-8")
        for token in ("Nokia XG-040G-MD", "nokia,xg-040g-md", "nokia_xg-040g-md", "AN7581DT", "XG040GMC2P5G"):
            if token in data:
                leaks.append(f"{rel}:{token}")
    if leaks:
        raise SystemExit("MF runtime board identity leak: " + ", ".join(leaks))

    print("MF_RUNTIME_ENABLE=PASS writers=ubi/install/reset stockbridge=enabled fip-selfupdate=host-only validator=mf-general")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    ap.add_argument("pristine_root", type=Path)
    args = ap.parse_args()
    transform(args.source_root, args.pristine_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
