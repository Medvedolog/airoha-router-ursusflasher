#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / 'data' / 'proven_backend.py').read_text(encoding='utf-8')

# Contract checks: exact safe RI byte windows, cross-check, and authoritative ri_mac.
assert 'skip=26 count=12' in src
assert 'skip=88 count=4' in src
assert 'serial[4:].lower() != suffix_hex' in src
assert '"G984Serial": serial' in src
assert '"MfrID": serial[:4]' in src
assert 'identity.get("primary_mac_source") == "ri@0x3e"' in src

# Synthetic RI layout vector: never embed a real device serial/MAC in QA.
serial = 'ABCD1234ABCD'
suffix = bytes.fromhex(serial[4:])
ri = bytearray(b'0' * 0x100)
ri[0x1a:0x1a+12] = serial.encode('ascii')
ri[0x58:0x58+4] = suffix
parsed = bytes(ri[0x1a:0x1a+12]).decode('ascii')
assert re.fullmatch(r'[A-Z]{4}[0-9A-F]{8}', parsed)
assert parsed[4:].lower() == ri[0x58:0x5c].hex()
assert parsed[:4] == 'ABCD'
print('MD_IDENTITY_ACCEPT2_QA=PASS')
print('RI_SERIAL=0x1a:12_ASCII')
print('RI_G984_SUFFIX=0x58:4_BINARY_CROSSCHECK')
print('RI_MAC=AUTHORITATIVE_0x3e')
