#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_func(text: str, name: str, new: str) -> str:
    needles = (f"static int {name}(", f"int {name}(")
    starts = [text.find(n) for n in needles if text.find(n) >= 0]
    if not starts:
        raise SystemExit(f"function not found: {name}")
    start = min(starts)
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"function brace not found: {name}")
    depth = 0
    end = None
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f"function end not found: {name}")
    return text[:start] + new.rstrip() + text[end:]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one match, got {n}")
    return text.replace(old, new, 1)


# MF donor FIPs are valid TF-A FIP containers but may place the first payload
# immediately after the actual TOC (for BL31+BL33 this is 0x88), while the MD
# implementation historically required an arbitrary 0x400 payload floor.
# Keep the MD structural model, but derive the real TOC end from the terminator.
# This accepts both compact MF FIPs and padded MD/stock FIPs without a build hash
# or file-size whitelist, while still rejecting payloads that overlap the TOC.
FIP_PARSE = r'''static int ursus_fip_parse(const u8 *buf, size_t len, size_t *nt_off,
                           size_t *nt_size, size_t *declared_end)
{
    const struct ursus_fip_header *hdr;
    const struct ursus_fip_entry *ent;
    unsigned int i, j;
    bool nt = false, term = false;
    size_t noff = 0, nsize = 0, dend = 0, toc_end = 0;

    if (!buf || len < sizeof(*hdr) + 2 * sizeof(*ent))
        return -EINVAL;
    hdr = (const struct ursus_fip_header *)buf;
    if (le32_to_cpu(hdr->name) != URSUS_FIP_MAGIC ||
        le32_to_cpu(hdr->serial_number) != URSUS_FIP_SERIAL)
        return -EINVAL;

    ent = (const void *)(buf + sizeof(*hdr));
    for (i = 0; i < URSUS_FIP_MAX_ENTRIES; i++, ent++) {
        u64 off, size;

        if ((const u8 *)(ent + 1) > buf + len)
            return -EINVAL;
        off = le64_to_cpu(ent->offset_address);
        size = le64_to_cpu(ent->size);
        if (ursus_uuid_zero(ent->uuid)) {
            if (size || off > len)
                return -EINVAL;
            term = true;
            dend = (size_t)off;
            toc_end = (size_t)((const u8 *)(ent + 1) - buf);
            if (dend < toc_end)
                return -EINVAL;
            break;
        }
        if (!size || off > len || size > len - off)
            return -ERANGE;
        if (!memcmp(ent->uuid, ursus_nt_fw_uuid, sizeof(ursus_nt_fw_uuid))) {
            nt = true;
            noff = (size_t)off;
            nsize = (size_t)size;
        }
    }
    if (!nt || !term)
        return -EINVAL;

    /* Second pass: every payload must start after the actual complete TOC and
     * must end no later than the terminator-declared FIP end. */
    ent = (const void *)(buf + sizeof(*hdr));
    for (j = 0; j < i; j++, ent++) {
        u64 off = le64_to_cpu(ent->offset_address);
        u64 size = le64_to_cpu(ent->size);

        if (off < toc_end || off > dend || size > dend - off)
            return -ERANGE;
    }

    if (nt_off)
        *nt_off = noff;
    if (nt_size)
        *nt_size = nsize;
    if (declared_end)
        *declared_end = dend;
    printf("URSUS_MF3_FIP_PARSE_OK toc_end=0x%x declared_end=0x%x nt_off=0x%x nt_size=0x%x\n",
           (unsigned int)toc_end, (unsigned int)dend,
           (unsigned int)noff, (unsigned int)nsize);
    return 0;
}'''


