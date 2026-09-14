#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "ursusboot" / "configs"
POLICY = ROOT / "ursusboot" / "board-policies"
REGISTRY = CFG / "board-profiles.json"

ASSIGN_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=")
UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")


def symbols(path: Path) -> set[str]:
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = ASSIGN_RE.match(line) or UNSET_RE.match(line)
        if m:
            out.add(m.group(1))
    return out


def fail(msg: str) -> None:
    raise SystemExit("URSUS_PROFILE_SELFTEST_FAIL: " + msg)


data = json.loads(REGISTRY.read_text(encoding="utf-8"))
if data.get("schema") != 1:
    fail("unsupported registry schema")
profiles = data.get("profiles")
if not isinstance(profiles, dict) or not profiles:
    fail("profiles missing")

required = {"xg040-md", "xg040-mf", "xg140-md"}
if not required.issubset(profiles):
    fail("missing baseline profiles: " + ",".join(sorted(required - set(profiles))))

for name, profile in profiles.items():
    fragments = profile.get("fragments")
    if not isinstance(fragments, list) or len(fragments) < 3:
        fail(f"{name}: invalid fragment composition")
    seen: set[str] = set()
    for frag in fragments:
        if frag in seen:
            fail(f"{name}: duplicate fragment {frag}")
        seen.add(frag)
        path = CFG / frag
        if not path.is_file():
            fail(f"{name}: missing fragment {frag}")

    if fragments[0] != "ursusboot-common.cfg":
        fail(f"{name}: common fragment must be first")

    policy_name = profile.get("board_policy_header")
    if not isinstance(policy_name, str) or not policy_name.endswith(".h"):
        fail(f"{name}: board_policy_header missing")
    policy_path = POLICY / policy_name
    if not policy_path.is_file():
        fail(f"{name}: board policy header missing: {policy_name}")
    pdata = policy_path.read_text(encoding="utf-8")
    for marker in (
        f'#define URSUS_BOARD_POLICY_ID              "{name}"',
        "URSUS_BOARD_STOCK_MASTER_BASE",
        "URSUS_BOARD_STOCK_SLAVE_BASE",
        "URSUS_BOARD_STOCK_ENV_BASE",
        "URSUS_BOARD_STOCK_HDR_MAGIC",
        "URSUS_BOARD_APPEND_SERDES_ARGS",
        "URSUS_BOARD_ALLOW_UBI_BOOT",
        "URSUS_BOARD_ALLOW_FACTORY_FIT",
    ):
        if marker not in pdata:
            fail(f"{name}: policy marker missing: {marker}")

md = profiles["xg040-md"]
mf = profiles["xg040-mf"]
xg = profiles["xg140-md"]
if md["soc"] != "an7581" or xg["soc"] != "an7581":
    fail("MD and XG140 must share AN7581 SoC layer")
if mf["soc"] != "an7583":
    fail("MF must use AN7583 SoC layer")
if xg.get("derivation") != "md-derived":
    fail("XG140 must be explicitly MD-derived")
if xg.get("environment_policy") != "vendor-env-preserved":
    fail("XG140 must preserve vendor env")

for board_file in ("ursusboot-board-md.cfg", "ursusboot-board-mf.cfg", "ursusboot-board-xg140.cfg"):
    syms = symbols(CFG / board_file)
    forbidden = {s for s in syms if s.startswith("CONFIG_TARGET_") or s.startswith("CONFIG_PCS_") or s.startswith("CONFIG_PINCTRL_") or s.startswith("CONFIG_ENV_")}
    if forbidden:
        fail(f"{board_file}: board layer leaks SoC/storage symbols: {sorted(forbidden)}")

for soc_file in ("ursusboot-soc-an7581.cfg", "ursusboot-soc-an7583.cfg"):
    syms = symbols(CFG / soc_file)
    forbidden = {s for s in syms if s.startswith("CONFIG_DEFAULT_DEVICE_TREE") or s.startswith("CONFIG_DEFAULT_FDT_FILE") or s.startswith("CONFIG_ENV_")}
    if forbidden:
        fail(f"{soc_file}: SoC layer leaks board/storage symbols: {sorted(forbidden)}")

nowhere = (CFG / "ursusboot-storage-env-nowhere.cfg").read_text(encoding="utf-8")
if "CONFIG_ENV_IS_NOWHERE=y" not in nowhere or "CONFIG_ENV_IS_IN_UBI=y" in nowhere:
    fail("ENV_NOWHERE storage policy invalid")
ubi = (CFG / "ursusboot-storage-ubi-redundant.cfg").read_text(encoding="utf-8")
if "CONFIG_ENV_IS_IN_UBI=y" not in ubi or "CONFIG_ENV_REDUNDANT=y" not in ubi:
    fail("UBI redundant storage policy invalid")

xgp = (POLICY / xg["board_policy_header"]).read_text(encoding="utf-8")
if "#define URSUS_BOARD_ALLOW_UBI_BOOT          0" not in xgp:
    fail("XG140 must not inherit MD UBI boot detection implicitly")
if "#define URSUS_BOARD_APPEND_SERDES_ARGS(dst, cap) 0" not in xgp:
    fail("XG140 must not inherit unproven MD SerDes overrides")

print("URSUS_PROFILE_SELFTEST=PASS")
for name in sorted(profiles):
    p = profiles[name]
    print(f"PROFILE {name}: soc={p['soc']} derivation={p['derivation']} env={p['environment_policy']} policy={p['board_policy_header']} fragments={','.join(p['fragments'])}")
