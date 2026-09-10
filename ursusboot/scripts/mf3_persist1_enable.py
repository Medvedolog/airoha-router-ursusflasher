#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact match, got {count}")
    return text.replace(old, new, 1)


def patch_update(root: Path) -> None:
    path = root / "cmd/ursusupdate.c"
    text = path.read_text(encoding="utf-8")

    start_gate = '''    printf("URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE\\n");
    return -EROFS;

'''
    text = replace_exact(text, start_gate, "", "remove MF2 FIP start gate")

    detect = '''    ret = ursus_detect_ubi_layout(&is_ubi);
    if (ret)
        return ret;
    ret = ursus_fip_validate(addr, len, !is_ubi);
'''
    detect_new = '''    ret = ursus_detect_ubi_layout(&is_ubi);
    if (ret)
        return ret;
    if (is_ubi) {
        printf("URSUS_MF3_PERSIST1_REJECT layout=UBI reason=FIP_ONLY_STOCK_CANARY\\n");
        return -EROFS;
    }
    printf("URSUS_MF3_PERSIST1_PRECHECK layout=STOCK scope=FIP_ONLY_CANARY bytes=%u\\n",
           (unsigned int)len);
    ret = ursus_fip_validate(addr, len, true);
'''
    text = replace_exact(text, detect, detect_new, "PERSIST1 stock-only start guard")

    stock_old = '''    stock_id = ursus_mem_has(raw, raw_cap, "MF2_STOCK_FIP_VALIDATION_DISABLED") &&
               ursus_mem_has(raw, raw_cap, "AN7583");
'''
    stock_new = '''    stock_id = !ursus_id &&
               (ursus_mem_has(raw, raw_cap, "AN7583") ||
                ursus_mem_has(raw, raw_cap, "airoha,an7583") ||
                ursus_mem_has(raw, raw_cap, "nokia,xg-040g-mf"));
'''
    text = replace_exact(text, stock_old, stock_new, "MF stock FIP structural identity")
    text = replace_exact(text, '"MF2_STOCK_FIP_DISABLED"', '"NOKIA_AN7583_STOCK"', "MF stock identity label")

    step_stub = '''int ursus_fip_update_step(void)
{
    printf("URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE_STEP\\n");
    return -EROFS;
}
'''
    step = '''int ursus_fip_update_step(void)
{
    int ret = 0;
    const u8 *src;

    if (!ursus_up.active)
        return ursus_up.stage == URSUS_UP_COMPLETE ? 1 :
               ursus_up.stage == URSUS_UP_FAILED ? ursus_up.error : 0;
    if (!ursus_up.announced) {
        ursus_up.announced = true;
        ursus_up.announced_at = get_timer(0);
        printf("URSUS_UPDATE_STAGE name=%s percent=%u detail=%s\\n",
               ursus_update_stage_name(ursus_up.stage),
               ursus_update_percent_value(ursus_up.stage),
               ursus_update_detail_text(ursus_up.stage));
        return 0;
    }
    if (get_timer(ursus_up.announced_at) < URSUS_UPDATE_STAGE_HOLD_MS)
        return 0;
    ursus_up.announced = false;

    switch (ursus_up.stage) {
    case URSUS_UP_PRECHECK:
        ret = ursus_detect_ubi_layout(&ursus_up.ubi_layout);
        if (ret)
            return ursus_update_fail_reason(ret, "PRECHECK_LAYOUT_DETECT_FAILED");
        if (ursus_up.ubi_layout)
            return ursus_update_fail_reason(-EROFS, "MF3_PERSIST1_UBI_BLOCKED");
        ret = ursus_fip_validate(ursus_up.addr, ursus_up.len, true);
        if (ret)
            return ursus_update_fail_reason(ret, "PRECHECK_FIP_VALIDATE_FAILED");
        printf("URSUS_MF3_PERSIST1_PRECHECK_OK nand=256MiB erase=0x20000 writesize=0x800 layout=STOCK\\n");
        ursus_up.last_success_stage = URSUS_UP_PRECHECK;
        ursus_up.stage = URSUS_UP_STOCK_BACKUP;
        break;

    case URSUS_UP_STOCK_BACKUP: {
        size_t old_end = 0;

        ret = ursus_bad_in_range(ursus_update_nand, 0, URSUS_STOCK_BOOT_SIZE);
        if (ret)
            return ursus_update_fail(ret < 0 ? ret : -EIO);
        ursus_up.stock_candidate = malloc(URSUS_STOCK_BOOT_SIZE);
        ursus_up.stock_readback = malloc(URSUS_STOCK_BOOT_SIZE);
        if (!ursus_up.stock_candidate || !ursus_up.stock_readback)
            return ursus_update_fail(-ENOMEM);
        ret = ursus_read_exact(ursus_update_nand, 0, URSUS_STOCK_BOOT_SIZE,
                               ursus_up.stock_candidate);
        if (ret)
            return ursus_update_fail(ret);
        ret = ursus_fip_validate_current(ursus_up.stock_candidate + URSUS_STOCK_FIP_OFF,
                                         URSUS_STOCK_FIP_MAX, &old_end);
        if (ret || old_end >= URSUS_STOCK_FIP_MAX)
            return ursus_update_fail(ret ? ret : -EINVAL);
        printf("URSUS_MF3_PERSIST1_STOCK_FIP_OK offset=0x800 old_fip=0x%x env=0x7c000/0x4000\\n",
               (unsigned int)old_end);
        memset(ursus_up.stock_candidate + URSUS_STOCK_FIP_OFF, 0xff,
               URSUS_STOCK_FIP_MAX);
        src = map_sysmem(ursus_up.addr, ursus_up.len);
        if (!src)
            return ursus_update_fail(-ENOMEM);
        memcpy(ursus_up.stock_candidate + URSUS_STOCK_FIP_OFF, src, ursus_up.len);
        unmap_sysmem(src);
        printf("URSUS_UPDATE_STOCK_BACKUP_OK bytes=0x%lx old_fip=0x%x preserve_prefix=0x800 preserve_env=0x4000\\n",
               (ulong)URSUS_STOCK_BOOT_SIZE, (unsigned int)old_end);
        ursus_up.last_success_stage = URSUS_UP_STOCK_BACKUP;
        ursus_up.stage = URSUS_UP_STOCK_ERASE;
        break;
    }

    case URSUS_UP_STOCK_ERASE: {
        struct erase_info ei = { .addr = 0, .len = URSUS_STOCK_BOOT_SIZE };

        ursus_up.write_started = true;
        ursus_up.commit_started = true;
        printf("URSUS_MF3_PERSIST1_COMMIT_BEGIN target=stock-mtd0 span=0x80000 fip_off=0x800 env_preserved=1\\n");
        printf("URSUS_UPDATE_ERASE_BEGIN layout=STOCK off=0 size=0x%lx\\n",
               (ulong)URSUS_STOCK_BOOT_SIZE);
        ret = mtd_erase(ursus_update_nand, &ei);
        if (ret)
            return ursus_update_fail(ret);
        printf("URSUS_UPDATE_ERASE_OK layout=STOCK\\n");
        ursus_up.last_success_stage = URSUS_UP_STOCK_ERASE;
        ursus_up.stage = URSUS_UP_STOCK_WRITE;
        break;
    }

    case URSUS_UP_STOCK_WRITE: {
        size_t written = 0;

        ret = mtd_write(ursus_update_nand, 0, URSUS_STOCK_BOOT_SIZE,
                        &written, ursus_up.stock_candidate);
        if (ret || written != URSUS_STOCK_BOOT_SIZE)
            return ursus_update_fail(ret ? ret : -EIO);
        printf("URSUS_UPDATE_WRITE_OK layout=STOCK bytes=0x%lx\\n",
               (ulong)URSUS_STOCK_BOOT_SIZE);
        ursus_up.last_success_stage = URSUS_UP_STOCK_WRITE;
        ursus_up.stage = URSUS_UP_STOCK_VERIFY;
        break;
    }

    case URSUS_UP_STOCK_VERIFY:
        ret = ursus_read_exact(ursus_update_nand, 0, URSUS_STOCK_BOOT_SIZE,
                               ursus_up.stock_readback);
        if (ret || memcmp(ursus_up.stock_candidate, ursus_up.stock_readback,
                          URSUS_STOCK_BOOT_SIZE))
            return ursus_update_fail(ret ? ret : -EBADMSG);
        printf("URSUS_UPDATE_READBACK_OK layout=STOCK bytes=0x%lx prefix=preserved env=preserved\\n",
               (ulong)URSUS_STOCK_BOOT_SIZE);
        ursus_up.last_success_stage = URSUS_UP_STOCK_VERIFY;
        ursus_up.stage = URSUS_UP_COMPLETE;
        ursus_up.active = false;
        free(ursus_up.stock_candidate);
        ursus_up.stock_candidate = NULL;
        free(ursus_up.stock_readback);
        ursus_up.stock_readback = NULL;
        printf("URSUS_MF3_PERSIST1_COMMIT_OK readback=byte-exact reboot=MANUAL\\n");
        printf("URSUS_UPDATE_COMMIT_OK layout=STOCK reboot=MANUAL\\n");
        return 1;

    default:
        return ursus_update_fail_reason(-EINVAL, "MF3_PERSIST1_INVALID_STAGE");
    }
    return 0;
}
'''
    text = replace_exact(text, step_stub, step, "restore stock-only FIP update step")

    required = (
        "URSUS_MF3_PERSIST1_PRECHECK",
        "URSUS_MF3_PERSIST1_PRECHECK_OK",
        "URSUS_MF3_PERSIST1_STOCK_FIP_OK",
        "URSUS_MF3_PERSIST1_COMMIT_BEGIN",
        "URSUS_MF3_PERSIST1_COMMIT_OK",
        "NOKIA_AN7583_STOCK",
    )
    for marker in required:
        if marker not in text:
            raise SystemExit(f"PERSIST1 update marker missing: {marker}")
    for forbidden in (
        "URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE\\n",
        "URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE_STEP\\n",
    ):
        if forbidden in text:
            raise SystemExit(f"PERSIST1 FIP gate survived: {forbidden}")

    path.write_text(text, encoding="utf-8")


