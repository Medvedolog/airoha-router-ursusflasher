#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/xg140-ram-recovery"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
OUT="$WORK/out"
XG140_DTS_URL="https://raw.githubusercontent.com/hzyitc/openwrt-redmi-ax3000/b27424f28a034ee1d18409b7952616ba9a40cca4/target/linux/airoha/dts/an7581-xg-140g-md.dts"

command -v tar >/dev/null
command -v make >/dev/null
command -v gcc >/dev/null
command -v python3 >/dev/null
command -v sha256sum >/dev/null
command -v curl >/dev/null

if [ ! -f "$SDK_BUNDLE" ]; then
  "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null
fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

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

# Reuse the proven AN7581 UrsusBoot TEST61 source, but give it the XG-140G-MD
# board description and identity. This build is intended to be chain-loaded
# into already-initialized DRAM from stock tcboot. It does not replace mtd0.
MD_DTS=$(find . -type f -name 'an7581-nokia-xg-040g-md.dts' | head -n1)
[ -n "$MD_DTS" ] || { echo "reference AN7581 MD DTS not found" >&2; exit 1; }
DTS_DIR=$(dirname "$MD_DTS")
XG_DTS="$DTS_DIR/an7581-bell-xg-140g-md.dts"
curl -fsSL "$XG140_DTS_URL" -o "$XG_DTS"

# The public XG140 DTS currently advertises an 8 GiB memory node although the
# production XG140GMC2P5G board tested here has 512 MiB. tcboot already trained
# DDR4 before this RAM handoff, so keep the DT truthful and bounded to 512 MiB.
python3 - "$XG_DTS" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = s.replace('reg = <0x0 0x80000000 0x2 0x00000000>;',
              'reg = <0x0 0x80000000 0x0 0x20000000>;')
p.write_text(s)
PY

cp "$CONFIG" .config
sed -i 's#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-nokia-xg-040g-md"#CONFIG_DEFAULT_DEVICE_TREE="airoha/an7581-bell-xg-140g-md"#' .config
sed -i 's#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-nokia-xg-040g-md.dtb"#CONFIG_DEFAULT_FDT_FILE="airoha/an7581-bell-xg-140g-md.dtb"#' .config
# RAM recovery must never persist an environment while we are proving this port.
sed -i 's/^CONFIG_ENV_IS_IN_UBI=y/# CONFIG_ENV_IS_IN_UBI is not set/' .config
sed -i 's/^# CONFIG_ENV_IS_NOWHERE is not set/CONFIG_ENV_IS_NOWHERE=y/' .config

# Dedicated branch: retarget board identity and sysupgrade supported-device
# checks from XG-040G-MD to Bell XG-140G-MD. Do not touch SoC identity AN7581.
while IFS= read -r -d '' f; do
  sed -i \
    -e 's/Nokia XG-040G-MD/Bell XG-140G-MD/g' \
    -e 's/nokia,xg-040g-md/bell,xg-140g-md/g' \
    "$f"
done < <(grep -RIlZ --exclude-dir=.git -e 'Nokia XG-040G-MD' -e 'nokia,xg-040g-md' cmd include board drivers defenvs 2>/dev/null || true)

# Make the experimental identity unambiguous on UART/Web.
if [ -f include/ursus_version.h ]; then
  sed -i 's/#define URSUS_VERSION ".*"/#define URSUS_VERSION "0.1.0-xg140-ram1"/' include/ursus_version.h
fi
printf '%s\n' '-UrsusBoot-0.1.0-xg140-ram1' > .scmversion

make olddefconfig
make -j"${JOBS:-$(nproc)}"

# Raw position-independent U-Boot is the primary tcboot chain-load payload.
cp -av u-boot.bin u-boot u-boot.map u-boot.sym System.map "$OUT/"
[ -f u-boot.dtb ] && cp -av u-boot.dtb "$OUT/" || true
[ -f "$XG_DTS" ] && cp -av "$XG_DTS" "$OUT/"
cp -av .config "$OUT/u-boot.xg140-ram.config"

# Also emit a legacy standalone wrapper for a bootm experiment. The raw image
# remains authoritative; the wrapper is provided only as an alternate RAM-only
# entry path and is never written to NAND.
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
- Intended for Bell/Nokia XG-140G-MD / XG140GMC2P5G / AN7581DT only.
- Stock tcboot in mtd0 is NOT replaced by this build.
- First hardware test is RAM-only.
- Do NOT saveenv, erase or write mtd0.
- The XG140 production board already initialized DDR4-2666 in tcboot.

PRIMARY tcboot experiment
1. Stop tcboot autoboot.
2. XMODEM-load u-boot.bin to 0x81e00000.
3. Verify the transfer size/hash on the host.
4. Execute: go 0x81e00000
5. Expect UrsusBoot 0.1.0-xg140-ram1 and HTTP on 192.168.1.1:80.

ALTERNATE experiment
If stock tcboot refuses raw go, XMODEM-load ursusboot-xg140-ram.uimg and try
bootm at its load address. This is also RAM-only.

The first acceptance gate is UART identity + working Ethernet/WebFailsafe.
Only after that should the Web firmware validator be tested with the XG140
stock-layout sysupgrade image. No BL2/preloader migration is part of RAM1.
EOF

echo "XG140_URSUSBOOT_RAM_BUILD=PASS"
echo "Artifacts: $OUT"
