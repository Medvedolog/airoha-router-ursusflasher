#!/bin/bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/md-transition2"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
COMMON_CONFIG="$ROOT/ursusboot/configs/ursusboot-common.cfg"
BOARD_CONFIG="$ROOT/ursusboot/configs/ursusboot-board-md.cfg"
TRANSITION_CONFIG="$ROOT/ursusboot/configs/ursusboot-transition-handoff.cfg"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
PATCH_HANDOFF="$ROOT/ursusboot/patches/190-md-transition1-handoff.patch"
PATCH_UART_FALLBACK="$ROOT/ursusboot/patches/200-transition2-uart-fallback.patch"
PATCH_NETDBG="$ROOT/ursusboot/patches/210-transition2-netdbg1-netreset.patch"
PATCH_STOCKSLOT="$ROOT/ursusboot/patches/220-transition2-stockslot-command.patch"
OUT="$WORK/out"
RELEASE_EPOCH=1789300800
VERSION="0.1.0-alpha5-UBIUX1-TRANSITION2"
STOCK_KERNEL_LOAD=0x80088000
TEXT_BASE=0x81e00000

for x in tar make gcc perl python3 sha256sum patch; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$CONFIG" "$COMMON_CONFIG" "$BOARD_CONFIG" "$TRANSITION_CONFIG" "$CONFIG_MERGER" "$PATCH_HANDOFF" "$PATCH_UART_FALLBACK" "$PATCH_NETDBG" "$PATCH_STOCKSLOT"; do
    [ -f "$f" ] || { echo "missing build input: $f" >&2; exit 1; }
done

if [ ! -f "$SDK_BUNDLE" ]; then
    bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null
fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"
TEST61_WEB_SHA=$(sha256sum "$WORK/u-boot/cmd/ursusweb.c" | awk '{print $1}')
patch -d "$WORK/u-boot" -p1 < "$PATCH_HANDOFF"
patch -d "$WORK/u-boot" -p1 < "$PATCH_UART_FALLBACK"
patch -d "$WORK/u-boot" -p1 < "$PATCH_NETDBG"
python3 - "$WORK/u-boot/drivers/net/airoha_eth.c" <<'PYMAC'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '''\tret = arht_eth_write_hwaddr(dev);\n\tif (ret) {\n\t\tprintf("URSUS_NETRESET_FAIL stage=HWADDR ret=%d\\n", ret);\n\t\treturn CMD_RET_FAILURE;\n\t}\n'''
new = '''\t{\n\t\tstruct eth_pdata *pdata = dev_get_plat(dev);\n\t\tstatic const u8 fixed_mac[ARP_HLEN] = {\n\t\t\t0x02, 0x55, 0x52, 0x53, 0x55, 0x53\n\t\t};\n\n\t\tif (!pdata) {\n\t\t\tprintf("URSUS_NETRESET_FAIL stage=FIXED_MAC reason=NO_ETH_PDATA\\n");\n\t\t\treturn CMD_RET_FAILURE;\n\t\t}\n\t\tmemcpy(pdata->enetaddr, fixed_mac, sizeof(fixed_mac));\n\t\tret = eth_env_set_enetaddr("ethaddr", fixed_mac);\n\t\tprintf("URSUS_TRANSITION_FIXED_MAC mac=%pM env_ret=%d\\n",\n\t\t       fixed_mac, ret);\n\t\tif (ret && ret != -EEXIST)\n\t\t\treturn CMD_RET_FAILURE;\n\t}\n\n\tret = arht_eth_write_hwaddr(dev);\n\tif (ret) {\n\t\tprintf("URSUS_NETRESET_FAIL stage=HWADDR ret=%d\\n", ret);\n\t\treturn CMD_RET_FAILURE;\n\t}\n'''
count = s.count(old)
if count != 1:
    raise SystemExit(f"TRANSITION2-FIXEDMAC1 source match count={count}, expected=1")
p.write_text(s.replace(old, new))
print("TRANSITION2-FIXEDMAC1 source transform=PASS mac=02:55:52:53:55:53 allow_env_eexist=1")
PYMAC
python3 - "$WORK/u-boot/cmd/ursusdispatch.c" <<'PYWEB'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '    return ursus_enter_webfailsafe("TRANSITION_WEB_ONLY", 0);'
new = '''    ursus_recovery_latched = true;
    snprintf(ursus_recovery_reason, sizeof(ursus_recovery_reason), "%s",
             "TRANSITION_WEB_ONLY");
    printf("URSUS_TRANSITION_CANONICAL_RECOVERY=1 reason=%s\\n",
           ursus_recovery_reason);'''