VALIDATE_CURRENT = r'''static int ursus_fip_validate_current(const u8 *buf, size_t available_len, size_t *declared_end)
{
    size_t nt_off, nt_size, end;
    const u8 *nt;
    u64 raw64 = 0;
    SizeT raw_cap, compressed_len;
    u8 *raw;
    int ret;
    unsigned int i;
    bool ursus_id, stock_id;

    ret = ursus_fip_parse(buf, available_len, &nt_off, &nt_size, &end);
    if (ret)
        return ret;
    if (!end || end > available_len || nt_size < 13 || nt_off + nt_size > end)
        return -EINVAL;
    nt = buf + nt_off;
    for (i = 0; i < 8; i++)
        raw64 |= (u64)nt[5 + i] << (i * 8);
    if (raw64 < 0x10000 || raw64 > URSUS_FIP_RAW_MAX)
        return -EFBIG;
    raw_cap = (SizeT)raw64;
    raw = malloc(raw_cap);
    if (!raw)
        return -ENOMEM;
    compressed_len = nt_size;
    ret = lzmaBuffToBuffDecompress(raw, &raw_cap, nt, compressed_len);
    if (ret != SZ_OK || raw_cap != raw64) {
        free(raw);
        return -EBADMSG;
    }

    /* Same validator model as production MD: classify only after the NT FW
     * entry has been structurally parsed and LZMA-decompressed. Never scan
     * the compressed FIP blob for board strings. */
    ursus_id = ursus_mem_has(raw, raw_cap, "U-Boot 2026.07-UrsusBoot-") &&
               ursus_mem_has(raw, raw_cap, "nokia,xg-040g-mf") &&
               ursus_mem_has(raw, raw_cap, "airoha,an7583");
    stock_id = ursus_mem_has(raw, raw_cap, "AN7583DT") &&
               ursus_mem_has(raw, raw_cap, "XG040GMF");
    free(raw);

    if (!ursus_id && !stock_id) {
        printf("URSUS_UPDATE_CURRENT_FIP_REJECT reason=device-mismatch board=nokia_xg-040g-mf soc=an7583\n");
        return -ENODEV;
    }
    if (declared_end)
        *declared_end = end;
    printf("URSUS_UPDATE_CURRENT_FIP_OK identity=%s bytes=0x%x\n",
           ursus_id ? "URSUSBOOT_MF" : "NOKIA_XG040GMF_STOCK",
           (unsigned int)end);
    return 0;
}'''


VALIDATE_BUF = r'''static int ursus_fip_validate_buf(const u8 *buf, size_t len, bool stock_limit,
                                  u8 digest[SHA256_SUM_LEN])
{
    size_t nt_off, nt_size, declared_end;
    const u8 *nt;
    u64 raw64 = 0;
    SizeT raw_cap, compressed_len;
    u8 *raw;
    int ret;
    unsigned int i;
    bool ursus_id, stock_id;

    if (!len || len > URSUS_UBI_FIP_VOL_SIZE)
        return -EFBIG;
    if (stock_limit && len >= URSUS_STOCK_FIP_MAX)
        return -EFBIG;
    ret = ursus_fip_parse(buf, len, &nt_off, &nt_size, &declared_end);
    if (ret)
        return ret;
    if (declared_end != len)
        return -EINVAL;
    if (nt_size < 13 || nt_off + nt_size > len)
        return -EINVAL;
    nt = buf + nt_off;
    for (i = 0; i < 8; i++)
        raw64 |= (u64)nt[5 + i] << (i * 8);
    if (raw64 < 0x10000 || raw64 > URSUS_FIP_RAW_MAX)
        return -EFBIG;
    raw_cap = (SizeT)raw64;
    raw = malloc(raw_cap);
    if (!raw)
        return -ENOMEM;
    compressed_len = nt_size;
    ret = lzmaBuffToBuffDecompress(raw, &raw_cap, nt, compressed_len);
    if (ret != SZ_OK || raw_cap != raw64) {
        printf("URSUS_UPDATE_REJECT reason=nt-fw-lzma ret=%d expected=%llu got=%lu\n",
               ret, (unsigned long long)raw64, (ulong)raw_cap);
        free(raw);
        return -EBADMSG;
    }

    ursus_id = ursus_mem_has(raw, raw_cap, "U-Boot 2026.07-UrsusBoot-") &&
               ursus_mem_has(raw, raw_cap, "nokia,xg-040g-mf") &&
               ursus_mem_has(raw, raw_cap, "airoha,an7583");
    stock_id = ursus_mem_has(raw, raw_cap, "AN7583DT") &&
               ursus_mem_has(raw, raw_cap, "XG040GMF");
    if (!ursus_id && !stock_id) {
        printf("URSUS_UPDATE_REJECT reason=device-mismatch ursus=%u board=%u soc=%u stock_board=%u stock_soc=%u\n",
               ursus_mem_has(raw, raw_cap, "U-Boot 2026.07-UrsusBoot-"),
               ursus_mem_has(raw, raw_cap, "nokia,xg-040g-mf"),
               ursus_mem_has(raw, raw_cap, "airoha,an7583"),
               ursus_mem_has(raw, raw_cap, "XG040GMF"),
               ursus_mem_has(raw, raw_cap, "AN7583DT"));
        free(raw);
        return -ENODEV;
    }
    printf("URSUS_MF3_FIP_IDENTITY identity=%s validation=FIP_PARSE+NTFW_LZMA+BOARD_SOC\n",
           ursus_id ? "URSUSBOOT_MF" : "NOKIA_XG040GMF_STOCK");
    free(raw);
    sha256_csum_wd(buf, len, digest, CHUNKSZ_SHA256);
    return 0;
}'''


