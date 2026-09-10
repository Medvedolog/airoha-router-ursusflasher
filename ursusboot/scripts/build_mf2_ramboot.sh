#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/mf-ramboot"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_defconfig"
COMMON_CONFIG="$ROOT/ursusboot/configs/ursusboot-common.cfg"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
ENVFILE="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_env"
TRANSFORM="$ROOT/ursusboot/scripts/mf2_ramreadonly_transform.py"
REPACK="$ROOT/ursusboot/scripts/mf2_repack_from_medve.py"
MEDVE_DIR=${MF2_MEDVE_DIR:-"$ROOT/work/medveflasher-rc35"}
MEDVE_PATCHER="$MEDVE_DIR/data/recovery/recovery-safe-uboot-source/patch_recovery_safe_fip.py"
PRELOADER="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-preloader.bin"
DONOR="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-recovery-safe-bl31-uboot.fip"
OUT="$WORK/out"
VERSION="0.1.0-TEST61"
RELEASE_EPOCH=1788948000

EXPECTED_PRELOADER_SIZE=118322
EXPECTED_PRELOADER_SHA=c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f
EXPECTED_DONOR_SIZE=339010
EXPECTED_DONOR_SHA=8bfe8870e44923a463a3ed66c8b1906214f5c820fd8c15865c63430185de8bb2

for x in tar make gcc perl python3 sha256sum strings patch stat sed; do command -v "$x" >/dev/null; done
for f in "$COMMON_CONFIG" "$CONFIG_MERGER"; do [ -f "$f" ] || { echo "shared UrsusBoot config input missing: $f" >&2; exit 1; }; done
[ -f "$SOURCE_BUNDLE" ] || { echo "TEST61 source snapshot missing" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "MF config missing" >&2; exit 1; }
[ -f "$ENVFILE" ] || { echo "MF env missing" >&2; exit 1; }
[ -f "$REPACK" ] || { echo "MF Medve repack adapter missing" >&2; exit 1; }
[ -f "$MEDVE_PATCHER" ] || { echo "Pinned MedveFlasher FIP parser missing: $MEDVE_PATCHER" >&2; exit 1; }
[ -f "$PRELOADER" ] || { echo "Pinned MedveFlasher MF UART preloader missing: $PRELOADER" >&2; exit 1; }
[ -f "$DONOR" ] || { echo "Pinned MedveFlasher MF SAFE FIP missing: $DONOR" >&2; exit 1; }

[ "$(stat -c %s "$PRELOADER")" = "$EXPECTED_PRELOADER_SIZE" ] || { echo "MF preloader size mismatch" >&2; exit 1; }
[ "$(sha256sum "$PRELOADER" | awk '{print $1}')" = "$EXPECTED_PRELOADER_SHA" ] || { echo "MF preloader SHA256 mismatch" >&2; exit 1; }
[ "$(stat -c %s "$DONOR")" = "$EXPECTED_DONOR_SIZE" ] || { echo "MF SAFE donor size mismatch" >&2; exit 1; }
[ "$(sha256sum "$DONOR" | awk '{print $1}')" = "$EXPECTED_DONOR_SHA" ] || { echo "MF SAFE donor SHA256 mismatch" >&2; exit 1; }

echo "MF_MEDVE_INPUTS=PASS commit=342cac4cb99a924f3d83eb8e4b5259490377704e"

if [ ! -f "$SDK_BUNDLE" ]; then bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null; fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"

# Start from the hardware-proven MF RAM transform. High-level FIP/UBI writers
# remain rejected, but the recovery console deliberately exposes loadx + raw
# mtd so a brick can be restored even when no valid partition layout exists.
python3 "$TRANSFORM" "$WORK/u-boot"
printf '%s\n' "-UrsusBoot-${VERSION}" > "$WORK/u-boot/.scmversion"
sed -E -i "s/^#define URSUS_VERSION \"[^\"]+\"/#define URSUS_VERSION \"${VERSION}\"/" "$WORK/u-boot/include/ursus_version.h"
cp "$ENVFILE" "$WORK/u-boot/defenvs/an7583_nokia_xg-040g-mf_env"
cp "$CONFIG" "$WORK/u-boot/.config"
python3 "$CONFIG_MERGER" --config "$WORK/u-boot/.config" "$COMMON_CONFIG"

