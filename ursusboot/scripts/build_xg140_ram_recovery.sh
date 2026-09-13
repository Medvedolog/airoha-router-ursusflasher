#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/xg140-ram-recovery"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
DTS_PATCH="$ROOT/ursusboot/patches/140-xg140-ram1-dts.patch"
OUT="$WORK/out"

command -v tar >/dev/null
command -v make >/dev/null
command -v gcc >/dev/null
command -v python3 >/dev/null
command -v sha256sum >/dev/null
command -v patch >/dev/null

if [ ! -f "$SDK_BUNDLE" ]; then
  bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null
fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }
[ -f "$DTS_PATCH" ] || { echo "XG140 UrsusBoot DTS patch missing" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"
SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }

TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
export URSUS_SDK_ROOT="$SDK_ROOT"
export STAGING_DIR="$SDK_ROOT/staging_dir"
export STAGING_DIR_HOST="$HOST"
export BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl-
export SOURCE_DATE_EPOCH=1789344000

cd "$WORK/u-boot"

# Use a dedicated U-Boot DTS derived from the proven AN7581 XG-040G-MD
# U-Boot device tree, with only the XG-140G-MD board deltas and the exact
# stock NAND map observed on the physical XG140GMC2P5G. Do not feed the
# Linux/OpenWrt DTS directly to U-Boot.
patch -p1 < "$DTS_PATCH"
XG_DTS="dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts"
XG_UBOOT_DTSI="arch/arm/dts/an7581-bell-xg-140g-md-u-boot.dtsi"
test -s "$XG_DTS"
test -s "$XG_UBOOT_DTSI"

grep -q 'model = "Bell XG-140G-MD"' "$XG_DTS"
grep -q 'reg = <0x0 0x80000000 0x0 0x20000000>;' "$XG_DTS"
grep -q 'label = "nsb_master"' "$XG_DTS"
grep -q 'reg = <0x000c0000 0x02880000>;' "$XG_DTS"
grep -q 'label = "nsb_slave"' "$XG_DTS"
grep -q 'reg = <0x02940000 0x02880000>;' "$XG_DTS"

cp "$CONFIG" .config
sed -i 's#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-nokia-xg-040g-md"#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-bell-xg-140g-md"#' .config
sed -i 's#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-nokia-xg-040g-md.dtb"#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-bell-xg-140g-md.dtb"#' .config

# RAM1 is a chain-loaded recovery environment. It must not persist U-Boot env.
sed -i 's/^CONFIG_ENV_IS_IN_UBI=y/# CONFIG_ENV_IS_IN_UBI is not set/' .config
sed -i 's/^# CONFIG_ENV_IS_NOWHERE is not set/CONFIG_ENV_IS_NOWHERE=y/' .config

# Retarget only board identity / supported-device checks. AN7581 stays AN7581.
while IFS= read -r -d '' f; do
  sed -i \
    -e 's/Nokia XG-040G-MD/Bell XG-140G-MD/g' \
    -e 's/nokia,xg-040g-md/bell,xg-140g-md/g' \
    "$f"
done < <(grep -RIlZ --exclude-dir=.git -e 'Nokia XG-040G-MD' -e 'nokia,xg-040g-md' cmd include board drivers defenvs 2>/dev/null || true)

if [ -f include/ursus_version.h ]; then
  sed -i 's/#define URSUS_VERSION ".*"/#define URSUS_VERSION "0.1.0-xg140-ram1"/' include/ursus_version.h
fi
printf '%s\n' '-UrsusBoot-0.1.0-xg140-ram1' > .scmversion

make olddefconfig
make -j"${JOBS:-$(nproc)}"

cp -av u-boot.bin u-boot u-boot.map u-boot.sym System.map "$OUT/"
[ -f u-boot.dtb ] && cp -av u-boot.dtb "$OUT/" || true
cp -av "$XG_DTS" "$OUT/"
cp -av "$XG_UBOOT_DTSI" "$OUT/"
cp -av .config "$OUT/u-boot.xg140-ram.config"

MKIMAGE=$(command -v mkimage || true)
if [ -z "$MKIMAGE" ] && [ -x tools/mkimage ]; then MKIMAGE="$PWD/tools/mkimage"; fi
if [ -n "$MKIMAGE" ]; then
  "$MKIMAGE" -A arm64 -O u-boot -T standalone -C none \
    -a 0x81e00000 -e 0x81e00000 \
    -n 'UrsusBoot XG140 RAM recovery' \
    -d u-boot.bin "$OUT/ursusboot-xg140-ram.uimg" || true
fi

(
  cd "$OUT"
  sha256sum ./* > SHA256SUMS.txt
)
cat > "$OUT/TESTING.txt" <<'EOF'
UrsusBoot XG-140G-MD RAM recovery prototype

SAFETY CONTRACT
- Bell/Nokia XG-140G-MD / XG140GMC2P5G / AN7581DT only.
- Stock tcboot in mtd0 is NOT replaced during the RAM1 hardware gate.
- tcboot has already initialized the real 512 MiB DDR4-2666.
- U-Boot environment is CONFIG_ENV_IS_NOWHERE in RAM1.
- Do not saveenv, erase or write mtd0 during the RAM1 gate.

DTS BASIS
- AN7581 U-Boot structure follows the proven Nokia XG-040G-MD U-Boot DTS.
- XG140 deltas are taken from the booted XG140 OpenWrt DTS and physical tests.
- RAM is fixed to 512 MiB.
- Stock NAND map is explicit: bootloader, romfile, nsb_master, nsb_slave,
  bosa, ri, flag, flagback, config, data, oopsfs, log.
- First network path keeps the proven AN7581 GDM1 recovery path. EN8811H/GDM4
  can be enabled after the first RAM-only Ethernet/Web acceptance gate.

PRIMARY tcboot experiment
1. Stop tcboot autoboot.
2. XMODEM-load u-boot.bin to 0x81e00000.
3. Execute: go 0x81e00000
4. Expect UrsusBoot 0.1.0-xg140-ram1 on UART.
5. Check mtd list before any writer is enabled.
6. Check HTTP at 192.168.1.1:80.

Only after UART + NAND map + Ethernet/Web all pass do we build the persistent
XG140 UrsusBoot installer that replaces tcboot. The stock-layout sysupgrade is
not considered bootable by tcboot.
EOF

echo "XG140_URSUSBOOT_RAM_BUILD=PASS"
echo "Artifacts: $OUT"
