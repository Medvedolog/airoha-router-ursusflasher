#!/bin/bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/md-transition1"}
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
VERSION="0.1.0-alpha5-UBIUX1-TRANSITION1"
LOAD_ADDR=0x81e00000

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

# Semantic Phase-A policy checks. Kconfig may omit disabled/invisible symbols,
# so do not require literal '# CONFIG_FOO is not set' lines.
grep -q '^CONFIG_ENV_IS_NOWHERE=y$' .config || { echo 'TRANSITION1: ENV_IS_NOWHERE missing' >&2; exit 1; }
for sym in CONFIG_ENV_IS_IN_UBI CONFIG_ENV_REDUNDANT CONFIG_CMD_SAVEENV CONFIG_CMD_ERASEENV; do
    if grep -q "^${sym}=y$" .config; then
        echo "TRANSITION1: forbidden ${sym}=y" >&2
        exit 1
    fi
done
grep -q '^CONFIG_NET_LWIP=y$' .config || { echo 'TRANSITION1: NET_LWIP missing' >&2; exit 1; }
grep -q '^CONFIG_MTD=y$' .config || { echo 'TRANSITION1: MTD missing' >&2; exit 1; }

make -j"${JOBS:-$(nproc)}"

[ -x tools/mkimage ] || { echo "host mkimage missing after U-Boot build" >&2; exit 1; }
tools/mkimage -A arm64 -O u-boot -T standalone -C none -a "$LOAD_ADDR" -e "$LOAD_ADDR" -n "UrsusBoot MD TRANSITION1" -d u-boot.bin "$OUT/ursusboot-md-${VERSION}.uimg"

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map "$OUT/"
[ "$(cat .scmversion)" = "-UrsusBoot-${VERSION}" ]
grep -Fq "#define URSUS_VERSION \"${VERSION}\"" include/ursus_version.h
strings u-boot.bin > "$WORK/u-boot.strings"
for marker in "$VERSION" 'TRANSITION' 'NONE' 'OFFICIAL_OPENWRT' 'TRANSITION_HANDOFF_ONLY'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "missing transition marker: $marker" >&2; exit 1; }
done

python3 - "$OUT/ursusboot-md-${VERSION}.uimg" <<'PYQA'
import binascii, struct, sys
p = sys.argv[1]
d = open(p, 'rb').read()
assert len(d) >= 64
magic,hcrc,ts,size,load,entry,dcrc,os_id,arch,img_type,comp,name = struct.unpack('>7I4B32s', d[:64])
assert magic == 0x27051956
assert size == len(d) - 64
assert load == 0x81e00000 and entry == 0x81e00000
assert os_id == 17 and arch == 22 and img_type == 1 and comp == 0
h = bytearray(d[:64]); struct.pack_into('>I', h, 4, 0)
assert (binascii.crc32(h) & 0xffffffff) == hcrc
assert (binascii.crc32(d[64:]) & 0xffffffff) == dcrc
print(f'TRANSITION_UIMAGE_QA=PASS bytes={len(d)} load=0x{load:x} entry=0x{entry:x}')
PYQA

sha256sum u-boot.bin "$OUT/ursusboot-md-${VERSION}.uimg" | tee "$OUT/SHA256SUMS"
printf '%s\n' "UrsusBoot ${VERSION}" "MODE=TRANSITION" "PERSISTENCE_TARGET=NONE" "FINAL_TARGET=OFFICIAL_OPENWRT" "HANDOFF_ONLY=1" "ENV_IS_NOWHERE=PASS" "LOAD_ADDR=${LOAD_ADDR}" "SOURCE_DATE_EPOCH=${RELEASE_EPOCH}" > "$OUT/TRANSITION1-BUILD_INFO.txt"

echo "MD_TRANSITION1_BUILD=PASS"
echo "Artifacts: $OUT"