# Source-level board separation before compiler/linker can hide dead MD code.
! grep -q '0x1fa20000' "$WORK/u-boot/cmd/ursusled.c" || { echo "AN7581 SCU raw MMIO survived MF transform" >&2; exit 1; }
! grep -q '0x1fb58000' "$WORK/u-boot/cmd/ursusled.c" || { echo "MT7531 raw MMIO survived MF transform" >&2; exit 1; }
! grep -q '^obj-y += ursus_an7581_safe_gpio.o$' "$WORK/u-boot/drivers/gpio/Makefile" || { echo "AN7581 safe GPIO object still linked in MF" >&2; exit 1; }
grep -Fq '#define LED_STATUS_RED "red:wan"' "$WORK/u-boot/cmd/ursusled.c" || { echo "MF red LED DT label missing" >&2; exit 1; }
grep -Fq '#define LED_USB1_GREEN "green:usb-1"' "$WORK/u-boot/cmd/ursusled.c" || { echo "MF USB1 LED DT label missing" >&2; exit 1; }
grep -Fq '#define LED_USB2_GREEN "green:usb-2"' "$WORK/u-boot/cmd/ursusled.c" || { echo "MF USB2 LED DT label missing" >&2; exit 1; }

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"

cd "$WORK/u-boot"
make olddefconfig
python3 "$CONFIG_MERGER" --check-only --config .config "$COMMON_CONFIG"

# Recovery contract: MTD/SPI-NAND drivers, XMODEM receive and the generic raw
# MTD command are intentionally available from the UART shell. Destructive
# high-level UrsusBoot/UBI entrypoints and persistent environment stay blocked.
for sym in CONFIG_CMD_MTD_MARKBAD CONFIG_CMD_MTD_NAND_WRITE_TEST CONFIG_CMD_UBI CONFIG_CMD_UBI_RENAME CONFIG_CMD_ERASEENV CONFIG_CMD_NAND CONFIG_CMD_SF CONFIG_CMD_PXE CONFIG_ENV_IS_IN_MTD CONFIG_ENV_IS_IN_UBI; do
    if grep -q "^${sym}=y" .config; then
        echo "MF RAM recovery config violation: ${sym}=y" >&2
        exit 1
    fi
done
for sym in CONFIG_TARGET_AN7583 CONFIG_MTD CONFIG_DM_MTD CONFIG_MTD_SPI_NAND CONFIG_CMD_MTD CONFIG_CMD_LOADB CONFIG_CMD_TFTPBOOT CONFIG_NET_LWIP CONFIG_AIROHA_ETH CONFIG_PCS_AIROHA_AN7583 CONFIG_PINCTRL_AIROHA_AN7583 CONFIG_ENV_IS_NOWHERE CONFIG_CONSOLE_RECORD; do
    grep -q "^${sym}=y" .config || { echo "Required MF recovery symbol missing: ${sym}" >&2; exit 1; }
done

grep -Fq 'CONFIG_DEFAULT_DEVICE_TREE="an7583-nokia-xg-040g-mf"' .config || { echo "wrong MF DTS" >&2; exit 1; }
grep -Fxq 'bootcmd=ursusweb' defenvs/an7583_nokia_xg-040g-mf_env || { echo "MF bootcmd is not ursusweb" >&2; exit 1; }
! grep -Eq 'saveenv|mtd (erase|write)|ubi (write|create|remove|rename|detach)' defenvs/an7583_nokia_xg-040g-mf_env || { echo "persistent command leaked into MF default env" >&2; exit 1; }

