#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import device_state as ds
import expert_mf_acceptance as acc


def state(model: str, soc: str, system: str, probe: str = ds.PROBE_COMPLETE) -> ds.DeviceState:
    return ds.DeviceState(
        model=model,
        soc=soc,
        current_system=system,
        current_layout="NOKIA_STOCK" if system == "NOKIA_STOCK" else "OPENWRT_UBI",
        probe_status=probe,
    )


# MD behavior must remain byte/code-path independent from the feature wrapper.
md = state("Nokia XG-040G-MD", "Airoha AN7581", "NOKIA_STOCK")
assert acc.acceptance_action_applicability(md)[2] == acc._original_action_applicability(md)[2]

# Only a complete, positively identified MF STOCK state receives the acceptance writer.
mf_stock = state("Nokia XG-040G-MF", "Airoha AN7583", "NOKIA_STOCK")
a = acc.acceptance_action_applicability(mf_stock)[2]
assert a.enabled is True
assert a.write_capable is True
assert a.resolved_backend == acc.MF_ACCEPTANCE_BACKEND
assert a.reason == ""

for blocked in (
    state("Nokia XG-040G-MF", "Airoha AN7583", "OPENWRT_UBI"),
    state("Nokia XG-040G-MF", "Airoha AN7583", "RECOVERY"),
    state("Nokia XG-040G-MF", "Airoha AN7583", "NOKIA_STOCK", ds.PROBE_PARTIAL),
):
    action = acc.acceptance_action_applicability(blocked)[2]
    assert action.enabled is False
    assert action.resolved_backend == "BOARD_PROFILE_WRITE_DISABLED"

# Exercise dispatch without hardware: MF must use the dedicated acceptance installer,
# never the captured MD dispatcher. Repeated family proof and root bootstrap are mandatory.
events: list[str] = []


class Access:
    family = "mf"

    def close_web(self, announce: bool = False) -> None:
        events.append("close_web")


class Telnet:
    def close(self) -> None:
        events.append("close_telnet")


old_ask = acc.proven.ask_credentials
old_login = acc.proven.login_root_family
old_require = acc.proven.require_supported_model_over_telnet
old_run = acc.mf_persistent_install.run_stock_acceptance
try:
    acc.proven.ask_credentials = lambda **kwargs: (events.append("ask_credentials") or Access())

    def fake_login(access, family, allow_service_provisioning=False):
        assert family == "mf"
        assert allow_service_provisioning is True
        events.append("login_root_mf")
        return Telnet()

    acc.proven.login_root_family = fake_login
    acc.proven.require_supported_model_over_telnet = lambda access, telnet: events.append("model_gate")
    acc.mf_persistent_install.run_stock_acceptance = lambda access: (events.append("mf_installer") or 0)
    acc.acceptance_bootloader_dispatch("192.168.1.1", mf_stock)
finally:
    acc.proven.ask_credentials = old_ask
    acc.proven.login_root_family = old_login
    acc.proven.require_supported_model_over_telnet = old_require
    acc.mf_persistent_install.run_stock_acceptance = old_run

assert events == [
    "ask_credentials",
    "login_root_mf",
    "model_gate",
    "close_telnet",
    "mf_installer",
    "close_web",
], events

print("MF_PERSISTENT_EXPERT_INTEGRATION=PASS")
print("MF_STOCK_ITEM2_BACKEND=" + acc.MF_ACCEPTANCE_BACKEND)
print("MD_EXPERT_POLICY=UNCHANGED")
print("MF_NON_STOCK_WRITES=BLOCKED")
