#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ursus_web_client as uw

HOST = "192.168.1.1"
MTD0_SIZE = 0x80000
FIP_OFF = 0x800
ENV_OFF = 0x7C000
EXPECTED_PREFIX_SHA256 = "82830140f4f8842702d0569065c27071b7cc24e0876e6c487cb4d9d81c294dd7"
TB_FW_UUID = bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a")
NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
CHECKSUM_UUID = bytes.fromhex("a2cceab7f8254b279704633a6fd69ad8")
EXPECTED_TB_SHA256 = "07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_backup(path: Path) -> bytes:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as f:
            data = f.read()
    else:
        data = path.read_bytes()
    if len(data) != MTD0_SIZE:
        raise SystemExit(f"mtd0 size mismatch: 0x{len(data):x}, expected 0x{MTD0_SIZE:x}")
    if sha(data[:FIP_OFF]) != EXPECTED_PREFIX_SHA256:
        raise SystemExit("BootROM prefix SHA256 does not match the proven XG140/Nokia prefix")
    env = data[ENV_OFF:MTD0_SIZE]
    stored = struct.unpack_from("<I", env, 0)[0]
    calc = zlib.crc32(env[4:]) & 0xFFFFFFFF
    if stored != calc:
        raise SystemExit(f"stock env CRC mismatch: stored={stored:08x} calc={calc:08x}")
    if data[FIP_OFF:FIP_OFF + 8] != bytes.fromhex("010064aa78563412"):
        raise SystemExit("Airoha FIP header not found at physical 0x800")
    return data


def parse_fip(fip: bytes):
    entries = []
    pos = 16
    declared_end = None
    for _ in range(64):
        if pos + 40 > len(fip):
            raise SystemExit("FIP TOC truncated")
        uuid = fip[pos:pos + 16]
        off, size, flags = struct.unpack_from("<QQQ", fip, pos + 16)
        if uuid == b"\0" * 16:
            declared_end = off
            break
        if off < 0x400 or size == 0 or off + size > len(fip):
            raise SystemExit(f"invalid FIP entry range: off=0x{off:x} size=0x{size:x}")
        entries.append((uuid, off, size, flags))
        pos += 40
    if declared_end is None or declared_end > len(fip):
        raise SystemExit("FIP declared end is invalid")
    return entries, declared_end


def validate_native_donor(boot: bytes) -> tuple[bytes, list]:
    window = boot[FIP_OFF:ENV_OFF]
    entries, end = parse_fip(window)
    donor = window[:end]
    if end >= ENV_OFF - FIP_OFF:
        raise SystemExit(f"native FIP overlaps stock env: end=0x{end:x}")
    tb = [e for e in entries if e[0] == TB_FW_UUID]
    nt = [e for e in entries if e[0] == NT_FW_UUID]
    if len(tb) != 1 or len(nt) != 1:
        raise SystemExit("native XG140 FIP must contain exactly one TB_FW and one NT_FW")
    _, off, size, _ = tb[0]
    got = sha(donor[off:off + size])
    if got != EXPECTED_TB_SHA256:
        raise SystemExit(f"native XG140 TB_FW SHA256 mismatch: {got}")
    return donor, entries


def print_native_toc(entries: list, end: int) -> None:
    print(f"Native XG140 FIP TOC: {len(entries)} entries, declared_end=0x{end:x}")
    for idx, (uuid, off, size, flags) in enumerate(entries):
        role = "TB_FW" if uuid == TB_FW_UUID else "NT_FW" if uuid == NT_FW_UUID else "checksum" if uuid == CHECKSUM_UUID else "native"
        print(f"  [{idx}] {role:8s} uuid={uuid.hex()} off=0x{off:x} size=0x{size:x} flags=0x{flags:x}")


def compare_lineage(old: bytes, new: bytes) -> None:
    old_entries, _ = parse_fip(old)
    new_entries, _ = parse_fip(new)
    om = {u: (o, s, f) for u, o, s, f in old_entries}
    nm = {u: (o, s, f) for u, o, s, f in new_entries}
    if set(om) != set(nm):
        raise SystemExit("repacked FIP entry set differs from native XG140 donor")
    for u, (oo, osz, of) in om.items():
        no, nsz, nf = nm[u]
        if u == NT_FW_UUID:
            if no != oo or nf != of:
                raise SystemExit("NT_FW native offset/flags changed")
            continue
        if (oo, osz, of) != (no, nsz, nf):
            raise SystemExit(f"native FIP metadata changed for UUID {u.hex()}")
        if old[oo:oo + osz] != new[no:no + nsz]:
            raise SystemExit(f"native FIP payload changed for UUID {u.hex()}")


def main() -> int:
    root = HERE.parent
    lzma_path = root / "u-boot.lzma"
    repacker = root / "repack_xg140_native_fip.py"
    if not lzma_path.is_file() or not repacker.is_file():
        raise SystemExit("artifact is incomplete: u-boot.lzma/repack_xg140_native_fip.py missing")

    raw = input("Path to your XG140 mtd0_bootloader.bin or .bin.gz backup: ").strip().strip('"')
    backup_path = Path(raw).expanduser().resolve()
    if not backup_path.is_file():
        raise SystemExit(f"backup not found: {backup_path}")

    boot = read_backup(backup_path)
    donor, entries = validate_native_donor(boot)
    _entries_check, end = parse_fip(donor)
    print(f"Native XG140 mtd0 SHA256: {sha(boot)}")
    print(f"Native XG140 donor FIP: size=0x{len(donor):x} SHA256={sha(donor)}")
    print_native_toc(entries, end)

    with tempfile.TemporaryDirectory(prefix="xg140-native-fip-") as td:
        td = Path(td)
        donor_path = td / "xg140-stock-native.fip"
        output_path = td / "ursusboot-xg140-native-persistent.fip"
        donor_path.write_bytes(donor)
        subprocess.run(
            [sys.executable, str(repacker), str(donor_path), str(lzma_path), str(output_path)],
            check=True,
        )
        new = output_path.read_bytes()
        if len(new) >= ENV_OFF - FIP_OFF:
            raise SystemExit(f"repacked FIP reaches protected env: size=0x{len(new):x}")
        compare_lineage(donor, new)
        print(f"Native-hybrid FIP: size=0x{len(new):x} SHA256={sha(new)}")
        print("Preserved: BootROM prefix, stock env, and every native FIP entry except NT_FW payload/size.")
        print("No foreign checksum entry is synthesized when the native Nokia donor does not contain one.")

        st = uw.status(HOST)
        version = str(st.get("version") or "")
        model = str(st.get("model") or st.get("board") or "")
        print(f"UrsusBoot: version={version!r} model={model!r} layout={st.get('current_layout')!r}")
        if "xg140" not in version.lower() and "140g" not in model.lower():
            raise SystemExit("XG140 UrsusBoot identity not confirmed; nothing written")

        ans = input("Write native-hybrid UrsusBoot to XG140 bootloader area? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("Cancelled before write.")
            return 0

        # The operator already confirmed this exact destructive transaction above.
        # Do not ask a second y/N inside the transport helper.
        final = uw.update_bootloader(HOST, output_path, confirm=False)
        print(f"Completed: stage={final.get('operation_stage')} transaction={final.get('operation_transaction_state')}")
        print("Reboot only after the updater reports successful readback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
