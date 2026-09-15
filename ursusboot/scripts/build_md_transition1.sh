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
PATCH="$ROOT/ursusboot/patches/190-md-transition1-handoff.patch"
OUT="$WORK/out"
RELEASE_EPOCH=1789300800
VERSION="0.1.0-alpha5-UBIUX1-TRANSITION2"
STOCK_KERNEL_LOAD=0x80088000
TEXT_BASE=0x81e00000

for x in tar make gcc perl python3 sha256sum patch; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$CONFIG" "$COMMON_CONFIG" "$BOARD_CONFIG" "$TRANSITION_CONFIG" "$CONFIG_MERGER" "$PATCH"; do
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

make -j"${JOBS:-$(nproc)}"

# Stock-tcboot-compatible handoff image. tcboot continues down its proven
# ARM64 Linux kernel path at 0x80088000. The position-independent shim copies
# TRANSITION U-Boot to its linked TEXT_BASE 0x81e00000 and branches there.
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
for marker in "$VERSION" 'TRANSITION' 'NONE' 'OFFICIAL_OPENWRT' 'URSUS_TRANSITION_WEB_BEGIN'; do
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
    "TRANSITION_ENTRY=ursusdispatch->ursusweb" \
    "ENV_IS_NOWHERE=PASS" \
    "STOCK_INNER_FORMAT=ARM64_LINUX_IMAGE_HANDOFF" \
    "STOCK_KERNEL_LOAD=${STOCK_KERNEL_LOAD}" \
    "TEXT_BASE=${TEXT_BASE}" \
    "SOURCE_DATE_EPOCH=${RELEASE_EPOCH}" > "$OUT/TRANSITION2-BUILD_INFO.txt"

echo "MD_TRANSITION2_BUILD=PASS"
echo "Artifacts: $OUT"
