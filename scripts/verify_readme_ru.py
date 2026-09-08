#!/usr/bin/env python3
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / 'scripts/verify_docs.py')], cwd=ROOT, check=True)
print('README_RU_OPERATIONS_QA=PASS')
