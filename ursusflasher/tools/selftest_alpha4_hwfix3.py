#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1]
data = D / "data"

# The alpha4 HWFIX3 A/B harness was a historical engineering experiment and is
# intentionally absent from current operator/runtime packages.
assert not (data / "alpha4_hwfix_test.py").exists()

expert = (data / "expert.py").read_text(encoding="utf-8")
for forbidden in (
    "alpha4_ab_install",
    "alpha4_ab_rollback",
    "alpha4_hwfix_test.install_hwfix3",
    "alpha4_hwfix_test.rollback_hwfix3",
):
    assert forbidden not in expert, forbidden

terms = json.loads((data / "UI_TERMS.json").read_text(encoding="utf-8"))
assert "alpha4_ab_install" not in terms["expert_actions"]
assert "alpha4_ab_rollback" not in terms["expert_actions"]

manifest = json.loads((data / "MANIFEST.json").read_text(encoding="utf-8"))
assert manifest["version"] == (D / "VERSION").read_text(encoding="utf-8").strip()
assert manifest["version"] == "0.2.80-dev"
assert manifest["ursusboot"]["version"] == "0.1.0-alpha5-t80"

# Current production and emergency lines stay separate; no alpha4 candidate is
# allowed to become a production target again.
update = (data / "ursusboot_update.py").read_text(encoding="utf-8")
assert "0.1.0-alpha5-t80" in update
assert "ursusboot-md-0.1.0-alpha3-update.fip" in update
assert "alpha4-HWFIX3" not in update

print("ALPHA4_HWFIX3_RETIRED_QA=PASS")
print("PRODUCTION=T80 EMERGENCY=ALPHA3")
