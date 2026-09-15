#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("NOKIA_LANG", "en")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import device_state as ds  # noqa: E402
import expert_airoha as launcher  # noqa: E402


def test_launcher_chain_source() -> None:
    cmd = (ROOT / "START_EXPERT.cmd").read_text(encoding="utf-8")
    sh = (ROOT / "START_EXPERT.sh").read_text(encoding="utf-8")
    airoha = (SRC / "expert_airoha.py").read_text(encoding="utf-8")
    multi = (SRC / "expert_multi.py").read_text(encoding="utf-8")

    assert "expert_airoha.py" in cmd
    assert "expert_airoha.py" in sh
    assert "import expert_multi as base" in airoha
    assert "return base.main()" in airoha
    assert "import stock_ab_transition" in multi
    assert "stock_ab_transition.run_expert(host=host, profile=profile)" in multi
    assert "elif number == 9:" in multi
    assert "_run_factory_bootarea_restore(state)" in multi


def test_shipped_item4_dispatch_behavior() -> None:
    em = launcher.base
    host = "192.0.2.1"
    state = ds.DeviceState(
        host=host,
        probe_status=ds.PROBE_COMPLETE,
        model="Nokia XG-040G-MD",
        soc="Airoha AN7581",
        current_system="NOKIA_STOCK",
        current_layout="NOKIA_STOCK",
        bootloader="STOCK_TCBOOT",
        evidence={"board_profile": "md"},
    )
    events: list[tuple] = []
    old: list[tuple[object, str, object]] = []
    old_host = os.environ.get("NOKIA_ROUTER_IP")

    def patch(obj: object, name: str, value: object) -> None:
        old.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    choices = iter(("4", "0"))
    try:
        os.environ["NOKIA_ROUTER_IP"] = host
        patch(em.ds, "probe_device_state", lambda _host: state)
        patch(em.base.proven, "start_session_logging", lambda: None)
        patch(em.base.ui, "enable", lambda: None)
        patch(em.base.one_key, "choose_language", lambda: None)
        patch(em.base.ui, "package_version", lambda _root: "test")
        patch(em.base.ui, "banner", lambda *args, **kwargs: None)
        patch(em.base.ui, "section", lambda *args, **kwargs: None)
        patch(em.base.ui, "menu_item", lambda *args, **kwargs: None)
        patch(em.base.ui, "note", lambda *args, **kwargs: None)
        patch(em.base.ui, "rule", lambda *args, **kwargs: None)
        patch(em.base.ui, "status", lambda *args, **kwargs: None)
        patch(em.base.ui, "prompt", lambda _text: "")
        patch(em.base.network_guidance, "show", lambda: None)
        patch(em, "_show_action", lambda *args, **kwargs: None)
        patch(em.base, "_show_transition_action", lambda _state: None)
        patch(em.base, "ask_menu", lambda _max: next(choices))
        patch(
            em.stock_ab_transition,
            "run_expert",
            lambda *, host, profile: (events.append(("transition", host, profile)) or 0),
        )
        patch(em.base, "run_action", lambda fn, **kwargs: fn())

        rc = launcher.main()
        assert rc == 0
        assert events == [("transition", host, "xg040-md")]
    finally:
        if old_host is None:
            os.environ.pop("NOKIA_ROUTER_IP", None)
        else:
            os.environ["NOKIA_ROUTER_IP"] = old_host
        for obj, name, value in reversed(old):
            setattr(obj, name, value)


test_launcher_chain_source()
test_shipped_item4_dispatch_behavior()
print("selftest_expert_launcher_item4: PASS")
