#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def patch(root: Path) -> None:
    path = root / "cmd/ursusweb.c"
    if not path.is_file():
        raise SystemExit(f"missing Ursus Web source: {path}")

    text = path.read_text(encoding="utf-8")
    marker = "URSUS_MF2_HWTEST5_QUIET_CHUNKS"
    if marker in text:
        raise SystemExit("HWTEST5 quiet-chunk patch already applied")

    pattern = re.compile(
        r'''    if \(URSUS_REQ_MATCH\(c->reqhdr, "POST /api/initramfs-begin "\) \|\|\n'''
        r'''        URSUS_REQ_MATCH\(c->reqhdr, "POST /api/initramfs-chunk "\) \|\|\n'''
        r'''        URSUS_REQ_MATCH\(c->reqhdr, "POST /api/expert/discard "\) \|\|\n'''
        r'''        URSUS_REQ_MATCH\(c->reqhdr, "POST /api/expert/boot-once "\)\) \{\n'''
        r'''        ursus_logf\("URSUS_MF2_RAM_POST_ALLOW route=initramfs_or_boot_once\\n"\);\n'''
        r'''    \} else if \(!strncmp\(c->reqhdr, "POST ", 5\)\) \{'''
    )

    replacement = r'''    /* URSUS_MF2_HWTEST5_QUIET_CHUNKS
     * Keep the RAM-only POST allowlist exactly as MF2 established, but do not
     * append one operation-log line for every 64 KiB initramfs chunk.  Begin,
     * discard and boot-once remain visible; persistent POST routes still hit
     * the unchanged reject gate below.
     */
    if (URSUS_REQ_MATCH(c->reqhdr, "POST /api/initramfs-begin ") ||
        URSUS_REQ_MATCH(c->reqhdr, "POST /api/expert/discard ") ||
        URSUS_REQ_MATCH(c->reqhdr, "POST /api/expert/boot-once ")) {
        ursus_logf("URSUS_MF2_RAM_POST_ALLOW route=initramfs_control\n");
    } else if (URSUS_REQ_MATCH(c->reqhdr, "POST /api/initramfs-chunk ")) {
        /* allowed RAM transport; intentionally no per-chunk log */
    } else if (!strncmp(c->reqhdr, "POST ", 5)) {'''

    out, count = pattern.subn(lambda _m: replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"MF2 selective POST gate match count={count}")

    path.write_text(out, encoding="utf-8")
    verify = path.read_text(encoding="utf-8")
    required = (
        marker,
        'POST /api/initramfs-chunk ',
        'allowed RAM transport; intentionally no per-chunk log',
        'URSUS_MF2_RAM_POST_ALLOW route=initramfs_control',
        'MF2 READONLY: rejected HTTP POST',
    )
    for token in required:
        if token not in verify:
            raise SystemExit(f"HWTEST5 Web quiet marker missing: {token}")

    if 'URSUS_MF2_RAM_POST_ALLOW route=initramfs_or_boot_once' in verify:
        raise SystemExit("legacy per-chunk allow log survived HWTEST5 patch")

    print("MF2_HWTEST5_WEB_QUIET=PASS chunks=allowed_unlogged persistent_post=unchanged_reject")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
