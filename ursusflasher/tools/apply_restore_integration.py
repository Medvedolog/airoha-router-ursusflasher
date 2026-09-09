#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact anchor, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_device_state() -> None:
    path = ROOT / "ursusflasher/src/device_state.py"
    replace_once(
        path,
        '''                import board_profiles as bp\n                writes_enabled = bp.persistent_writes_enabled(board_profile)\n''',
        '''                import board_profiles as bp\n                writes_enabled = bp.write_action_enabled(board_profile, key)\n''',
        "device-state profile action gate",
    )
    replace_once(
        path,
        '''                reason = terms.tr(\n                    f"профиль {board_key.upper()} подключён только для чтения; persistent write будет включён после аппаратной приёмки",\n                    f"{board_key.upper()} profile is read-only; persistent writes stay disabled until hardware acceptance",\n                )\n''',
        '''                reason = terms.tr(\n                    f"профиль {board_key.upper()} не разрешает это persistent write действие; доступны только явно доказанные recovery writers",\n                    f"{board_key.upper()} profile does not authorize this persistent write action; only explicitly proven recovery writers are available",\n                )\n''',
        "device-state profile gate reason",
    )


def patch_expert() -> None:
    path = ROOT / "ursusflasher/src/expert.py"
    replace_once(
        path,
        '''import network_guidance\nimport ursus_web_client as uw\n''',
        '''import network_guidance\nimport stock_restore\nimport ursus_web_client as uw\n''',
        "expert stock_restore import",
    )
    replace_once(
        path,
        '''    if number == 6:\n        return (\n            "Заводской образ Nokia из проверенной резервной копии; backend пока не подключён",\n            "Nokia factory image from a validated backup; backend is not connected yet",\n        )\n''',
        '''    if number == 6:\n        return (\n            "Проверенный stock backup: автоматически без UART через U-Boot+RAM initramfs при доступной OpenWrt/recovery; иначе BootROM/XMODEM",\n            "Validated stock backup: automatically without UART through U-Boot+RAM initramfs when OpenWrt/recovery is available; otherwise BootROM/XMODEM",\n        )\n''',
        "expert item 6 detail",
    )
    replace_once(
        path,
        '''        elif number == 5:\n            network_guidance.show()\n            if confirm_uart_recovery(\n                "Airoha BootROM запустит среду восстановления из оперативной памяти; механизм записи остаётся прежним до отдельной переработки транзакционной модели.",\n                "Airoha BootROM will start recovery from RAM; the destructive backend remains unchanged until the transaction refactor.",\n            ):\n                run_action(ursusboot_update.uart_bootrom_recover, write_may_happen=True)\n        elif number == 7:\n''',
        '''        elif number == 5:\n            network_guidance.show()\n            if confirm_uart_recovery(\n                "Airoha BootROM запустит среду восстановления из оперативной памяти; механизм записи остаётся прежним до отдельной переработки транзакционной модели.",\n                "Airoha BootROM will start recovery from RAM; the destructive backend remains unchanged until the transaction refactor.",\n            ):\n                run_action(ursusboot_update.uart_bootrom_recover, write_may_happen=True)\n        elif number == 6:\n            network_guidance.show()\n            # Restore owns its single destructive y/N at the latest safe point:\n            # before one-shot persistent bootcmd on the no-UART route, or after\n            # RECOVERY_SAFE + geometry + TFTP preflight on the UART route.\n            run_action(lambda: stock_restore.restore_nokia(_interactive_diagnostic_state(state)), write_may_happen=True)\n        elif number == 7:\n''',
        "expert item 6 dispatch",
    )


def patch_capabilities() -> None:
    path = ROOT / "config/FIRMWARE_CAPABILITIES.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    action = (data.get("ui_actions") or {}).get("restore_nokia")
    if not isinstance(action, dict):
        raise SystemExit("capabilities: ui_actions.restore_nokia missing")
    if action.get("number") != 6 or action.get("write_capable") is not True:
        raise SystemExit("capabilities: restore_nokia contract changed")
    action["implemented"] = True
    action["backend"] = "STATE_RESOLVED_STOCK_RESTORE; RUNNING_UBOOT_RAM_INITRAMFS_OR_BOOTROM_UART"
    action.pop("unavailable_reason_ru", None)
    action.pop("unavailable_reason_en", None)

    md = data.get("md")
    if isinstance(md, dict):
        md["STOCK_RESTORE_RUNNING"] = (
            "EXPOSED_EXPERT_ITEM_6; FAMILY_SAFE_MD_MF_RAM_INITRAMFS; ONE_ORDINARY_YN; "
            "ONE_SHOT_BOOTCMD_VERIFIED; NO_AUTOMATIC_SECOND_BOOTCMD_WRITER; IBU_READBACK_THEN_BL2_LAST"
        )
        md["STOCK_RESTORE_BOOTROM"] = (
            "EXPOSED_EXPERT_ITEM_6; FAMILY_AWARE_MD_MF_RECOVERY_SAFE_XMODEM; "
            "SAFE_MARKER_NONCE_GEOMETRY_TFTP_PREFLIGHT; ONE_ORDINARY_YN; "
            "BADBLOCK_AWARE_READBACK; BL2_LAST"
        )
        md["OPENWRT_RAW_RESTORE"] = (
            "EXPERT_ITEM_6; VERIFIED_STOCK_BACKUP_ONLY; PRODUCTION_OPENWRT_USES_BOARD_SPECIFIC_RAM_RECOVERY; "
            "RECOVERY_SSH_OR_BOOTROM_RAM_UBOOT; WRITE_STATE_UNKNOWN_NO_AUTOMATIC_FALLBACK"
        )
    data["version"] = str(data.get("version") or "") + "-stockrestore1"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify() -> None:
    expert = (ROOT / "ursusflasher/src/expert.py").read_text(encoding="utf-8")
    state = (ROOT / "ursusflasher/src/device_state.py").read_text(encoding="utf-8")
    caps = json.loads((ROOT / "config/FIRMWARE_CAPABILITIES.json").read_text(encoding="utf-8"))
    if "import stock_restore" not in expert or "elif number == 6:" not in expert:
        raise SystemExit("verify: expert restore integration missing")
    if "bp.write_action_enabled(board_profile, key)" not in state:
        raise SystemExit("verify: profile-scoped write gate missing")
    action = caps["ui_actions"]["restore_nokia"]
    if action.get("implemented") is not True or action.get("backend") == "NONE":
        raise SystemExit("verify: restore_nokia capability not enabled")
    print("URSUS_STOCK_RESTORE_INTEGRATION_PATCH=PASS")


def main() -> int:
    patch_device_state()
    patch_expert()
    patch_capabilities()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