count = s.count(old)
if count != 1:
    raise SystemExit(f"TRANSITION2-WEBLOOP1 source match count={count}, expected=1")
p.write_text(s.replace(old, new))
print("TRANSITION2-WEBLOOP1 source transform=PASS matches=1")
PYWEB
patch -d "$WORK/u-boot" -p1 < "$PATCH_STOCKSLOT"
TRANSITION_WEB_SHA=$(sha256sum "$WORK/u-boot/cmd/ursusweb.c" | awk '{print $1}')
[ "$TRANSITION_WEB_SHA" = "$TEST61_WEB_SHA" ] || {
    echo "TRANSITION2-TEST61WEB1: cmd/ursusweb.c diverged from persistent TEST61 source" >&2
    exit 1
}
if grep -Fq 'cmd/ursusweb.c' "$PATCH_HANDOFF"; then
    echo "TRANSITION2-TEST61WEB1: handoff patch must not modify cmd/ursusweb.c" >&2
    exit 1
fi

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"

cp "$CONFIG" "$WORK/u-boot/.config"
python3 "$CONFIG_MERGER" --config "$WORK/u-boot/.config" "$COMMON_CONFIG" "$BOARD_CONFIG" "$TRANSITION_CONFIG"
cd "$WORK/u-boot"
make olddefconfig

grep -q '^CONFIG_ENV_IS_NOWHERE=y$' .config || { echo 'TRANSITION2: ENV_IS_NOWHERE missing' >&2; exit 1; }
for sym in CONFIG_ENV_IS_IN_UBI CONFIG_ENV_REDUNDANT CONFIG_CMD_SAVEENV CONFIG_CMD_ERASEENV; do
    if grep -q "^${sym}=y$" .config; then
        echo "TRANSITION2: forbidden ${sym}=y" >&2
        exit 1
    fi
done
grep -q '^CONFIG_NET_LWIP=y$' .config || { echo 'TRANSITION2: NET_LWIP missing' >&2; exit 1; }
grep -q '^CONFIG_MTD=y$' .config || { echo 'TRANSITION2: MTD missing' >&2; exit 1; }
grep -q '^CONFIG_TEXT_BASE=0x81e00000$' .config || { echo 'TRANSITION2: unexpected TEXT_BASE' >&2; exit 1; }
grep -Fq '#define URSUS_TRANSITION_WEB_ONLY 1' include/ursus_version.h || { echo 'TRANSITION2: Web-only dispatcher marker missing' >&2; exit 1; }
grep -Fq 'URSUS_TRANSITION_WEB_BEGIN' cmd/ursusdispatch.c || { echo 'TRANSITION2: dispatcher Web entry missing' >&2; exit 1; }
grep -Fq 'URSUS_TRANSITION_NET_SANITIZE_BEGIN' cmd/ursusdispatch.c || { echo 'TRANSITION2-NETFIX2: startup network sanitize missing' >&2; exit 1; }
grep -Fq 'run_command("ursusnetreset", 0)' cmd/ursusdispatch.c || { echo 'TRANSITION2-NETFIX2: startup reset command missing' >&2; exit 1; }
grep -Fq 'URSUS_TRANSITION_CANONICAL_RECOVERY=1' cmd/ursusdispatch.c || { echo 'TRANSITION2-WEBLOOP1: canonical recovery marker missing' >&2; exit 1; }
if grep -Fq 'return ursus_enter_webfailsafe("TRANSITION_WEB_ONLY", 0);' cmd/ursusdispatch.c; then
    echo 'TRANSITION2-WEBLOOP1: forbidden direct Web return still present' >&2
    exit 1
