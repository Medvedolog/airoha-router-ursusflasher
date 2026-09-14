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
patch -p1 < "$DTS_PATCH"
XG_DTS="dts/upstream/src/arm64/airoha/an7581-bell-xg-140g-md.dts"
XG_UBOOT_DTSI="arch/arm/dts/an7581-bell-xg-140g-md-u-boot.dtsi"
test -s "$XG_DTS"
test -s "$XG_UBOOT_DTSI"

grep -q 'model = "Bell XG-140G-MD"' "$XG_DTS"
grep -q 'reg = <0x0 0x80000000 0x0 0x20000000>;' "$XG_DTS"
grep -q 'label = "bootloader"' "$XG_DTS"
grep -q 'reg = <0x00000000 0x00080000>;' "$XG_DTS"
grep -q 'label = "nsb_master"' "$XG_DTS"
grep -q 'reg = <0x000c0000 0x02880000>;' "$XG_DTS"
grep -q 'label = "nsb_slave"' "$XG_DTS"
grep -q 'reg = <0x02940000 0x02880000>;' "$XG_DTS"

cp "$CONFIG" .config
sed -i 's#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-nokia-xg-040g-md"#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-bell-xg-140g-md"#' .config
sed -i 's#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-nokia-xg-040g-md.dtb"#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-bell-xg-140g-md.dtb"#' .config
sed -i 's/^CONFIG_ENV_IS_IN_UBI=y/# CONFIG_ENV_IS_IN_UBI is not set/' .config
sed -i 's/^# CONFIG_ENV_IS_NOWHERE is not set/CONFIG_ENV_IS_NOWHERE=y/' .config

while IFS= read -r -d '' f; do
  sed -i \
    -e 's/Nokia XG-040G-MD/Bell XG-140G-MD/g' \
    -e 's/nokia,xg-040g-md/bell,xg-140g-md/g' \
    "$f"
done < <(grep -RIlZ --exclude-dir=.git -e 'Nokia XG-040G-MD' -e 'nokia,xg-040g-md' cmd include board drivers defenvs 2>/dev/null || true)

if [ -f include/ursus_version.h ]; then
  sed -i 's/#define URSUS_VERSION ".*"/#define URSUS_VERSION "0.1.0-xg140-native1"/' include/ursus_version.h
fi
printf '%s\n' '-UrsusBoot-0.1.0-xg140-native1' > .scmversion

make olddefconfig
make -j"${JOBS:-$(nproc)}"

# Produce only the board-specific BL33 payload here. The persistent FIP is built
# on the operator PC from that unit's own stock mtd0 backup by the dedicated
# XG140 native repacker packaged by CI. Do not export the legacy MD/MF checksum
# repacker from the U-Boot source tree.
gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576

cp -av u-boot.bin u-boot u-boot.map u-boot.sym System.map u-boot.lzma "$OUT/"
[ -f u-boot.dtb ] && cp -av u-boot.dtb "$OUT/" || true
cp -av "$XG_DTS" "$OUT/"
cp -av "$XG_UBOOT_DTSI" "$OUT/"
cp -av .config "$OUT/u-boot.xg140-native.config"

MKIMAGE=$(command -v mkimage || true)
if [ -z "$MKIMAGE" ] && [ -x tools/mkimage ]; then MKIMAGE="$PWD/tools/mkimage"; fi
if [ -n "$MKIMAGE" ]; then
  "$MKIMAGE" -A arm64 -O u-boot -T standalone -C none \
    -a 0x81e00000 -e 0x81e00000 \
    -n 'UrsusBoot XG140 RAM recovery' \
    -d u-boot.bin "$OUT/ursusboot-xg140-ram.uimg" || true
fi

cat > "$OUT/TESTING.txt" <<'EOF'
UrsusBoot XG-140G-MD NATIVE1

TARGET
Bell/Nokia XG-140G-MD / XG140GMC2P5G / AN7581DT / 512 MiB.

PERSISTENT FIP POLICY
- CI does NOT use any XG-040G-MD donor FIP.
- The artifact contains XG140 BL33 as u-boot.lzma; CI packages the dedicated XG140 native repacker.
- START_INSTALL_PERSISTENT.cmd asks for this router's own mtd0_bootloader.bin(.gz).
- The host extracts the native XG140 FIP from physical 0x800 up to its declared end.
- For the checksum-free Nokia stock lineage, every native FIP entry is preserved byte-for-byte;
  only final NT_FW/BL33 payload and its size are changed, plus the FIP terminator end.
- No Routerich/MTK checksum entry is synthesized when the native donor does not contain one.
- The repacker refuses a donor where NT_FW is not the final payload instead of relocating unknown native entries.
- Final FIP physical end must remain below the stock env at 0x7c000.
- BootROM prefix 0x0..0x7ff and stock env 0x7c000..0x7ffff are preserved by the
  device-side STOCK updater from live mtd0; full 512 KiB readback is required.
- One ordinary y/N is required immediately before the persistent write.

FLOW
1. RAM-start u-boot.bin at 0x81e00000 from stock tcboot UART.
2. Verify UrsusBoot/WebFailsafe at 192.168.1.1.
3. Run START_INSTALL_PERSISTENT.cmd.
4. Select your own XG140 mtd0_bootloader.bin or mtd0_bootloader.bin.gz backup.
5. Host validates 0x80000 size, BootROM prefix SHA256, stock env CRC, native FIP,
   and TB_FW SHA256; then builds a native-hybrid FIP by replacing only final BL33/NT_FW.
6. One y/N.
7. WebFailsafe STOCK updater writes the 512 KiB reconstructed boot area and verifies full readback.
8. Reboot into persistent XG140 UrsusBoot only after readback PASS.
9. Flash only the correct Bell XG-140G-MD sysupgrade.

Airoha BootROM UART recovery remains the emergency escape path.
EOF

(
  cd "$OUT"
  sha256sum ./* > SHA256SUMS.txt
)

echo "XG140_URSUSBOOT_NATIVE1_BUILD=PASS"
echo "Artifacts: $OUT"
