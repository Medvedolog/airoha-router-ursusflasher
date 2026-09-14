#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PROFILE="xg140-md"
ROLE=${URSUS_RUNTIME_ROLE:-persistent}
case "$ROLE" in
    persistent|ram-recovery) ;;
    *) echo "Unsupported XG140 runtime role: $ROLE" >&2; exit 2 ;;
esac
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/xg140-native-profile-$ROLE"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
SEED_CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
PROFILE_REGISTRY="$ROOT/ursusboot/configs/board-profiles.json"
PROFILE_RESOLVER="$ROOT/ursusboot/scripts/resolve_board_profile.py"
CONFIG_MERGER="$ROOT/ursusboot/scripts/apply_kconfig_fragment.py"
POLICY_APPLIER="$ROOT/ursusboot/scripts/apply_board_policy.py"
ROLE_APPLIER="$ROOT/ursusboot/scripts/apply_runtime_role.py"
DERIVE="$ROOT/ursusboot/scripts/xg140_md_derive.py"
DTS_PATCH="$ROOT/ursusboot/patches/140-xg140-ram1-dts.patch"
OUT="$WORK/out"
VERSION="0.1.0-xg140-profile1"
BUILD_EPOCH=${XG140_BUILD_EPOCH:-$(git -C "$ROOT" show -s --format=%ct HEAD 2>/dev/null || date +%s)}
BUILD_COMMIT=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
OLD_MD_IDENTITY='Nokia XG-040G-MD'

if [ "$ROLE" = persistent ]; then
    EXPECT_BOOTCMD='bootcmd=ursusdispatch'
    FORBID_BOOTCMD='bootcmd=ursusweb;true'
    MODE='PERSISTENT_NATIVE_BL33'
else
    EXPECT_BOOTCMD='bootcmd=ursusweb;true'
    FORBID_BOOTCMD='bootcmd=ursusdispatch'
    MODE='RAM_RECOVERY_WEBFAILSAFE'
fi

for x in tar make gcc perl python3 sha256sum strings patch stat sed; do command -v "$x" >/dev/null; done
for f in "$SOURCE_BUNDLE" "$SEED_CONFIG" "$PROFILE_REGISTRY" "$PROFILE_RESOLVER" "$CONFIG_MERGER" "$POLICY_APPLIER" "$ROLE_APPLIER" "$DERIVE" "$DTS_PATCH"; do
    [ -f "$f" ] || { echo "XG140 native profile build input missing: $f" >&2; exit 1; }
done
mapfile -t PROFILE_CONFIGS < <(python3 "$PROFILE_RESOLVER" --registry "$PROFILE_REGISTRY" --profile "$PROFILE" --role "$ROLE" --config-dir "$ROOT/ursusboot/configs")
[ "${#PROFILE_CONFIGS[@]}" -ge 3 ] || { echo "UrsusBoot profile did not resolve: $PROFILE/$ROLE" >&2; exit 1; }
RESOLVED_ROLE=$(python3 "$PROFILE_RESOLVER" --registry "$PROFILE_REGISTRY" --profile "$PROFILE" --role "$ROLE" --field runtime_role)
[ "$RESOLVED_ROLE" = "$ROLE" ] || { echo "Runtime role resolver mismatch: requested=$ROLE resolved=$RESOLVED_ROLE" >&2; exit 1; }
POLICY_HEADER=$(python3 "$PROFILE_RESOLVER" --registry "$PROFILE_REGISTRY" --profile "$PROFILE" --role "$ROLE" --field board_policy_header)
BOARD_POLICY="$ROOT/ursusboot/board-policies/$POLICY_HEADER"
[ -f "$BOARD_POLICY" ] || { echo "UrsusBoot board policy missing: $BOARD_POLICY" >&2; exit 1; }

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
python3 "$POLICY_APPLIER" "$WORK/u-boot" "$BOARD_POLICY"
python3 "$ROLE_APPLIER" "$WORK/u-boot" --role "$ROLE"
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
grep -Fq '#define URSUS_BOARD_POLICY_ID              "xg140-md"' include/ursus_board_policy.h
grep -Fq '#define URSUS_BOARD_ALLOW_UBI_BOOT          0' include/ursus_board_policy.h
grep -Fq '#define URSUS_BOARD_APPEND_SERDES_ARGS(dst, cap) 0' include/ursus_board_policy.h
grep -Fq "#define URSUS_RUNTIME_ROLE_ID \"$ROLE\"" include/ursus_runtime_role.h
grep -Fq "#define URSUS_RUNTIME_BOOTCMD \"$EXPECT_BOOTCMD\"" include/ursus_runtime_role.h

