#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, zlib

ROOT = Path(__file__).resolve().parents[1]

# Historical/emergency payloads that are intentionally still committed.
checks = {
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-bl2.bin":
        "6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d",
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-update.fip":
        "597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce",
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip":
        "ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600",
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.bin":
        "43296d98686ada9e4e13c5a5a49430372abf45e9bd0fc8eae837920e8ba5224d",
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.lzma":
        "bec245ab0b10e3fffcc2f0a482c2c3b97b03577b4a03c436857243cd68ff9d29",
    "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip":
        "3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea",
}
for rel, expected in checks.items():
    p = ROOT / rel
    assert p.is_file(), rel
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual == expected, (rel, actual, expected)

# T80 production line is CI-built in airoha-ursusboot and is injected into the
# public kit from these exact immutable artifacts.  Do not require removed
# HWFIX3/UIFIX1 files merely because they once lived in this repository.
pin = json.loads((ROOT / "config/URSUSBOOT_PIN.json").read_text(encoding="utf-8"))
assert pin["repo"] == "Medvedolog/airoha-ursusboot"
assert pin["commit"] == "e27da4f7dac5d93af26b44ae4b0d60acea2aae74"
assert pin["version"] == "0.1.0-alpha5-t80"
assert pin["build_run"] == 37288451919
assert pin["artifacts"]["md"]["update_fip_size"] == 503808
assert pin["artifacts"]["md"]["update_fip_sha256"] == "90716644a2d856542cdab8cf5694f43031c55d8424247fc87cdde130412fdafb"
assert pin["artifacts"]["mf"]["update_fip_size"] == 327027
assert pin["artifacts"]["mf"]["update_fip_sha256"] == "a70d318fece02d7bf24f46dd589dc33ec09c048898a442e5a9686e26f07f432f"

legacy = ROOT / "payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"
assert f"{zlib.crc32(legacy.read_bytes()) & 0xffffffff:08x}" == "c1edda32"
source = ROOT / "ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst"
assert hashlib.sha256(source.read_bytes()).hexdigest() == "57736bb74e2efd198e56e687dba50b945c160ada8ee9a3f25e3534842aa7f8c3"

print("BOOT_CHAIN_IDENTITY_QA=PASS production=T80 historical_emergency_line=retained")