make -j"${JOBS:-$(nproc)}"

# Keep the exact hardware-tested recovery-safe BL31 donor. Only BL33 is rebuilt.
python3 "$REPACK" \
    --medve-patcher "$MEDVE_PATCHER" \
    --source "$DONOR" \
    --bl33-raw u-boot.bin \
    --bl33-output u-boot.lzma \
    --output "ursusboot-mf-${VERSION}-ram.fip" \
    --report "$OUT/MF-FIP-REPACK.json"

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma "ursusboot-mf-${VERSION}-ram.fip" "$OUT/"
cp "$PRELOADER" "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin"
cp .config "$OUT/u-boot.MF_RAM.full.config"
cp defenvs/an7583_nokia_xg-040g-mf_env "$OUT/MF_RAM.env"

[ "$(cat .scmversion)" = "-UrsusBoot-${VERSION}" ] || { echo "MF .scmversion mismatch" >&2; exit 1; }
grep -Fq "#define URSUS_VERSION \"${VERSION}\"" include/ursus_version.h || { echo "MF version header mismatch" >&2; exit 1; }
strings u-boot.bin > "$WORK/u-boot.strings"
for marker in "$VERSION" 'Nokia XG-040G-MF' 'Airoha AN7583' 'URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE' 'URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE' 'URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION' 'URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "MF binary marker missing: $marker" >&2; exit 1; }
done
if grep -Fq 'Nokia XG-040G-MD' "$WORK/u-boot.strings"; then
    echo "MD board identity leaked into MF binary" >&2
    exit 1
fi
for symbol in ursus_scu_read ursus_scu_write ursus_lanphy_c45_write ursus_lanphy_c45_read ursus_an7581_safe_gpio; do
    if grep -Fq "$symbol" u-boot.sym; then
        echo "MD-only symbol leaked into MF link: $symbol" >&2
        exit 1
    fi
done

python3 - "$OUT/MF-FIP-REPACK.json" <<'PYQA'
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
print('MF_FIP_QA=PASS output_sha256=' + r['output_sha256'] + ' output_size=' + str(r['output_size']))
PYQA

sha256sum "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin" "$OUT/ursusboot-mf-${VERSION}-ram.fip" "$OUT/u-boot.bin" "$OUT/u-boot.lzma" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
  "UrsusBoot ${VERSION}" \
  "TARGET=Nokia XG-040G-MF / Airoha AN7583" \
  "MODE=RAM_RECOVERY" \
  "SOURCE=TEST61 exact source snapshot" \
  "OPENWRT_BASELINE=3d1645ee26d6a2e20be71d7fa1716721bac78e53" \
  "MEDVEFLASHER_COMMIT=342cac4cb99a924f3d83eb8e4b5259490377704e" \
  "MEDVE_FIP_PARSER=data/recovery/recovery-safe-uboot-source/patch_recovery_safe_fip.py" \
  "MEDVE_FIP_COMPRESSOR=lzma_encode+lzma1ext_noeopm.c" \
  "UART_PRELOADER_SHA256=${EXPECTED_PRELOADER_SHA}" \
  "DONOR_SAFE_FIP_SHA256=${EXPECTED_DONOR_SHA}" \
  "COMMON_KCONFIG=PASS" \
  "RAW_MTD_CLI=ENABLED" \
  "SERIAL_XMODEM_LOAD=ENABLED" \
  "TFTP_CLIENT=ENABLED" \
  "HIGH_LEVEL_FIP_UBI_WRITERS=REJECTED" \
  "HTTP_POST=REJECTED" \
  "ENV=NOWHERE" \
  "RECOVERY_PURPOSE=diagnostics,backup,raw-debrick" > "$OUT/MF-BUILD_INFO.txt"

echo "MF_RAMBOOT_BUILD=PASS"
echo "Artifacts: $OUT"
