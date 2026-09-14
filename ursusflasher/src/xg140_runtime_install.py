#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import console_ui as ui
import ursusboot_install as transport
import xg140_profile as xp
import xg140_stock_transport as xs


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def install_from_stock(*, host: str = "192.168.1.1") -> int:
    bl33_path, build_info = xp.require_bl33()
    bl33 = bl33_path.read_bytes()
    root = xp.project_root()
    private = root / "work" / "private" / "xg140-runtime-install"
    results = root / "results"
    private.mkdir(parents=True, exist_ok=True); results.mkdir(parents=True, exist_ok=True)
    run_stamp = stamp()
    before = private / f"xg140-mtd0-before-{run_stamp}.bin"
    target = private / f"xg140-mtd0-ursusboot-{run_stamp}.bin"
    result_path = results / f"xg140-ursusboot-telnet-{run_stamp}.json"
    result = {
        "operation": "XG140_NATIVE_DEVICE_DERIVED_URSUSBOOT_INSTALL",
        "transport": "stock-telnet-tftp", "host": host,
        "status": "RUNNING", "started_at": run_stamp, "payload": build_info,
    }
    access = telnet = None
    try:
        access = xs.open_stock_access(host)
        telnet = xs.uid0_telnet(access)
        pf = transport.mtd0_write_preflight(telnet); result["preflight"] = pf
        _remote_before, live_sha = transport.capture_live_mtd0(telnet, access, before)
        live = before.read_bytes()
        candidate, meta = xp.build_candidate(live, bl33)
        target.write_bytes(candidate); expected = meta["candidate_sha256"]
        result.update({"source_mtd0_sha256": live_sha, "private_backup": str(before), "candidate": meta})

        ui.rule("XG140 NATIVE-HYBRID", style="amber2")
        ui.status("TARGET", f"{xp.MODEL} / {xp.SOC} / profile={xp.EXPECTED_PROFILE}")
        ui.status("SOURCE", f"live mtd0 SHA256={live_sha}")
        ui.status("BL33", f"{bl33_path.name} · {len(bl33)} bytes · SHA256={xp.sha256_bytes(bl33)}")
        ui.status("FIP", f"entries={meta['entry_count']} old_end=0x{meta['old_fip_end']:x} new_end=0x{meta['new_fip_end']:x} physical_end=0x{meta['physical_end']:x}")
        ui.note(tr(
            "Live BootROM prefix 0x000..0x7ff и vendor env 0x7c000..0x7ffff сохраняются; меняется только NT_FW/BL33.",
            "Live BootROM prefix 0x000..0x7ff and vendor env 0x7c000..0x7ffff are preserved; only NT_FW/BL33 changes.",
        ))
        if live_sha == expected:
            result.update(status="ALREADY_EXACT", readback_sha256=live_sha, completed_at=stamp())
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ui.status(tr("ГОТОВО", "READY"), tr("Точный XG140 UrsusBoot уже в mtd0; запись пропущена.", "Exact XG140 UrsusBoot is already in mtd0; write skipped."))
            return 0

        remote = transport.upload_candidate(telnet, access, target)
        rc, check = telnet.command_clean(f"wc -c < {shlex.quote(remote)}; sha256sum {shlex.quote(remote)}", timeout=60)
        if rc or str(xp.BOOT_AREA_SIZE) not in check or expected not in check.lower():
            raise RuntimeError("XG140 candidate transfer verification failed")
        ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
        print(f"  XG140 mtd0 0x0..0x7ffff; writer={pf['writer']}; native FIP except NT_FW preserved; full readback required.")
        if ui.prompt(tr("Начать запись? [y/N]: ", "Start writing? [y/N]: ")).strip().lower() not in ("y", "yes", "д", "да"):
            result.update(status="CANCELLED_BEFORE_WRITE", completed_at=stamp())
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 2

        result["write_started_at"] = stamp()
        rc, out = transport.write_image(telnet, remote, pf["writer"])
        result.update(write_rc=rc, write_output_tail=out[-4000:])
        if rc:
            result["status"] = "WRITE_STATE_UNKNOWN"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError("XG140 mtd0 writer failed; no alternate writer attempted")
        rb = transport.remote_mtd0_sha(telnet); result["readback_sha256"] = rb
        if rb != expected:
            result.update(status="READBACK_MISMATCH", completed_at=stamp())
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError("XG140 full mtd0 readback mismatch; DO NOT reboot")
        result.update(status="WRITE_AND_READBACK_PASS", completed_at=stamp())
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ui.status(tr("ГОТОВО", "READY"), f"XG140 mtd0 full readback PASS: {rb}")
        ui.status(tr("ИНФО", "INFO"), tr(f"Исходный mtd0: {before}", f"Original mtd0: {before}"))
        reboot = ui.prompt(tr("Enter — reboot для cold-boot теста, N — остаться в stock: ", "Enter — reboot for cold-boot test, N — stay in stock: ")).strip().lower()
        if reboot in ("n", "no", "нет"):
            return 0
        try:
            telnet.send_line("sync; reboot"); time.sleep(1)
        except Exception:
            pass
        ui.status(tr("СДЕЛАЙТЕ", "ACTION"), tr(
            "Сохраните UART cold boot до UrsusBoot → ursusdispatch → stock Linux.",
            "Capture cold-boot UART through UrsusBoot → ursusdispatch → stock Linux.",
        ))
        return 0
    finally:
        if telnet:
            try: telnet.close()
            except Exception: pass
        if access:
            access.close_web(announce=False)


def main() -> int:
    return install_from_stock(host=os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1"))


if __name__ == "__main__":
    raise SystemExit(main())
