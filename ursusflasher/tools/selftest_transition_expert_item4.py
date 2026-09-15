#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
expert = (ROOT / "ursusflasher" / "src" / "expert.py").read_text(encoding="utf-8")
transition = (ROOT / "ursusflasher" / "src" / "stock_ab_transition.py").read_text(encoding="utf-8")
fit = (ROOT / "ursusflasher" / "src" / "stock_fit_wrapper.py").read_text(encoding="utf-8")

boundary = "# ---------------- destructive boundary ----------------"
prompt = 'Preflight passed. Write TRANSITION to nsb_slave and activate SLAVE? [y/N]: '

# EXPERT item 4 is the production entrypoint; the old item-2 redirect is gone.
assert "import stock_ab_transition" in expert
assert "Stock Nokia → Vanilla OpenWrt (TRANSITION)" in expert
assert "stock_ab_transition.run_expert(host=host, profile=profile)" in expert
assert "number = 2" not in expert.split("if number == 4:", 1)[1].split("selected = app[number]", 1)[0]
assert "Reset не менее 30 секунд" in expert

# Full stock backup uses the proven all-MTD backend and is verified before write.
assert "pb.backup_tftp(" in transition
assert "pb.verify_stock_restore_backup(full_backup)" in transition
assert transition.index("pb.backup_tftp(") < transition.index(boundary)

# The old reduced four-partition transfer is gone. Staging inputs are read from
# the already verified all-MTD backup, so there is no hidden TFTP-only download.
assert "_backup_partition_bytes(" in transition
assert "receive_remote_file(" not in transition
assert "def _capture(" not in transition

# Transport selection/preflight happens before the single destructive y/N.
assert "pb.send_file_to_router(" in transition
assert "pb.send_file_to_router_tftp(" in transition
assert "_select_and_preflight_transport" in transition
assert "transport and writer are frozen" in transition
assert prompt in transition
run_part = transition.split("def run(", 1)[1]
assert run_part.index("_select_and_preflight_transport(") < run_part.index(prompt)
assert run_part.index(prompt) < run_part.index(boundary)
# No transfer call is allowed after the write boundary.
after_boundary = run_part.split(boundary, 1)[1]
assert "send_file_to_router(" not in after_boundary
assert "send_file_to_router_tftp(" not in after_boundary

# EXPERT uses the common UrsusFlasher session logger; the standalone transcript
# remains developer/HW-test-only.
assert "own_transcript=False" in transition

# Board policy is explicit. MF must never silently inherit MD offsets.
assert "class TransitionPolicy" in transition
assert 'profile="xg040-md"' in transition
assert 'profile == "xg040-mf"' in transition
assert "refusing to copy MD MTD indices/offsets/HDR assumptions" in transition

# Structural FIT validation remains; known stock compression variants are not fingerprints.
assert "compression" in fit
assert "lzma" in fit
assert "none" in fit

print("selftest_transition_expert_item4: PASS")