fi
grep -Fq 'URSUS_WEB_COMMAND_BEGIN' cmd/ursusdispatch.c || { echo 'TRANSITION2-WEBLOOP1: Web begin marker missing' >&2; exit 1; }
grep -Fq 'URSUS_WEB_COMMAND_RETURN ret=%d' cmd/ursusdispatch.c || { echo 'TRANSITION2-WEBLOOP1: Web return marker missing' >&2; exit 1; }
grep -Fq 'URSUS_UART_FALLBACK=READY scope=TRANSITION shell=UNRESTRICTED after=WEB_COMMAND_RETURN' cmd/ursusdispatch.c || { echo 'TRANSITION2-WEBLOOP1: UART fallback ordering marker missing' >&2; exit 1; }
grep -Fq 'ursusstockslot, 2, 0, do_ursusstockslot' cmd/ursusdispatch.c || { echo 'TRANSITION2-STOCKSLOT1: command missing' >&2; exit 1; }
grep -Fq 'URSUS_STOCKSLOT_DONE' cmd/ursusdispatch.c || { echo 'TRANSITION2-STOCKSLOT1: readback marker missing' >&2; exit 1; }
grep -Fq '&gdm1 {' arch/arm/dts/an7581-nokia-xg-040g-md-u-boot.dtsi || { echo 'TRANSITION2: board U-Boot DT does not force gdm1 okay' >&2; exit 1; }
grep -Fq 'status = "okay";' arch/arm/dts/an7581-nokia-xg-040g-md-u-boot.dtsi || { echo 'TRANSITION2: gdm1 status override missing' >&2; exit 1; }
grep -Fq 'URSUS_NETDBG_RX_RING' drivers/net/airoha_eth.c || { echo 'TRANSITION2-NETDBG1: RX ring readback marker missing' >&2; exit 1; }
grep -Fq 'URSUS_NETDBG_FIRST_RX' drivers/net/airoha_eth.c || { echo 'TRANSITION2-NETDBG1: first RX marker missing' >&2; exit 1; }
grep -Fq 'ursusnetreset, 1, 0, do_ursusnetreset' drivers/net/airoha_eth.c || { echo 'TRANSITION2-NETFIX2: reset command missing' >&2; exit 1; }
grep -Fq 'URSUS_TRANSITION_FIXED_MAC mac=%pM env_ret=%d' drivers/net/airoha_eth.c || { echo 'TRANSITION2-FIXEDMAC1: fixed MAC marker missing' >&2; exit 1; }
grep -Fq 'ret && ret != -EEXIST' drivers/net/airoha_eth.c || { echo 'TRANSITION2-FIXEDMAC1: EEXIST tolerance missing' >&2; exit 1; }

make -j"${JOBS:-$(nproc)}"

cat > "$WORK/transition-linux-handoff.S" <<'EOF_ASM'
.section .text,"ax"
.global _start
_start:
    b handoff
    .long 0
    .quad 0
    .quad image_end - _start
    .quad 0
    .quad 0
    .quad 0
    .quad 0
    .long 0x644d5241
    .long 0
handoff:
    adr x0, payload_start
    movz x5, #0x0000
    movk x5, #0x81e0, lsl #16
    mov x1, x5
    adr x2, payload_end
    sub x3, x2, x0
1:
    cmp x3, #8
    b.lo 2f
    ldr x4, [x0], #8
    str x4, [x1], #8
    sub x3, x3, #8
    b 1b
2:
    cbz x3, 4f
3:
    ldrb w4, [x0], #1
    strb w4, [x1], #1
    subs x3, x3, #1
    b.ne 3b
4:
    mov x6, x5
    adr x7, payload_end
    adr x8, payload_start
    sub x7, x7, x8
    add x7, x5, x7
5:
    dc cvau, x6
    add x6, x6, #64
    cmp x6, x7
    b.lo 5b
    dsb sy
    ic iallu
    dsb sy
    isb
    br x5
    .balign 16
payload_start:
    .incbin "u-boot.bin"
payload_end:
image_end:
EOF_ASM

${CROSS_COMPILE}gcc -c -nostdlib "$WORK/transition-linux-handoff.S" -o "$WORK/transition-linux-handoff.o"
${CROSS_COMPILE}ld -Ttext="$STOCK_KERNEL_LOAD" --entry=_start -nostdlib \
    -o "$WORK/transition-linux-handoff.elf" "$WORK/transition-linux-handoff.o"
