#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import mf_runtime_install as mri


class Access:
    def __init__(self, family: str = "unknown") -> None:
        self.family = family
        self.model_name = ""
        self.chipset = ""
        self.model_verified = False
        self.model_verification_source = ""
        self.closed = False

    def close_web(self, announce: bool = False) -> None:
        self.closed = True


# Interactive MF stock install must use the existing family-aware proven
# backend, not the historical generic MD-only ask_credentials model gate.
old_install_access = mri.pb._install_access
try:
    seen = []
    good = Access("mf")

    def fake_install_access(profile):
        seen.append(profile)
        return good

    mri.pb._install_access = fake_install_access
    assert mri._open_stock_access_interactive() is good
    assert seen == [mri.pb.MF_INSTALL_PROFILE]

    bad = Access("md")
    mri.pb._install_access = lambda profile: bad
    try:
        mri._open_stock_access_interactive()
        raise AssertionError("non-MF access was accepted")
    except RuntimeError as exc:
        assert "positively identified MF stock" in str(exc)
    assert bad.closed is True
finally:
    mri.pb._install_access = old_install_access


# The unattended compatibility bridge may widen the legacy stock_web list only
# after BOARD_PROFILES positively identifies MF. It must restore the module
# constant immediately and carry the proven family into StockAccess.
class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host

    def login(self, user: str, password: str, allow_plain: bool = False) -> None:
        return None

    def logout(self) -> None:
        return None


class FakeSetup:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def read_device_info(self):
        return {"model": "XG-040G-MF", "chipset": "AN7583DT"}


fake_module = SimpleNamespace(
    DEFAULT_WEB_USER="CMCCAdmin",
    DEFAULT_WEB_PASSWORD="secret",
    SUPPORTED_INSTALL_MODELS=("XG-040G-MD",),
    StockWeb=FakeClient,
    StockSetup=FakeSetup,
    LoginError=RuntimeError,
)

old_load = mri.pb._load_stock_web_module
old_auto = mri.pb._automatic_stock_web_access
old_match = mri.bp.match_profile
old_profile = dict(mri.pb._STARTUP_DEVICE_PROFILE)
old_auth = dict(mri.pb._STARTUP_WEB_AUTH)
try:
    mri.pb._load_stock_web_module = lambda: fake_module
    mri.bp.match_profile = lambda model="", soc="", board="": ("mf", {"model": "Nokia XG-040G-MF", "soc": "Airoha AN7583"})
    auto_seen = []

    def fake_auto(host, module, offer_interactive_plain_retry=False):
        assert host == "192.168.1.1"
        assert module is fake_module
        assert "XG-040G-MF" in module.SUPPORTED_INSTALL_MODELS
        auto_seen.append(tuple(module.SUPPORTED_INSTALL_MODELS))
        return Access()

    mri.pb._automatic_stock_web_access = fake_auto
    access = mri._open_stock_access_auto("192.168.1.1")
    assert auto_seen
    assert fake_module.SUPPORTED_INSTALL_MODELS == ("XG-040G-MD",)
    assert access.family == "mf"
    assert access.model_name == "XG-040G-MF"
    assert access.chipset == "AN7583DT"
    assert access.model_verified is True
    assert access.model_verification_source == "mf-runtime-stock-web-board-profile"
finally:
    mri.pb._load_stock_web_module = old_load
    mri.pb._automatic_stock_web_access = old_auto
    mri.bp.match_profile = old_match
    mri.pb._STARTUP_DEVICE_PROFILE.clear(); mri.pb._STARTUP_DEVICE_PROFILE.update(old_profile)
    mri.pb._STARTUP_WEB_AUTH.clear(); mri.pb._STARTUP_WEB_AUTH.update(old_auth)

print("MF_STOCK_INTERACTIVE_ACCESS=PROVEN_FAMILY_AWARE")
print("MF_STOCK_UNATTENDED_GATE=SCOPED_COMPAT_BRIDGE")
print("MF_STOCK_ACCESS_SELFTEST=PASS")
