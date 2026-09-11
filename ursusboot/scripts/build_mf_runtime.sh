#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/mf-runtime"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
SEED_CONFIG="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_defconfig"
COMMON_CONFIG="$ROOT/ursusboot/configs/ursusboot-common.cfg"
BOARD_CONFIG="$ROOT/ursusboot/configs/ursusboot-board-mf.cfg"
MODE_CONFIG="$ROOT/ursusboot/configs/ursusboot-runtime-mf.cfg"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
ENVFILE="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_RUNTIME_env"
MF_BASE_TRANSFORM="$ROOT/ursusboot/scripts/mf2_ramreadonly_transform.py"
RUNTIME_ENABLE="$ROOT/ursusboot/scripts/mf_runtime_enable.py"
BOARD_HW="$ROOT/ursusboot/scripts/mf_hwtest8_apply.py"
REPACK="$ROOT/ursusboot/scripts/mf2_repack_from_medve.py"
MEDVE_DIR=${MF2_MEDVE_DIR:-"$ROOT/work/medveflasher-rc35"}
MEDVE_PATCHER="$MEDVE_DIR/data/recovery/recovery-safe-uboot-source/patch_recovery_safe_fip.py"
PRELOADER="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-preloader.bin"
DONOR="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-recovery-safe-bl31-uboot.fip"
OUT="$WORK/out"
VERSION="0.1.0-TEST62"
# By default tie the visible U-Boot build date to the source commit instead of
# the old fixed Sep-09 epoch. CI/repro builds may override explicitly.
BUILD_EPOCH=${MF_RUNTIME_BUILD_EPOCH:-$(git -C "$ROOT" show -s --format=%ct HEAD 2>/dev/null || date +%s)}
BUILD_COMMIT=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)

EXPECTED_PRELOADER_SIZE=118322
EXPECTED_PRELOADER_SHA=c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f
EXPECTED_DONOR_SIZE=339010
EXPECTED_DONOR_SHA=8bfe8870e44923a463a3ed66c8b1906214f5c820fd8c15865c63430185de8bb2

for x in tar make gcc perl python3 sha256sum strings patch stat sed; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$SEED_CONFIG" "$COMMON_CONFIG" "$BOARD_CONFIG" "$MODE_CONFIG" "$CONFIG_MERGER" "$ENVFILE" "$MF_BASE_TRANSFORM" "$RUNTIME_ENABLE" "$BOARD_HW" "$REPACK" "$MEDVE_PATCHER" "$PRELOADER" "$DONOR"; do
    [ -f "$f" ] || { echo "MF runtime build input missing: $f" >&2; exit 1; }
done
[ "$(stat -c %s "$PRELOADER")" = "$EXPECTED_PRELOADER_SIZE" ] || { echo "MF recovery preloader size mismatch" >&2; exit 1; }
[ "$(sha256sum "$PRELOADER" | awk '{print $1}')" = "$EXPECTED_PRELOADER_SHA" ] || { echo "MF recovery preloader SHA mismatch" >&2; exit 1; }
[ "$(stat -c %s "$DONOR")" = "$EXPECTED_DONOR_SIZE" ] || { echo "MF donor size mismatch" >&2; exit 1; }
[ "$(sha256sum "$DONOR" | awk '{print $1}')" = "$EXPECTED_DONOR_SHA" ] || { echo "MF donor SHA mismatch" >&2; exit 1; }

if [ ! -f "$SDK_BUNDLE" ]; then bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null; fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"
cp -a "$WORK/u-boot" "$WORK/u-boot-pristine"

# TEST62 is a board-specialized derivative of the exact TEST61 source snapshot.
python3 "$MF_BASE_TRANSFORM" "$WORK/u-boot"
python3 "$RUNTIME_ENABLE" "$WORK/u-boot" "$WORK/u-boot-pristine"
python3 "$BOARD_HW" "$WORK/u-boot"
printf '%s\n' "-UrsusBoot-${VERSION}" > "$WORK/u-boot/.scmversion"
sed -E -i "s/^#define URSUS_VERSION \"[^\"]+\"/#define URSUS_VERSION \"${VERSION}\"/" "$WORK/u-boot/include/ursus_version.h"
cp "$ENVFILE" "$WORK/u-boot/defenvs/an7583_nokia_xg-040g-mf_runtime_env"
cp "$SEED_CONFIG" "$WORK/u-boot/.config"
python3 "$CONFIG_MERGER" --config "$WORK/u-boot/.config" "$COMMON_CONFIG" "$BOARD_CONFIG" "$MODE_CONFIG"

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$BUILD_EPOCH"

cd "$WORK/u-boot"
make olddefconfig
python3 "$CONFIG_MERGER" --check-only --config .config "$COMMON_CONFIG" "$BOARD_CONFIG" "$MODE_CONFIG"

for sym in CONFIG_TARGET_AN7583 CONFIG_MTD CONFIG_DM_MTD CONFIG_MTD_SPI_NAND CONFIG_MTD_UBI CONFIG_CMD_MTD CONFIG_CMD_UBI CONFIG_CMD_TFTPBOOT CONFIG_NET_LWIP CONFIG_AIROHA_ETH CONFIG_PCS_AIROHA_AN7583 CONFIG_PINCTRL_AIROHA_AN7583 CONFIG_ENV_IS_IN_UBI CONFIG_ENV_REDUNDANT CONFIG_CONSOLE_RECORD; do
    grep -q "^${sym}=y" .config || { echo "Required MF runtime symbol missing: ${sym}" >&2; exit 1; }
