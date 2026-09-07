#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(DATA))

import expert
import one_key

sample = RuntimeError("SSH-команда завершилась с кодом 127\nПоследний вывод SSH:\nash: line 0: base64: not found")
assert expert._operator_error_cause(sample) == "ash: line 0: base64: not found"
assert one_key._operator_error_cause(sample) == "ash: line 0: base64: not found"

install = (DATA / "ursusboot_install.py").read_text(encoding="utf-8")
backend = (DATA / "proven_backend.py").read_text(encoding="utf-8")
assert "f\"({command}) | base64\"" not in install
assert "pb.ssh_read_binary(host, command" in install
assert "def ssh_read_binary(host: str, command: str" in backend
assert "stdout=subprocess.PIPE, stderr=subprocess.PIPE" in backend
assert "text=True" not in backend[backend.index("def ssh_read_binary"):backend.index("def scp_executable")]
print("ERRORUI1_SSHBIN1_QA=PASS")
