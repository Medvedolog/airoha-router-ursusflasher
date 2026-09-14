#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLASHER = ROOT / "config" / "BOARD_PROFILES.json"
BOOT = ROOT / "ursusboot" / "configs" / "board-profiles.json"


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("profiles"), dict):
        raise SystemExit(f"PROFILE_BRIDGE_FAIL invalid catalog: {path}")
    return data["profiles"]


def norm_soc(value: str) -> str:
    s = str(value).lower().replace("airoha", "").replace("dt", "")
    return "".join(ch for ch in s if ch.isalnum())


def main() -> int:
    flasher = load(FLASHER)
    boot = load(BOOT)
    if not flasher:
        raise SystemExit("PROFILE_BRIDGE_FAIL empty UrsusFlasher catalog")

    for key, fp in flasher.items():
        bpkey = fp.get("ursusboot_profile")
        if not bpkey:
            raise SystemExit(f"PROFILE_BRIDGE_FAIL {key}: ursusboot_profile missing")
        if bpkey not in boot:
            raise SystemExit(f"PROFILE_BRIDGE_FAIL {key}: unknown UrsusBoot profile {bpkey}")
        bp = boot[bpkey]
        if norm_soc(fp.get("soc", "")) != norm_soc(bp.get("soc", "")):
            raise SystemExit(
                f"PROFILE_BRIDGE_FAIL {key}: SoC mismatch flasher={fp.get('soc')} boot={bp.get('soc')}"
            )
        model = str(fp.get("model", "")).lower()
        boot_model = str(bp.get("model", "")).lower()
        if "xg-140g-md" in model and "xg-140g-md" not in boot_model:
            raise SystemExit(f"PROFILE_BRIDGE_FAIL {key}: XG140 model mismatch")
        if "xg-040g-md" in model and "xg-040g-md" not in boot_model:
            raise SystemExit(f"PROFILE_BRIDGE_FAIL {key}: MD model mismatch")
        if "xg-040g-mf" in model and "xg-040g-mf" not in boot_model:
            raise SystemExit(f"PROFILE_BRIDGE_FAIL {key}: MF model mismatch")
        print(
            f"PROFILE_BRIDGE {key}->{bpkey} soc={fp.get('soc')} "
            f"derivation={bp.get('derivation')} policy={bp.get('board_policy_header')}"
        )

    xg = flasher.get("xg140")
    if not xg:
        raise SystemExit("PROFILE_BRIDGE_FAIL xg140 profile missing")
    wp = xg.get("write_policy") or {}
    if wp.get("persistent_write_enabled") is not False or not wp.get("engineering_only"):
        raise SystemExit("PROFILE_BRIDGE_FAIL XG140 persistent writes must remain pre-HW engineering-only")
    evidence = xg.get("evidence") or {}
    if evidence.get("raw_uboot_go_from_tcboot") != "HW_REJECTED_APPLICATION_RETURN_RC1":
        raise SystemExit("PROFILE_BRIDGE_FAIL XG140 raw-go rejection evidence missing")
    if evidence.get("persistent_ursusboot_cold_boot") != "HW_PENDING":
        raise SystemExit("PROFILE_BRIDGE_FAIL XG140 cold-boot status must remain HW_PENDING")

    print("PROFILE_CATALOG_BRIDGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
