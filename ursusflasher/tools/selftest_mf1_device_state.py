#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import device_state as ds


class _FakeStockClient:
    def __init__(self, host: str):
        self.host = host

    def login(self, *_args, **_kwargs):
        return None

    def logout(self):
        return None


class _FakeStockSetupMF:
    def __init__(self, _client):
        pass

    def read_device_info(self):
        return {
            "model": "XG-040G-MF",
            "chipset": "AN7583",
            "hardware": "test",
            "software": "test",
        }


class _FakeStockSetupMismatch:
    def __init__(self, _client):
        pass

    def read_device_info(self):
        return {
            "model": "XG-040G-MF",
            "chipset": "AN7581",
            "hardware": "test",
            "software": "test",
        }


def _install_fake_stock(setup_cls) -> None:
    sys.modules["stock_web"] = types.SimpleNamespace(
        DEFAULT_WEB_USER="CMCCAdmin",
        DEFAULT_WEB_PASSWORD="dummy",
        StockWeb=_FakeStockClient,
        StockSetup=setup_cls,
    )


def test_stock_mf_identity() -> None:
    _install_fake_stock(_FakeStockSetupMF)
    st = ds.DeviceState(probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_stock_web("192.168.1.1", st)
    assert st.probe_status == ds.PROBE_COMPLETE
    assert st.model == "Nokia XG-040G-MF"
    assert st.soc == "Airoha AN7583"
    assert st.evidence["board_profile"] == "mf"

    _install_fake_stock(_FakeStockSetupMismatch)
    bad = ds.DeviceState(probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_stock_web("192.168.1.1", bad)
    assert bad.probe_status == ds.PROBE_PARTIAL
    assert "STOCK_MODEL_SOC_MISMATCH" in bad.probe_reasons


def test_openwrt_mf_identity_and_layout() -> None:
    output = "\n".join([
        "__URSUS_STATE__",
        "BOARD=airoha,nokia-xg-040g-mf",
        "MODEL=Nokia XG-040G-MF",
        "MACHINE=Nokia XG-040G-MF",
        'MTD=mtd0: 00020000 00020000 "bl2";mtd1: 0ffe0000 00020000 "ubi";',
        "FIPVOL=fip",
        "ROOTMOUNT=overlayfs:/overlay|overlay|rw,relatime",
        "ROMMOUNT=/dev/ubiblock0_5|squashfs|ro,relatime",
        "OVERLAYMOUNT=ubi0:rootfs_data|ubifs|rw,relatime",
        "RELEASE=SNAPSHOT/test",
    ])
    sys.modules["proven_backend"] = types.SimpleNamespace(
        ssh_run=lambda *_args, **_kwargs: (0, output)
    )
    st = ds.DeviceState(probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_openwrt_ssh("192.168.1.1", st)
    assert st.probe_status == ds.PROBE_COMPLETE
    assert st.model == "Nokia XG-040G-MF"
    assert st.soc == "Airoha AN7583"
    assert st.current_system == "OPENWRT_UBI"
    assert st.current_layout == "OPENWRT_UBI"
    assert st.execution_environment == ds.EXEC_PERSISTENT_ROOT
    assert st.bootloader == "URSUSBOOT"


def test_ursus_mf_identity() -> None:
    sys.modules["ursus_web_client"] = types.SimpleNamespace(
        status=lambda _host: {
            "board": "nokia-xg-040g-mf",
            "soc": "AN7583",
            "current_layout": "OPENWRT_UBI",
            "version": "0.1.0-mf-test",
            "nand_size": 0x10000000,
            "erase_size": 0x20000,
        }
    )
    st = ds.DeviceState(probe_status=ds.PROBE_COMPLETE)
    assert ds._probe_ursus("192.168.1.1", st)
    assert st.model == "Nokia XG-040G-MF"
    assert st.soc == "Airoha AN7583"
    assert st.evidence["board_profile"] == "mf"
    assert st.nand_capacity == 0x10000000
    assert st.nand_erase_size == 0x20000


def test_mf_write_gate() -> None:
    mf = ds.DeviceState(
        probe_status=ds.PROBE_COMPLETE,
        model="Nokia XG-040G-MF",
        soc="Airoha AN7583",
        current_system="NOKIA_STOCK",
        current_layout="NOKIA_STOCK",
    )
    actions = ds.action_applicability(mf)
    write_actions = [item for item in actions.values() if item.write_capable]
    assert write_actions
    assert all(not item.enabled for item in write_actions)
    assert actions[1].resolved_backend == "DISABLED_READ_ONLY_BRINGUP"
    assert actions[2].resolved_backend == "DISABLED_READ_ONLY_BRINGUP"
    assert actions[7].enabled
    assert actions[7].resolved_backend == "STOCK_READONLY_TFTP_OR_BOOTROM"
    assert actions[8].enabled

    md = ds.DeviceState(
        probe_status=ds.PROBE_COMPLETE,
        model="Nokia XG-040G-MD",
        soc="Airoha AN7581",
        current_system="NOKIA_STOCK",
        current_layout="NOKIA_STOCK",
    )
    md_actions = ds.action_applicability(md)
    assert md_actions[2].enabled
    assert md_actions[2].resolved_backend == "TELNET_NOKIA_STOCK"


def main() -> int:
    test_stock_mf_identity()
    test_openwrt_mf_identity_and_layout()
    test_ursus_mf_identity()
    test_mf_write_gate()
    print("PASS: MF1 device-state identity, UBI classification and persistent-write gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