VALIDATE = r'''int ursus_fip_validate(ulong addr, size_t len, bool stock_limit)
{
    const u8 *buf = map_sysmem(addr, len);
    u8 digest[SHA256_SUM_LEN];
    int ret;
    unsigned int i;

    if (!buf)
        return -ENOMEM;
    ret = ursus_fip_validate_buf(buf, len, stock_limit, digest);
    unmap_sysmem(buf);
    if (ret) {
        printf("URSUS_UPDATE_PRECHECK_REJECT ret=%d len=%u stock_limit=%u\n",
               ret, (unsigned int)len, stock_limit);
        return ret;
    }
    printf("URSUS_UPDATE_PRECHECK_OK bytes=%u sha256=", (unsigned int)len);
    for (i = 0; i < SHA256_SUM_LEN; i++)
        printf("%02x", digest[i]);
    printf(" board=nokia_xg-040g-mf soc=an7583 validator=MD_STYLE_GENERAL\n");
    return 0;
}'''


def patch_update(root: Path) -> None:
    path = root / "cmd/ursusupdate.c"
    text = path.read_text(encoding="utf-8")
    text = replace_func(text, "ursus_fip_parse", FIP_PARSE)
    text = replace_func(text, "ursus_fip_validate_current", VALIDATE_CURRENT)
    text = replace_func(text, "ursus_fip_validate_buf", VALIDATE_BUF)
    text = replace_func(text, "ursus_fip_validate", VALIDATE)

    # PERSIST1 supplied the already-audited stock mtd0 preserve/write/readback
    # engine. PERSIST2 changes its policy/labels from one-build canary semantics
    # to ordinary MF FIP update + Nokia stock-FIP rollback semantics.
    replacements = (
        ("URSUS_MF3_PERSIST1_REJECT layout=UBI reason=FIP_ONLY_STOCK_CANARY",
         "URSUS_MF3_PERSIST2_REJECT layout=UBI reason=STOCK_LAYOUT_FIP_UPDATE_ONLY"),
        ("URSUS_MF3_PERSIST1_PRECHECK layout=STOCK scope=FIP_ONLY_CANARY bytes=%u",
         "URSUS_MF3_PERSIST2_PRECHECK layout=STOCK scope=FIP_UPDATE_ROLLBACK bytes=%u"),
        ("URSUS_MF3_PERSIST1_PRECHECK_OK", "URSUS_MF3_PERSIST2_PRECHECK_OK"),
        ("URSUS_MF3_PERSIST1_STOCK_FIP_OK", "URSUS_MF3_PERSIST2_CURRENT_FIP_OK"),
        ("URSUS_MF3_PERSIST1_COMMIT_BEGIN", "URSUS_MF3_PERSIST2_COMMIT_BEGIN"),
        ("URSUS_MF3_PERSIST1_COMMIT_OK", "URSUS_MF3_PERSIST2_COMMIT_OK"),
        ("MF3_PERSIST1_UBI_BLOCKED", "MF3_PERSIST2_UBI_BLOCKED"),
        ("MF3_PERSIST1_INVALID_STAGE", "MF3_PERSIST2_INVALID_STAGE"),
    )
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"PERSIST2 update anchor missing: {old}")
        text = text.replace(old, new)

    forbidden = (
        "FIP_ONLY_CANARY",
        "FIP_ONLY_STOCK_CANARY",
        "NOKIA_AN7583_STOCK",
        "MF2_STOCK_FIP_VALIDATION_DISABLED",
    )
    for token in forbidden:
        if token in text:
            raise SystemExit(f"obsolete validator/canary token survived: {token}")

    parse_start = text.index("static int ursus_fip_parse(")
    parse_end = text.index("static int ursus_fip_validate_current(", parse_start)
    parse_body = text[parse_start:parse_end]
    if "URSUS_FIP_TOC_MIN" in parse_body:
        raise SystemExit("MF parser still contains fixed 0x400 TOC floor")
    for required in (
        "toc_end = (size_t)((const u8 *)(ent + 1) - buf)",
        "off < toc_end",
        "URSUS_MF3_FIP_PARSE_OK",
    ):
        if required not in parse_body:
            raise SystemExit(f"dynamic TOC parser invariant missing: {required}")

    for required in (
        "URSUSBOOT_MF",
        "NOKIA_XG040GMF_STOCK",
        "AN7583DT",
        "XG040GMF",
        "nokia,xg-040g-mf",
        "airoha,an7583",
        "MD_STYLE_GENERAL",
        "FIP_UPDATE_ROLLBACK",
    ):
        if required not in text:
            raise SystemExit(f"PERSIST2 validator marker missing: {required}")
    path.write_text(text, encoding="utf-8")