# Identity must also remain clean after Kconfig generated headers/environment are created.
if grep -RIlF --exclude-dir=.git -- "$OLD_MD_IDENTITY" . > "$WORK/md-identity-prebuild-files.txt"; then
    echo "XG140_PREBUILD_MD_IDENTITY_LEAK=1" >&2
    cat "$WORK/md-identity-prebuild-files.txt" >&2
    while IFS= read -r f; do grep -nF -- "$OLD_MD_IDENTITY" "$f" >&2 || true; done < "$WORK/md-identity-prebuild-files.txt"
    exit 1
fi

echo "XG140_PREBUILD_IDENTITY=PASS role=$ROLE"
make -j"${JOBS:-$(nproc)}"

gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma "$OUT/"
[ -f u-boot.dtb ] && cp u-boot.dtb "$OUT/" || true
cp .config "$OUT/u-boot.XG140_PROFILE.full.config"
cp include/ursus_board_policy.h "$OUT/"
cp include/ursus_runtime_role.h "$OUT/"
cp dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts "$OUT/"
cp arch/arm/dts/an7581-bell-xg-140g-md-u-boot.dtsi "$OUT/"
cp "$ROOT/ursusflasher/tools/repack_xg140_native_fip.py" "$OUT/"

strings u-boot.bin > "$WORK/u-boot.strings"
for marker in \
    "$VERSION" \
    'Bell XG-140G-MD' \
    'bell,xg-140g-md' \
    'XG140GMC2P5G' \
    'URSUS_BOARD_PROFILE=xg140-md' \
    'URSUS_STOCKBOOT_TCBOOT_XG140_ARGS source=vendor_env' \
    "$EXPECT_BOOTCMD" \
    'ursusstockboot'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "XG140 profile binary marker missing role=$ROLE: $marker" >&2; exit 1; }
done
for forbidden in \
    'Nokia XG-040G-MD' \
    'nokia,xg-040g-md' \
    'XG040GMC2P5G' \
    'URSUS_STOCKBOOT_TCBOOT_MD_ARGS' \
    "$FORBID_BOOTCMD"; do
    if grep -Fq "$forbidden" "$WORK/u-boot.strings"; then
        echo "XG140 profile forbidden marker survived role=$ROLE: $forbidden" >&2
        echo "=== binary offsets ===" >&2
        strings -t x u-boot.bin | grep -F "$forbidden" >&2 || true
        echo "=== linked ELF offsets ===" >&2
        strings -t x u-boot | grep -F "$forbidden" >&2 || true
        echo "=== object producers ===" >&2
        while IFS= read -r -d '' obj; do
            if strings "$obj" | grep -Fq "$forbidden"; then
                echo "$obj" >&2
                strings -t x "$obj" | grep -F "$forbidden" >&2 || true
            fi
        done < <(find . -type f \( -name '*.o' -o -name '*.a' -o -name '*.dtb' \) -print0)
        echo "=== post-build text/generated sources ===" >&2
        grep -RInF --binary-files=without-match --exclude-dir=.git -- "$forbidden" . >&2 || true
        exit 1
    fi
done

sha256sum "$OUT/u-boot.bin" "$OUT/u-boot.lzma" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
  "UrsusBoot ${VERSION}" \
  "TARGET=Bell/Nokia XG-140G-MD / Airoha AN7581" \
  "PROFILE=${PROFILE}" \
  "RUNTIME_ROLE=${ROLE}" \
  "SOC=AN7581" \
  "DERIVATION=md-derived" \
  "BOARD_POLICY=${POLICY_HEADER}" \
  "MODE=${MODE}" \
  "ENV=NOWHERE_VENDOR_ENV_PRESERVED" \
  "BOOTCMD=${EXPECT_BOOTCMD#bootcmd=}" \
  "STOCK_BOOT_CORE=COMMON_MD_DERIVED" \
  "STOCK_SERDES=VENDOR_ENV_NO_MD_OVERRIDE" \
  "UBI_AUTODETECT=DISABLED_BY_BOARD_POLICY" \
  "FIP=DEVICE_NATIVE_DONOR_REQUIRED_FOR_PERSISTENT" \
  "FIP_REPACKER=repack_xg140_native_fip.py" \
  "BUILD_COMMIT=${BUILD_COMMIT}" \
  "SOURCE_DATE_EPOCH=${BUILD_EPOCH}" \
  "PROFILE_KCONFIG=PASS" > "$OUT/XG140-PROFILE-BUILD-INFO.txt"

echo "XG140_NATIVE_PROFILE_BUILD=PASS version=${VERSION} profile=${PROFILE} role=${ROLE} policy=${POLICY_HEADER} commit=${BUILD_COMMIT} epoch=${BUILD_EPOCH}"
echo "Artifacts: $OUT"
