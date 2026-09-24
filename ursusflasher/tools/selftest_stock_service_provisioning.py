#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import mf_runtime_install as mri
import proven_backend as pb
import ursusboot_install as ui
import expert


def source_contract() -> None:
    mf = inspect.getsource(mri.install_from_stock)
    md = inspect.getsource(ui.run_install)
    backup = inspect.getsource(pb.backup_tftp)
    readonly = inspect.getsource(expert.backup_stock_readonly)

    assert 'expected_family="mf", allow_service_provisioning=True' in mf
    assert 'expected_family="md", allow_service_provisioning=True' in md
    assert "allow_service_provisioning=allow_service_provisioning" in backup
    assert "allow_service_provisioning=True" not in backup
    assert "allow_service_provisioning=False" in readonly


class FakeTelnet:
    def __init__(self) -> None:
        self.uid = 1001

    def close(self) -> None:
        pass


class FakeSetup:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    def enable_ftp(self) -> str:
        self.state["ftp"] = True
        self.state["enabled"].append("FTP")
        return "enabled"

    def enable_samba(self) -> str:
        self.state["samba"] = True
        self.state["enabled"].append("Samba")
        return "enabled"

    def read_credentials(self) -> dict[str, object]:
        return {
            "ftp_user": "user_ftp",
            "ftp_password": "ftp-pass" if self.state["ftp"] else "",
            "ftp_port": 21,
            "ftp_enabled": bool(self.state["ftp"]),
        }


class FakeAccess:
    def __init__(self, state: dict[str, object]) -> None:
        self.host = "192.0.2.1"
        self.telnet_port = 23
        self.user = "admin"
        self.password = "web-pass"
        self.su_user = ""
        self.su_password = ""
        self.ftp_user = ""
        self.ftp_password = ""
        self.ftp_port = 21
        self.ftp_enabled = False
        self.web_client = object()
        self.web_setup = FakeSetup(state)


def exercise_family(family: str, allow: bool) -> list[str]:
    state: dict[str, object] = {"ftp": False, "samba": False, "enabled": []}
    access = FakeAccess(state)

    originals = (
        pb._telnet_open_logged_in,
        pb._telnet_probe_uid,
        pb._read_uid0_accounts,
        pb._telnet_su_root,
        pb.time.sleep,
    )
    try:
        pb._telnet_open_logged_in = lambda *args, **kwargs: FakeTelnet()
        pb._telnet_probe_uid = lambda telnet: telnet.uid
        pb._read_uid0_accounts = lambda telnet: (
            ["root", "user_ftp"] if state["ftp"] else ["root"]
        )

        def fake_su(telnet, account, secret, attempts=1):
            if account == "user_ftp" and state["ftp"] and secret == "ftp-pass":
                telnet.uid = 0

        pb._telnet_su_root = fake_su
        pb.time.sleep = lambda _seconds: None

        if allow:
            telnet = pb.login_root_family(
                access, family, sessions=3, allow_service_provisioning=True
            )
            assert pb._telnet_probe_uid(telnet) == 0
            assert access.su_user == "user_ftp"
        else:
            try:
                pb.login_root_family(
                    access, family, sessions=2, allow_service_provisioning=False
                )
            except pb.Error:
                pass
            else:
                raise AssertionError("read-only root discovery unexpectedly succeeded")
    finally:
        (
            pb._telnet_open_logged_in,
            pb._telnet_probe_uid,
            pb._read_uid0_accounts,
            pb._telnet_su_root,
            pb.time.sleep,
        ) = originals

    return list(state["enabled"])


source_contract()
for fam in ("md", "mf"):
    assert exercise_family(fam, True) == ["FTP"], fam
    assert exercise_family(fam, False) == [], fam

print("STOCK_SERVICE_PROVISIONING=PASS")
print("INSTALL_MD_FTP_AUTO_ENABLE=PASS")
print("INSTALL_MF_FTP_AUTO_ENABLE=PASS")
print("READONLY_BACKUP_SERVICE_PROVISIONING=BLOCKED")