${CROSS_COMPILE}objcopy -O binary "$WORK/transition-linux-handoff.elf" \
    "$OUT/ursusboot-md-${VERSION}.linuximg"

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map "$OUT/"
[ "$(cat .scmversion)" = "-UrsusBoot-${VERSION}" ]
grep -Fq "#define URSUS_VERSION \"${VERSION}\"" include/ursus_version.h
grep -Fq '#define URSUS_TRANSITION_HANDOFF_ONLY 0' include/ursus_version.h
grep -Fq '#define URSUS_TRANSITION_WEB_ONLY 1' include/ursus_version.h
strings u-boot.bin > "$WORK/u-boot.strings"
for marker in "$VERSION" 'TRANSITION' 'URSUS_TRANSITION_WEB_BEGIN' 'URSUS_TRANSITION_NET_SANITIZE_BEGIN' 'URSUS_TRANSITION_NET_SANITIZE_DONE' 'URSUS_TRANSITION_CANONICAL_RECOVERY=1' 'URSUS_WEB_COMMAND_BEGIN' 'URSUS_WEB_COMMAND_RETURN' 'URSUS_UART_FALLBACK=READY scope=TRANSITION shell=UNRESTRICTED after=WEB_COMMAND_RETURN' 'URSUS_NETDBG_RX_RING' 'URSUS_NETDBG_FIRST_RX' 'URSUS_NETRESET_BEGIN build=TRANSITION2-NETFIX2' 'URSUS_TRANSITION_FIXED_MAC' 'ursusnetreset' 'ursusstockslot' 'URSUS_STOCKSLOT_DONE'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "missing transition marker: $marker" >&2; exit 1; }
done

python3 - "$OUT/ursusboot-md-${VERSION}.linuximg" u-boot.bin <<'PYQA'
import hashlib, struct, sys
image = open(sys.argv[1], 'rb').read()
uboot = open(sys.argv[2], 'rb').read()
assert len(image) >= 64 + len(uboot)
assert struct.unpack_from('<I', image, 56)[0] == 0x644d5241
assert struct.unpack_from('<Q', image, 8)[0] == 0
assert struct.unpack_from('<Q', image, 16)[0] == len(image)
assert struct.unpack_from('<Q', image, 24)[0] == 0
assert image.endswith(uboot)
print(f'TRANSITION_LINUX_IMAGE_QA=PASS bytes={len(image)} stock_entry=0x80088000 text_base=0x81e00000')
print('TRANSITION_LINUX_IMAGE_SHA256=' + hashlib.sha256(image).hexdigest())
PYQA

sha256sum u-boot.bin "$OUT/ursusboot-md-${VERSION}.linuximg" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
    "UrsusBoot ${VERSION}" \
    "MODE=TRANSITION" \
    "PERSISTENCE_TARGET=NONE" \
    "FINAL_TARGET=OFFICIAL_OPENWRT" \
    "HANDOFF_ONLY=0" \
    "TRANSITION_ENTRY=ursusdispatch->net-sanitize->canonical-recovery->ursusweb" \
    "WEB_LOOP_POLICY=CANONICAL_PERSISTENT_RECOVERY" \
    "UART_FALLBACK=AFTER_WEB_COMMAND_RETURN" \
    "AN7581_GDM1_UBOOT_DTS=ALREADY_PRESENT" \
    "NETDBG_BUILD=TRANSITION2-NETDBG1" \
    "NETFIX_BUILD=TRANSITION2-NETFIX2" \
    "NETRESET_COMMAND=ursusnetreset" \
    "NETRESET_TIMING=AUTOMATIC_BEFORE_WEBFAILSAFE" \
    "TRANSITION_FIXED_MAC=02:55:52:53:55:53" \
    "TRANSITION_FIXED_MAC_SCOPE=RAM_ENV_AND_ETH_PDATA" \
    "TRANSITION_FIXED_MAC_ENV_EEXIST=ALLOWED" \
    "STOCKSLOT_BUILD=TRANSITION2-STOCKSLOT1" \
    "STOCKSLOT_COMMAND=ursusstockslot status|master|slave" \
    "STOCKSLOT_FLAG_OFFSET=0x05240000" \
    "STOCKSLOT_FLAGBACK_WRITE=NEVER" \
    "WEB_SOURCE=PERSISTENT_TEST61_UNMODIFIED" \
    "WEB_SOURCE_SHA256=${TRANSITION_WEB_SHA}" \
    "ENV_IS_NOWHERE=PASS" \
    "STOCK_INNER_FORMAT=ARM64_LINUX_IMAGE_HANDOFF" \
    "STOCK_KERNEL_LOAD=${STOCK_KERNEL_LOAD}" \
    "TEXT_BASE=${TEXT_BASE}" \
    "SOURCE_DATE_EPOCH=${RELEASE_EPOCH}" > "$OUT/TRANSITION2-BUILD_INFO.txt"

echo "MD_TRANSITION2_NETFIX2_FIXEDMAC1_STOCKSLOT1_TEST61WEB1_BUILD=PASS"
echo "Artifacts: $OUT"
