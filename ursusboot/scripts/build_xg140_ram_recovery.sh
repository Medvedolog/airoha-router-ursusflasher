#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/xg140-ram-recovery"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
DTS_PATCH="$ROOT/ursusboot/patches/140-xg140-ram1-dts.patch"
DONOR="$ROOT/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-update.fip"
OUT="$WORK/out"
PERSISTENT_FIP="ursusboot-xg140-0.1.0-xg140-persist1-update.fip"

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
[ -f "$DONOR" ] || { echo "proven alpha3 FIP lineage donor missing" >&2; exit 1; }

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

# XG140 PERSIST1 keeps the original 0x7c000..0x7ffff tcboot environment bytes
# intact but never writes them. Runtime defaults are authoritative.
sed -i 's/^CONFIG_ENV_IS_IN_UBI=y/# CONFIG_ENV_IS_IN_UBI is not set/' .config
sed -i 's/^# CONFIG_ENV_IS_NOWHERE is not set/CONFIG_ENV_IS_NOWHERE=y/' .config

while IFS= read -r -d '' f; do
  sed -i \
    -e 's/Nokia XG-040G-MD/Bell XG-140G-MD/g' \
    -e 's/nokia,xg-040g-md/bell,xg-140g-md/g' \
    "$f"
done < <(grep -RIlZ --exclude-dir=.git -e 'Nokia XG-040G-MD' -e 'nokia,xg-040g-md' cmd include board drivers defenvs 2>/dev/null || true)

if [ -f include/ursus_version.h ]; then
  sed -i 's/#define URSUS_VERSION ".*"/#define URSUS_VERSION "0.1.0-xg140-persist1"/' include/ursus_version.h
fi
printf '%s\n' '-UrsusBoot-0.1.0-xg140-persist1' > .scmversion

make olddefconfig
make -j"${JOBS:-$(nproc)}"

# Build exactly the same Airoha FIP lineage used by the hardware-proven MD
# direct-stock installer, changing only NT_FW/BL33 to the XG140 UrsusBoot.
gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576
python3 repack_persistent_fip.py "$DONOR" u-boot.lzma "$PERSISTENT_FIP"

test -s "$PERSISTENT_FIP"
python3 - "$PERSISTENT_FIP" <<'PY'
from pathlib import Path
import hashlib, struct, sys
p=Path(sys.argv[1]); b=p.read_bytes()
if b[:8] != bytes.fromhex('010064aa78563412'):
    raise SystemExit('persistent FIP header mismatch')
if len(b) >= 0x7b800:
    raise SystemExit(f'persistent FIP reaches protected env: size=0x{len(b):x}')
TB=bytes.fromhex('5ff9ec0b4d223e4da544c39d81c73f0a')
NT=bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4')
pos=16; tb=None; nt=None
for _ in range(32):
    u=b[pos:pos+16]
    if u == b'\0'*16: break
    off,size,flags=struct.unpack_from('<QQQ',b,pos+16)
    if off+size > len(b): raise SystemExit('FIP entry outside image')
    if u==TB: tb=(off,size)
    if u==NT: nt=(off,size)
    pos += 40
if not tb or not nt: raise SystemExit('FIP missing TB_FW or NT_FW')
tb_sha=hashlib.sha256(b[tb[0]:tb[0]+tb[1]]).hexdigest()
if tb_sha != '07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e':
    raise SystemExit('early-boot lineage BL2 mismatch: '+tb_sha)
print('XG140_PERSIST_FIP_SIZE=0x%x' % len(b))
print('XG140_PERSIST_FIP_SHA256='+hashlib.sha256(b).hexdigest())
print('XG140_PERSIST_BL33_RANGE=0x%x+0x%x' % nt)
PY

cp -av u-boot.bin u-boot u-boot.map u-boot.sym System.map u-boot.lzma "$PERSISTENT_FIP" "$OUT/"
[ -f u-boot.dtb ] && cp -av u-boot.dtb "$OUT/" || true
cp -av "$XG_DTS" "$OUT/"
cp -av "$XG_UBOOT_DTSI" "$OUT/"
cp -av .config "$OUT/u-boot.xg140-persist.config"

MKIMAGE=$(command -v mkimage || true)
if [ -z "$MKIMAGE" ] && [ -x tools/mkimage ]; then MKIMAGE="$PWD/tools/mkimage"; fi
if [ -n "$MKIMAGE" ]; then
  "$MKIMAGE" -A arm64 -O u-boot -T standalone -C none \
    -a 0x81e00000 -e 0x81e00000 \
    -n 'UrsusBoot XG140 RAM recovery' \
    -d u-boot.bin "$OUT/ursusboot-xg140-ram.uimg" || true
fi

cat > "$OUT/TESTING.txt" <<'EOF'
UrsusBoot XG-140G-MD PERSIST1

TARGET
Bell/Nokia XG-140G-MD / XG140GMC2P5G / AN7581DT / 512 MiB.

PERSISTENT STOCK BOOT CONTRACT
- Physical boot partition is exactly 0x80000 bytes.
- Preserve BootROM prefix 0x00000000..0x000007ff byte-for-byte.
- Replace only Airoha FIP beginning at physical 0x00000800.
- Preserve stock tcboot environment 0x0007c000..0x0007ffff byte-for-byte.
- Persistent FIP must end before 0x0007c000.
- Trusted Boot Firmware entry remains exact proven Nokia/Airoha lineage
  SHA256 07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e.
- Full mtd0 readback is mandatory before reboot.
- One y/N immediately before the destructive write.

RECOVERY FLOW
1. RAM-start this XG140 UrsusBoot from stock tcboot/UART.
2. Verify UART, mtd map and WebFailsafe at 192.168.1.1.
3. Run START_INSTALL_PERSISTENT.cmd from the artifact.
4. The helper uploads the PERSIST1 FIP to RAM and invokes UrsusBoot's
   transactional STOCK bootloader updater.
5. UrsusBoot preserves prefix/env and performs readback before reporting success.
6. Reboot. Persistent UrsusBoot must appear instead of tcboot.
7. Only then upload the correct Bell XG-140G-MD sysupgrade through WebFailsafe.

Airoha BootROM UART recovery remains the emergency escape path.
EOF

(
  cd "$OUT"
  sha256sum ./* > SHA256SUMS.txt
)

echo "XG140_URSUSBOOT_PERSIST1_BUILD=PASS"
echo "Artifacts: $OUT"
