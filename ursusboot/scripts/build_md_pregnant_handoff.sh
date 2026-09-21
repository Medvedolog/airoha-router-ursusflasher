#!/bin/bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/md-pregnant-handoff"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
COMMON_CONFIG="$ROOT/ursusboot/configs/ursusboot-common.cfg"
BOARD_CONFIG="$ROOT/ursusboot/configs/ursusboot-board-md.cfg"
HANDOFF_CONFIG="$ROOT/ursusboot/configs/ursusboot-pregnant-handoff.cfg"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
PATCH="$ROOT/ursusboot/patches/191-md-pregnant-handoff.patch"
OUT="$WORK/out"
RELEASE_EPOCH=1789300800
VERSION="0.1.0-alpha5-UBIUX1-PREGNANT1"
STOCK_KERNEL_LOAD=0x80088000
TEXT_BASE=0x81e00000
RUNTIME_DEST=0x92000000

for x in tar make gcc perl python3 sha256sum patch; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$CONFIG" "$COMMON_CONFIG" "$BOARD_CONFIG" "$HANDOFF_CONFIG" "$CONFIG_MERGER" "$PATCH"; do
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
patch -d "$WORK/u-boot" -p1 < "$PATCH"

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"

cp "$CONFIG" "$WORK/u-boot/.config"
python3 "$CONFIG_MERGER" --config "$WORK/u-boot/.config" "$COMMON_CONFIG" "$BOARD_CONFIG" "$HANDOFF_CONFIG"
cd "$WORK/u-boot"
make olddefconfig

grep -q '^CONFIG_ENV_IS_NOWHERE=y$' .config || { echo 'PREGNANT1: ENV_IS_NOWHERE missing' >&2; exit 1; }
grep -q '^CONFIG_TEXT_BASE=0x81e00000$' .config || { echo 'PREGNANT1: unexpected TEXT_BASE' >&2; exit 1; }
grep -q '^CONFIG_PSCI_RESET=y$' .config || { echo 'PREGNANT1: PSCI reset backend missing' >&2; exit 1; }
grep -q '^CONFIG_RESET_AIROHA=y$' .config || { echo 'PREGNANT1: Airoha reset backend missing' >&2; exit 1; }
for sym in CONFIG_CMD_PING CONFIG_CMD_DHCP CONFIG_CMD_DNS CONFIG_CMD_SNTP CONFIG_CMD_TFTPBOOT CONFIG_CMD_WGET CONFIG_CMD_MTD; do
    if grep -q "^${sym}=y$" .config; then
        echo "PREGNANT1: forbidden transient handoff capability ${sym}=y" >&2
        exit 1
    fi
done
grep -Fq '#define URSUS_PREGNANT_HANDOFF 1' include/ursus_version.h || { echo 'PREGNANT1 marker missing' >&2; exit 1; }
grep -Fq 'resetting for stock A/B retry' cmd/ursusdispatch.c || { echo 'PREGNANT1: rollback reset path missing' >&2; exit 1; }
grep -Fq 'URSUS_PREGNANT_HANDOFF_BEGIN addr=0x92000000' cmd/ursusdispatch.c || { echo 'PREGNANT1: direct handoff path missing' >&2; exit 1; }

make -j"${JOBS:-$(nproc)}"

# Hardware-proven stock tcboot handoff shape. The candidate builder patches
# exactly two little-endian u32 placeholders after the URSPREG1 marker:
# source offset from stock FIT loadaddr (0x81800000), and runtime FIT size.
# The shim copies the runtime to 0x92000000 BEFORE copying U-Boot over a part
# of the stock FIT address range, then starts RAM-only UrsusBoot at 0x81e00000.
cat > "$WORK/pregnant-linux-handoff.S" <<'EOF_ASM'
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
    adr x9, runtime_meta
    ldr w10, [x9, #8]
    ldr w11, [x9, #12]

    movz x0, #0x0000
    movk x0, #0x8180, lsl #16
    add x0, x0, x10
    movz x1, #0x0000
    movk x1, #0x9200, lsl #16
    uxtw x3, w11
6:
    cmp x3, #8
    b.lo 7f
    ldr x4, [x0], #8
    str x4, [x1], #8
    sub x3, x3, #8
    b 6b
7:
    cbz x3, 9f
8:
    ldrb w4, [x0], #1
    strb w4, [x1], #1
    subs x3, x3, #1
    b.ne 8b
9:
    movz x6, #0x0000
    movk x6, #0x9200, lsl #16
    uxtw x7, w11
    add x7, x6, x7
10:
    dc cvau, x6
    add x6, x6, #64
    cmp x6, x7
    b.lo 10b
    dsb sy
    ic iallu
    dsb sy
    isb

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
runtime_meta:
    .ascii "URSPREG1"
    .long 0xfeedface
    .long 0xcafef00d
    .balign 16
payload_start:
    .incbin "u-boot.bin"
payload_end:
image_end:
EOF_ASM

${CROSS_COMPILE}gcc -c -nostdlib "$WORK/pregnant-linux-handoff.S" -o "$WORK/pregnant-linux-handoff.o"
${CROSS_COMPILE}ld -Ttext="$STOCK_KERNEL_LOAD" --entry=_start -nostdlib     -o "$WORK/pregnant-linux-handoff.elf" "$WORK/pregnant-linux-handoff.o"
${CROSS_COMPILE}objcopy -O binary "$WORK/pregnant-linux-handoff.elf"     "$OUT/ursusboot-md-${VERSION}.linuximg"

cp u-boot.bin "$OUT/"
python3 - "$OUT/ursusboot-md-${VERSION}.linuximg" u-boot.bin <<'PYQA'
import hashlib, struct, sys
image=open(sys.argv[1],'rb').read()
uboot=open(sys.argv[2],'rb').read()
marker=b'URSPREG1'+struct.pack('<II',0xfeedface,0xcafef00d)
assert image.count(marker)==1
assert len(image) >= 64 + len(uboot)
assert struct.unpack_from('<I',image,56)[0]==0x644d5241
assert struct.unpack_from('<Q',image,16)[0]==len(image)
assert image.endswith(uboot)
print(f'PREGNANT_LINUX_HANDOFF_QA=PASS bytes={len(image)}')
print('PREGNANT_LINUX_HANDOFF_SHA256='+hashlib.sha256(image).hexdigest())
PYQA

sha256sum u-boot.bin "$OUT/ursusboot-md-${VERSION}.linuximg" | tee "$OUT/SHA256SUMS"
printf '%s\n'     "UrsusBoot ${VERSION}"     "MODE=PREGNANT_HANDOFF"     "PERSISTENCE_TARGET=NONE"     "WEB=DISABLED"     "NETWORK_RUNTIME=UNUSED"     "BOOTM_RETURN=RESET_TO_STOCK_AB"     "RUNTIME_DEST=${RUNTIME_DEST}"     "STOCK_KERNEL_LOAD=${STOCK_KERNEL_LOAD}"     "TEXT_BASE=${TEXT_BASE}"     "SOURCE_DATE_EPOCH=${RELEASE_EPOCH}" > "$OUT/PREGNANT-HANDOFF-BUILD_INFO.txt"

echo "MD_PREGNANT_HANDOFF_BUILD=PASS"
echo "Artifacts: $OUT"
