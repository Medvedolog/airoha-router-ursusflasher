#!/usr/bin/env python3
"""EXPERT item 6 route selection: the operator's choice wins; 'automatic'
sends UrsusBoot Recovery and OpenWrt-on-UrsusBoot to the UrsusBoot route
(no SSH / no one-shot bootcmd), everything else as before."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import stock_restore as sr  # noqa: E402

calls: list[str] = []
sr.restore_via_ursusboot = lambda host="192.168.1.1": calls.append(f"ursus:{host}")
sr.restore_over_uart = lambda: calls.append("uart")
sr.restore_from_running = lambda state: calls.append("running")
sr.ui.rule = sr.ui.menu_item = sr.ui.status = sr.ui.note = lambda *a, **k: None


def run(choice: str, state) -> str:
    calls.clear()
    sr.ui.prompt = lambda *_a, **_k: choice
    sr.restore_nokia(state)
    return ",".join(calls)


ursus = SimpleNamespace(host="192.168.1.1", current_system="RECOVERY", probe_status="PARTIAL",
                        model="", soc="", evidence={"ursus_status": {"product": "UrsusBoot"}})
openwrt = SimpleNamespace(host="192.168.1.1", current_system="OPENWRT_UBI", probe_status="COMPLETE",
                          model="Nokia XG-040G-MF", soc="AN7583", evidence={"openwrt_board": "nokia,xg-040g-mf-ubi"})
dead = SimpleNamespace(host="192.168.1.1", current_system="UNKNOWN", probe_status="FAILED",
                       model="", soc="", evidence={})

checks = [
    (run("", ursus) == "ursus:192.168.1.1", "auto + UrsusBoot Recovery -> UrsusBoot route (no SSH)"),
    (run("1", openwrt) == "running", "auto + OpenWrt -> running-OpenWrt route"),
    (run("1", dead) == "uart", "auto + no proven network -> BootROM/UART"),
    (run("4", openwrt) == "uart", "choice 4 forces BootROM/UART even when OpenWrt answers"),
    (run("3", openwrt) == "ursus:192.168.1.1", "choice 3 forces the UrsusBoot route"),
    (run("2", ursus) == "running", "choice 2 forces the running-OpenWrt route"),
    (run("0", openwrt) == "", "choice 0 does nothing"),
]
ok = True
for good, label in checks:
    print(("PASS " if good else "FAIL ") + label)
    ok &= good

# OpenWrt booted by UrsusBoot: detection from bootcmd.
sr.proven.ssh_run = lambda host, cmd, **k: (0, "BOOTCMD=ursusdispatch\n")
good = sr._running_on_ursusboot("192.168.1.1")
sr.proven.ssh_run = lambda host, cmd, **k: (0, "BOOTCMD=run check_buttons ; run boot_ubi\n")
good &= not sr._running_on_ursusboot("192.168.1.1")
print(("PASS " if good else "FAIL ") + "bootcmd=ursusdispatch is recognised as OpenWrt on UrsusBoot")
ok &= good
# UrsusBoot route: upload -> expert_valid gate -> boot-once -> recovery -> restore.
import one_key_multi  # noqa: E402
import ursus_web_client as uw  # noqa: E402
seq: list[str] = []
valid = {"v": True}
sr._wait_ursusboot = lambda host, seconds=300: {"product": "UrsusBoot"}
one_key_multi._family_from_ursus = lambda st: "mf"
sr._recovery_initramfs = lambda fam: (Path(f"{fam}.itb"), "00")
sr._one_yn_before_recovery_handoff = lambda **k: True
uw.upload = lambda host, path, kind, **k: seq.append(f"upload:{kind}")
uw.status = lambda host: {"expert_valid": valid["v"], "expert_reason": "bad fit"}
uw.boot_once = lambda host: seq.append("boot_once")
sr.proven.wait_for_stable_openwrt = lambda host, t, expected_mode=None: "recovery"
sr.proven.perform_stock_restore_over_ssh = lambda *a, **k: seq.append("restore")
sr._restore_from_ursusboot_after_inputs("192.168.1.1", "192.168.1.254", 1069, Path("b"), Path("p"),
                                        {"all_flash_sha256": "x"}, "mf")
good = seq == ["upload:initramfs", "boot_once", "restore"]
print(("PASS " if good else "FAIL ") + "UrsusBoot route: initramfs upload -> boot-once -> restore " + ",".join(seq))
ok &= good
seq.clear(); valid["v"] = False
try:
    sr._restore_from_ursusboot_after_inputs("192.168.1.1", "192.168.1.254", 1069, Path("b"), Path("p"), {}, "mf")
    good = False
except sr.proven.Error:
    good = seq == ["upload:initramfs"]
print(("PASS " if good else "FAIL ") + "UrsusBoot route stops before boot/write if UrsusBoot rejects the initramfs")
ok &= good
seq.clear(); valid["v"] = True
try:
    sr._restore_from_ursusboot_after_inputs("192.168.1.1", "192.168.1.254", 1069, Path("b"), Path("p"), {}, "md")
    good = False
except sr.proven.Error:
    good = seq == []
print(("PASS " if good else "FAIL ") + "UrsusBoot route refuses a backup of the other family before uploading")
ok &= good
print("selftest_restore_routes: " + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
