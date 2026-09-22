#!/usr/bin/env python3
"""Pin UrsusBoot's STOCK->UBI preloader acceptance to a specific preloader FIP.

UrsusBoot accepts an uploaded UBI preloader only if its SHA256 equals a
compiled-in digest (ursus_ubi_validate_preloader) and the 128 KiB BL2 candidate
built from it (0x800 x 0xff, preloader at 0x800, 0xff padding) equals a second
compiled-in digest (ursus_ubi_prepare_bl2_candidate / BL2-LAST verify). A new
(fast-scan) BL2 is therefore rejected unless the runtime is rebuilt with the
digests of exactly that preloader. This rewrites both digests (C byte arrays
and log/JSON hex text) and, if present, the pinned preloader size.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import struct
from pathlib import Path

BL2_SIZE = 0x20000
PRELOADER_OFF = 0x800
FIP_TOC_NAME = 0xAA640001
TB_FW_UUID = bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a")

MD = {
    "preloader_sha": "6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808",
    "bl2_sha": "6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d",
    "size": "113447",
}
MF = {
    "preloader_sha": "778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e",
    "bl2_sha": "c655479c4d14b4f6d1a7a5eb8de80bfb204b3cdf46c9e48a5c6f3aea22d98131",
    "size": "118333",
}


def bl2_candidate(preloader: bytes) -> bytes:
    if not preloader or len(preloader) > BL2_SIZE - PRELOADER_OFF:
        raise SystemExit(f"preloader size {len(preloader)} does not fit the 128 KiB BL2 candidate")
    img = b"\xff" * PRELOADER_OFF + preloader
    return img + b"\xff" * (BL2_SIZE - len(img))


def check_fip(preloader: bytes) -> None:
    if len(preloader) < 16 or struct.unpack_from("<I", preloader, 0)[0] != FIP_TOC_NAME:
        raise SystemExit("preloader is not a FIP (UrsusBoot requires the FIP magic)")
    if preloader[16:32] != TB_FW_UUID:
        raise SystemExit("preloader FIP does not start with a TB_FW (BL2) entry")


def pinned_values(preloader: bytes) -> dict[str, str]:
    return {
        "preloader_sha": hashlib.sha256(preloader).hexdigest(),
        "bl2_sha": hashlib.sha256(bl2_candidate(preloader)).hexdigest(),
        "size": str(len(preloader)),
    }


def _byte_pattern(hexstr: str) -> str:
    return r"\s*,\s*".join(re.escape("0x" + hexstr[i:i + 2]) for i in range(0, 64, 2))


def _swap_bytes(new_hex: str):
    """Replace the 32 0xNN tokens of a match in order, keeping its layout."""
    def repl(m: re.Match) -> str:
        it = iter(new_hex[i:i + 2] for i in range(0, 64, 2))
        return re.sub(r"0x[0-9a-fA-F]{2}", lambda _t: "0x" + next(it), m.group(0))
    return repl


def pin(tree: Path, preloader: bytes, old: dict[str, str]) -> dict[str, int]:
    check_fip(preloader)
    new = pinned_values(preloader)
    counts = {"preloader_sha_bytes": 0, "bl2_sha_bytes": 0, "preloader_sha_text": 0, "bl2_sha_text": 0, "size": 0}
    files = sorted((tree / "cmd").glob("ursus*.c")) + sorted((tree / "include").glob("ursus*.h"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        orig = text
        for key in ("preloader_sha", "bl2_sha"):
            text, n = re.subn(_byte_pattern(old[key]), _swap_bytes(new[key]), text, flags=re.I)
            counts[f"{key}_bytes"] += n
            n = text.count(old[key])
            text = text.replace(old[key], new[key])
            counts[f"{key}_text"] += n
        n = len(re.findall(rf"\b{old['size']}\b", text))
        text = re.sub(rf"\b{old['size']}\b", new["size"], text)
        counts["size"] += n
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print(f"UBI_PRELOADER_PIN file={path.relative_to(tree)}")
    for key in ("preloader_sha_bytes", "bl2_sha_bytes"):
        if counts[key] != 1:
            raise SystemExit(f"UBI preloader pin: expected exactly one {key} array, found {counts[key]}")
    print("UBI_PRELOADER_PIN " + " ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"UBI_PRELOADER_SHA256={new['preloader_sha']}")
    print(f"UBI_BL2_IMAGE_SHA256={new['bl2_sha']}")
    print(f"UBI_PRELOADER_SIZE={new['size']}")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, help="patched UrsusBoot U-Boot source tree")
    ap.add_argument("--preloader", required=True, help="preloader FIP to accept")
    ap.add_argument("--from", dest="base", choices=("md", "mf"), required=True,
                    help="digest set currently compiled into the tree")
    args = ap.parse_args()
    pin(Path(args.tree), Path(args.preloader).read_bytes(), MD if args.base == "md" else MF)


if __name__ == "__main__":
    main()