done
! grep -q '^CONFIG_ENV_IS_NOWHERE=y' .config || { echo "MF runtime unexpectedly uses ENV_IS_NOWHERE" >&2; exit 1; }
grep -Fq 'CONFIG_ENV_UBI_PART="ubi"' .config
grep -Fq 'CONFIG_ENV_UBI_VOLUME="ubootenv"' .config
grep -Fq 'CONFIG_ENV_UBI_VOLUME_REDUND="ubootenv2"' .config
grep -Fxq 'bootcmd=ursusdispatch' defenvs/an7583_nokia_xg-040g-mf_runtime_env

! grep -q '0x1fa20000' cmd/ursusled.c || { echo "AN7581 SCU raw MMIO survived MF runtime" >&2; exit 1; }
! grep -q '0x1fb58000' cmd/ursusled.c || { echo "MT7531 raw MMIO survived MF runtime" >&2; exit 1; }
! grep -q '^obj-y += ursus_an7581_safe_gpio.o$' drivers/gpio/Makefile || { echo "AN7581 safe GPIO object still linked" >&2; exit 1; }
grep -Fq 'URSUS_MF2_HWTEST8_LED_FIX' drivers/net/airoha_eth.c
grep -Fq 'function = "phy4_led0";' arch/arm/dts/an7583-nokia-xg-040g-mf.dts
grep -Fq 'obj-y += ursusweb.o ursusubi.o ursusdispatch.o ursusupdate.o ursusstock.o ursusled.o' cmd/Makefile

make -j"${JOBS:-$(nproc)}"

python3 "$REPACK" \
    --medve-patcher "$MEDVE_PATCHER" \
    --source "$DONOR" \
    --bl33-raw u-boot.bin \
    --bl33-output u-boot.runtime.lzma \
    --output "ursusboot-mf-${VERSION}-runtime-ram.fip" \
    --report "$OUT/MF-RUNTIME-FIP-REPACK.json"

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.runtime.lzma "ursusboot-mf-${VERSION}-runtime-ram.fip" "$OUT/"
cp .config "$OUT/u-boot.MF_RUNTIME.full.config"
cp defenvs/an7583_nokia_xg-040g-mf_runtime_env "$OUT/MF_RUNTIME.env"
cp "$PRELOADER" "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin"
strings u-boot.bin > "$WORK/u-boot.strings"

for marker in \
    "$VERSION" \
    'Nokia XG-040G-MF' \
    'Airoha AN7583' \
    'URSUS_MF2_HWTEST8_LED_END result=OK' \
    'URSUS_UBI_MIGRATION_ENABLED=1' \
    'URSUS_UBI_UPDATE_ENABLED=1' \
    'URSUS_STOCK_LAYOUT_INSTALL_ENABLED=1' \
    'URSUS_FIP_SELFUPDATE_ENABLED=1' \
    'URSUS_STOCKBOOT_TCBOOT_MF_ARGS pon=00 ethernet=12 wifi1=05 wifi2=05 usb1=00 usb2=02' \
    'ursusstockboot' \
    'nokia,xg-040g-mf' \
    'XG040GMF' \
    'AN7583DT'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "MF runtime binary marker missing: $marker" >&2; exit 1; }
done
for forbidden in \
    'MF2 RAM-only build: persistent operations disabled' \
    'URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE' \
    'URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION' \
    'URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE' \
    'URSUS_MF2_STOCKBRIDGE_DISABLED' \
    'Nokia XG-040G-MD'; do
    ! grep -Fq "$forbidden" "$WORK/u-boot.strings" || { echo "MF runtime forbidden marker survived: $forbidden" >&2; exit 1; }
done

python3 - "$OUT/MF-RUNTIME-FIP-REPACK.json" <<'PYQA'
import json, sys
r=json.load(open(sys.argv[1], encoding='ascii'))
assert r['entry_count'] == 2
assert r['bl31_byte_exact'] is True
assert r['mf2_bl33_roundtrip'] is True
assert r['mf2_bl33_lzma_known_size'] is True
assert r['mf2_bl33_lzma_eopm'] is False
assert r['serial_preserved'] is True
assert r['flags_preserved'] is True
assert r['uuid_flags_preserved'] is True
print('MF_RUNTIME_FIP_QA=PASS sha256=' + r['output_sha256'])
PYQA

sha256sum "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin" "$OUT/ursusboot-mf-${VERSION}-runtime-ram.fip" "$OUT/u-boot.bin" "$OUT/u-boot.runtime.lzma" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
  "UrsusBoot ${VERSION}" \
  "TARGET=Nokia XG-040G-MF / Airoha AN7583" \
  "MODE=PERSISTENT_RUNTIME" \
  "SOURCE=TEST61 exact source snapshot + TEST62 MF fixes" \
  "BUILD_COMMIT=${BUILD_COMMIT}" \
  "SOURCE_DATE_EPOCH=${BUILD_EPOCH}" \
  "BOOTCMD=ursusdispatch" \
  "ENV=UBI_REDUNDANT" \
  "OPENWRT_INSTALL=ENABLED" \
  "UBI_MIGRATION=ENABLED" \
  "UBI_UPDATE=ENABLED" \
  "STOCK_BOOT=ENABLED_SERDES_COMPLETE" \
  "FIP_SELFUPDATE=ENABLED_DEVICE_DERIVED_CANDIDATE_REQUIRED_BY_HOST" \
  "LAN234_LED=HWTEST8_NATIVE_C45" \
  "COMMON_KCONFIG=PASS" \
  "BOARD_KCONFIG=MF" \
  "MODE_KCONFIG=RUNTIME" > "$OUT/MF-RUNTIME-BUILD-INFO.txt"

echo "MF_RUNTIME_BUILD=PASS version=${VERSION} commit=${BUILD_COMMIT} epoch=${BUILD_EPOCH}"
echo "Artifacts: $OUT"