def patch_web(root: Path) -> None:
    path = root / "cmd/ursusweb.c"
    text = path.read_text(encoding="utf-8")

    status_old = '\\\"ram_read_only\\\":true,\\\"persistent_write_enabled\\\":false,\\\"ram_boot_enabled\\\":true,\\\"boot_fdt_compatible\\\"'
    status_new = '\\\"ram_read_only\\\":false,\\\"persistent_write_enabled\\\":true,\\\"persistent_write_scope\\\":\\\"FIP_ONLY_CANARY\\\",\\\"ram_boot_enabled\\\":true,\\\"boot_fdt_compatible\\\"'
    text = replace_exact(text, status_old, status_new, "PERSIST1 status capability")

    reject_old = '''    } else if (!strncmp(c->reqhdr, "POST ", 5)) {
        ursus_logf("MF2 READONLY: rejected HTTP POST\\n");
        return ursus_http_start_response(pcb, c, 403, "application/json",
            "{\\\"result\\\":\\\"REJECTED\\\",\\\"reason_class\\\":\\\"READ_ONLY_BRINGUP\\\",\\\"reason\\\":\\\"MF2 RAM-only build: persistent operations disabled\\\"}\\n");
    }
'''
    reject_new = '''    } else if (URSUS_REQ_MATCH(c->reqhdr, "POST /api/ursus-fip-begin ") ||
               URSUS_REQ_MATCH(c->reqhdr, "POST /api/ursus-fip-discard ") ||
               URSUS_REQ_MATCH(c->reqhdr, "POST /api/update-ursusboot ") ||
               URSUS_REQ_MATCH(c->reqhdr, "POST /api/reboot ")) {
        ursus_logf("URSUS_MF3_PERSIST1_POST_ALLOW scope=FIP_ONLY_CANARY\\n");
    } else if (URSUS_REQ_MATCH(c->reqhdr, "POST /api/ursus-fip-chunk ")) {
        /* volatile upload transport; intentionally no per-chunk operation log */
    } else if (!strncmp(c->reqhdr, "POST ", 5)) {
        ursus_logf("URSUS_MF3_PERSIST1_POST_REJECT scope=FIP_ONLY_CANARY\\n");
        return ursus_http_start_response(pcb, c, 403, "application/json",
            "{\\\"result\\\":\\\"REJECTED\\\",\\\"reason_class\\\":\\\"PERSIST1_SCOPE\\\",\\\"reason\\\":\\\"MF3 canary permits only UrsusBoot FIP update; OpenWrt/UBI/settings writes remain disabled\\\"}\\n");
    }
'''
    text = replace_exact(text, reject_old, reject_new, "PERSIST1 selective POST gate")

    required = (
        "URSUS_MF3_PERSIST1_POST_ALLOW",
        "URSUS_MF3_PERSIST1_POST_REJECT",
        "FIP_ONLY_CANARY",
        "POST /api/ursus-fip-begin ",
        "POST /api/ursus-fip-chunk ",
        "POST /api/update-ursusboot ",
    )
    for marker in required:
        if marker not in text:
            raise SystemExit(f"PERSIST1 Web marker missing: {marker}")

    gate = text.index("URSUS_MF3_PERSIST1_POST_REJECT")
    for blocked_route in (
        'POST /api/console ',
        'POST /api/firmware-begin ',
        'POST /api/ubi-preloader-begin ',
        'POST /api/install-openwrt-stock-layout ',
        'POST /api/install-ubi ',
        'POST /api/reset-openwrt-settings ',
    ):
        handler = text.find(blocked_route, gate)
        if handler < 0:
            raise SystemExit(f"expected blocked route handler missing: {blocked_route}")

    path.write_text(text, encoding="utf-8")


def patch(root: Path) -> None:
    root = root.resolve()
    patch_update(root)
    patch_web(root)

    ubi = (root / "cmd/ursusubi.c").read_text(encoding="utf-8")
    for marker in (
        "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE",
        "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION",
        "URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND",
    ):
        if marker not in ubi:
            raise SystemExit(f"PERSIST1 safety gate missing: {marker}")

    web = (root / "cmd/ursusweb.c").read_text(encoding="utf-8")
    for marker in (
        "URSUS_MF2_READONLY_REJECT operation=FACTORY_INSTALL",
        "URSUS_MF2_READONLY_REJECT operation=FACTORY_SETTINGS_RESET",
    ):
        if marker not in web:
            raise SystemExit(f"PERSIST1 Web backend gate missing: {marker}")

    print("MF3_PERSIST1_ENABLE=PASS write_scope=fip-only stock-mtd0=0x80000 readback=byte-exact ubi=blocked generic-writers=unchanged")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