def patch_web(root: Path) -> None:
    path = root / "cmd/ursusweb.c"
    text = path.read_text(encoding="utf-8")
    changes = (
        ("FIP_ONLY_CANARY", "FIP_UPDATE_ROLLBACK"),
        ("URSUS_MF3_PERSIST1_POST_ALLOW", "URSUS_MF3_PERSIST2_POST_ALLOW"),
        ("URSUS_MF3_PERSIST1_POST_REJECT", "URSUS_MF3_PERSIST2_POST_REJECT"),
        ("PERSIST1_SCOPE", "PERSIST2_SCOPE"),
        ("MF3 canary permits only UrsusBoot FIP update; OpenWrt/UBI/settings writes remain disabled",
         "MF3 permits validated UrsusBoot MF update or Nokia MF stock-FIP rollback; OpenWrt/UBI/settings writes remain disabled"),
    )
    for old, new in changes:
        if old not in text:
            raise SystemExit(f"PERSIST2 Web anchor missing: {old}")
        text = text.replace(old, new)
    if "FIP_ONLY_CANARY" in text or "MF3 canary" in text:
        raise SystemExit("PERSIST2 obsolete canary UI survived")
    path.write_text(text, encoding="utf-8")


def patch(root: Path) -> None:
    root = root.resolve()
    patch_update(root)
    patch_web(root)
    print("MF3_PERSIST2_VALIDATOR=PASS model=MD_STYLE_GENERAL_DYNAMIC_TOC accepted=URSUSBOOT_MF,NOKIA_XG040GMF_STOCK write_scope=FIP_UPDATE_ROLLBACK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
