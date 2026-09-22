#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"


def test_expert_can_skip_full_backup():
    expert = (SRC / "expert.py").read_text(encoding="utf-8")
    multi = (SRC / "expert_multi.py").read_text(encoding="utf-8")
    one_key = (SRC / "one_key.py").read_text(encoding="utf-8")
    install = (SRC / "ursusboot_install.py").read_text(encoding="utf-8")

    for source in (expert, multi):
        assert "skip_full_backup=skip_backup" in source
        assert "EXPERT backup: Enter" in source
        assert "s — пропустить" in source
        block=source[source.index("if number == 1:"):source.index("elif number == 2:")]
        assert "[y/N]" not in block
        assert "EXPERT backup: Enter" in block

    assert "def main(*, skip_full_backup: bool = False, router_host: str | None = None)" in one_key
    assert "install_ursus_from_stock(stock_host, skip_full_backup=skip_full_backup)" in one_key
    assert "skip_full_backup=skip_full_backup" in install
    assert "full_stock_backup_skipped" in install
    guidance = (SRC / "network_guidance.py").read_text(encoding="utf-8")
    assert "def choose_router_host(" in guidance
    assert "192.168.1.254" in guidance
    assert "Wi-Fi" in guidance and "VPN" in guidance
    assert "LAN2/LAN3" in guidance
    for source in (expert, multi):
        main = source[source.index("def main()"): ]
        assert "choose_router_host(default_host)" in main
        assert main.index("choose_router_host(default_host)") < main.index("probe_device_state(host)")
        assert "router_host=host" in main
    assert "EXPERT: skip the full restore-grade backup for this run? [y/N]" not in multi
    helper=multi[multi.index("def _ask_skip_full_backup"):multi.index("def _project_root")]
    assert "[y/N]" not in helper
    assert "s — skip" in helper
    assert "EXPERT: skip the full restore-grade backup for this run? [y/N]" not in multi


def test_item1_live_stock_gates_are_structural_not_sample_sha():
    source = (SRC / "ursusboot_install.py").read_text(encoding="utf-8")
    build = source[source.index("def build_candidate("):source.index("def open_root(")]

    assert "live BootROM prefix 0x0..0x7ff differs from the proven Nokia prefix" not in build
    assert "live persistent BL2 differs from proven Nokia BL2" not in build
    assert "EXPECTED_ROM_HEADER_SHA256" not in build
    assert "EXPECTED_STOCK_BL2_SHA256" not in build
    assert "live mtd0 has no Airoha FIP at physical 0x800" in build
    assert "env_crc_info(live)" in build
    assert "hybrid FIP overlaps stock boot environment" in build
    assert "exactly one Trusted Boot Firmware BL2 entry" in build
    assert "BootROM prefix preservation invariant failed" in build
    assert "stock boot environment preservation invariant failed" in build

    stock = source[source.index("def run_install("):source.index("def _materialize_mtd0_backup(")]
    assert "mtd0_write_preflight(telnet)" in stock
    assert "proc.get(0) != MTD0_EXPECTED" not in source
    assert "tuple(got[:2]) != tuple(MTD0_EXPECTED[:2])" in source
    assert "capture_live_mtd0(telnet, access, before_path)" in stock
    assert 'answer = ui.prompt("Начать запись mtd0? [y/N]: ")' in stock
    assert "after_sha = remote_mtd0_sha(telnet)" in stock
    assert "READBACK_MISMATCH" in stock


test_expert_can_skip_full_backup()
test_item1_live_stock_gates_are_structural_not_sample_sha()
print("selftest_expert_item1: PASS")
