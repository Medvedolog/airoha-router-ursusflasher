#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import expert


class UnsupportedModel(RuntimeError):
    pass


class FakeClient:
    def __init__(self, host: str):
        self.host = host
        self.logged_out = False

    def login(self, *_args, **_kwargs):
        return None

    def logout(self):
        self.logged_out = True


class FakeSetup:
    def __init__(self, client):
        self.client = client

    def read_device_info(self):
        return {"model": "XG-040G-MF", "chipset": "AN7583"}

    def read_credentials(self):
        return {
            "telnet_enabled": True,
            "telnet_user": "admin",
            "telnet_password": "secret",
            "telnet_port": 23,
            "ftp_enabled": False,
            "ftp_user": "ftp",
            "ftp_password": "ftpsecret",
            "ftp_port": 21,
        }


class FakeAccess:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def close_web(self, announce=False):
        if self.web_client:
            self.web_client.logout()


def main() -> int:
    fake_stock = types.SimpleNamespace(
        DEFAULT_WEB_USER="CMCCAdmin",
        DEFAULT_WEB_PASSWORD="dummy",
        StockWeb=FakeClient,
        StockSetup=FakeSetup,
        UnsupportedModel=UnsupportedModel,
    )
    captured_secrets = []
    fake_proven = types.SimpleNamespace(
        StockAccess=FakeAccess,
        _register_log_secret=captured_secrets.append,
    )

    old_stock = expert.stock_web
    old_proven = expert.proven
    old_tcp = expert._tcp_open
    try:
        expert.stock_web = fake_stock
        expert.proven = fake_proven
        expert._tcp_open = lambda *_args, **_kwargs: True

        access = expert._readonly_stock_access("192.168.1.1", expected_family="mf")
        assert access.family == "mf"
        assert access.model_name == "Nokia XG-040G-MF"
        assert access.chipset == "Airoha AN7583"
        assert access.model_verified is True
        assert access.model_verification_source.endswith("board-profile")
        assert captured_secrets

        try:
            expert._readonly_stock_access("192.168.1.1", expected_family="md")
        except UnsupportedModel:
            pass
        else:
            raise AssertionError("MF stock identity must not satisfy an MD preflight")
    finally:
        expert.stock_web = old_stock
        expert.proven = old_proven
        expert._tcp_open = old_tcp

    print("PASS: MF1 stock read-only access reuses board profile and cross-family gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
