#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/xg140-native-profile"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
SEED_CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
PROFILE="xg140-md"
PROFILE_REGISTRY="$ROOT/ursusboot/configs/board-profiles.json"
PROFILE_RESOLVER="$ROOT/ursusboot/scripts/resolve_board_profile.py"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
DERIVE="$ROOT/ursusboot/scripts/xg140_md_derive.py"
DTS_PATCH="$ROOT/ursusboot/patches/140-xg140-ram1-dts.patch"
OUT="$WORK/out"
VERSION="0.1.0-xg140-profile1"
BUILD_EPOCH=${XG140_BUILD_EPOCH:-$(git -C "$ROOT" show -s --format=%ct HEAD 2>/dev/null || date +%s)}
BUILD_COMMIT=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)

for x in tar make gcc perl python3 sha256sum strings patch stat sed; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$SEED_CONFIG" "$PROFILE_REGISTRY" "$PROFILE_RESOLVER" "$CONFIG_MERGER" "$DERIVE" "$DTS_PATCH"; do
    [ -f "$f" ] || { echo "XG140 native profile build input missing: $f" >&2; exit 1; }
done
mapfile -t PROFILE_CONFIGS < <(python3 "$PROFILE_RESOLVER" --registry "$PROFILE_REGISTRY" --profile "$PROFILE" --config-dir "$ROOT/ursusboot/configs")
[ "${#PROFILE_CONFIGS[@]}" -ge 3 ] || { echo "UrsusBoot profile did not resolve: $PROFILE" >&2; exit 1; }

if [ ! -f "$SDK_BUNDLE" ]; then bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null; fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"

cd "$WORK/u-boot"
patch -p1 < "$DTS_PATCH"
python3 "$DERIVE" "$WORK/u-boot"
cp "$SEED_CONFIG" .config
python3 "$CONFIG_MERGER" --config .config "${PROFILE_CONFIGS[@]}"

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$BUILD_EPOCH"

make olddefconfig
python3 "$CONFIG_MERGER" --check-only --config .config "${PROFILE_CONFIGS[@]}"

for sym in CONFIG_TARGET_AN7581 CONFIG_MTD CONFIG_DM_MTD CONFIG_MTD_SPI_NAND CONFIG_CMD_MTD CONFIG_CMD_TFTPBOOT CONFIG_CMD_WGET CONFIG_NET_LWIP CONFIG_AIROHA_ETH CONFIG_PCS_AIROHA_AN7581 CONFIG_PINCTRL_AIROHA_AN7581 CONFIG_ENV_IS_NOWHERE CONFIG_CONSOLE_RECORD; do
    grep -q "^${sym}=y" .config || { echo "Required XG140 profile symbol missing: ${sym}" >&2; exit 1; }
done
! grep -q '^CONFIG_ENV_IS_IN_UBI=y' .config || { echo "XG140 profile must not own vendor env via UBI" >&2; exit 1; }
grep -Fq 'CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-bell-xg-140g-md"' .config
grep -Fq 'CONFIG_DEFAULT_FDT_FILE="airoha/an7581-bell-xg-140g-md.dtb"' .config

grep -q 'model = "Bell XG-140G-MD"' dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts
grep -q 'label = "nsb_master"' dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts
grep -q 'label = "nsb_slave"' dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts
grep -q 'label = "flag"' dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts
grep -q 'label = "flagback"' dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts

make -j"${JOBS:-$(nproc)}"

gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma "$OUT/"
[ -f u-boot.dtb ] && cp u-boot.dtb "$OUT/" || true
cp .config "$OUT/u-boot.XG140_PROFILE.full.config"
cp dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts "$OUT/"
cp arch/arm/dts/an7581-bell-xg-140g-md-u-boot.dtsi "$OUT/"
cp "$ROOT/ursusflasher/tools/repack_xg140_native_fip.py" "$OUT/"

strings u-boot.bin > "$WORK/u-boot.strings"
for marker in \
    "$VERSION" \
    'Bell XG-140G-MD' \
    'bell,xg-140g-md' \
    'XG140GMC2P5G' \
    'bootcmd=ursusdispatch' \
    'ursusstockboot'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "XG140 profile binary marker missing: $marker" >&2; exit 1; }
done
for forbidden in \
    'Nokia XG-040G-MD' \
    'nokia,xg-040g-md' \
    'XG040GMC2P5G' \
    'bootcmd=ursusweb;true'; do
    ! grep -Fq "$forbidden" "$WORK/u-boot.strings" || { echo "XG140 profile forbidden marker survived: $forbidden" >&2; exit 1; }
done

sha256sum "$OUT/u-boot.bin" "$OUT/u-boot.lzma" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
  "UrsusBoot ${VERSION}" \
  "TARGET=Bell/Nokia XG-140G-MD / Airoha AN7581" \
  "PROFILE=${PROFILE}" \
  "SOC=AN7581" \
  "DERIVATION=md-derived" \
  "MODE=PERSISTENT_NATIVE_BL33" \
  "ENV=NOWHERE_VENDOR_ENV_PRESERVED" \
  "BOOTCMD=ursusdispatch" \
  "STOCK_BOOT_CORE=MD_DERIVED" \
  "FIP=DEVICE_NATIVE_DONOR_REQUIRED" \
  "FIP_REPACKER=repack_xg140_native_fip.py" \
  "BUILD_COMMIT=${BUILD_COMMIT}" \
  "SOURCE_DATE_EPOCH=${BUILD_EPOCH}" \
  "PROFILE_KCONFIG=PASS" > "$OUT/XG140-PROFILE-BUILD-INFO.txt"

echo "XG140_NATIVE_PROFILE_BUILD=PASS version=${VERSION} profile=${PROFILE} commit=${BUILD_COMMIT} epoch=${BUILD_EPOCH}"
echo "Artifacts: $OUT"
