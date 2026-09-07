# Pinned OpenWrt firmware bundle

Committed runtime firmware for Nokia XG-040G-MD from the UnameOne build dated **2026-09-06**: OpenWrt SNAPSHOT `r36009+75-6c315233aa`, kernel `6.18.44`, kernel ABI/vermagic `bed7e2dec73efb4c3050bc8a8373af30`. The two production sysupgrade files are retained byte-for-byte as supplied by the build author.

- `*-squashfs-sysupgrade.bin` — `OPENWRT_NONUBI_SYSUPGRADE`, used only for `OPENWRT_STOCK_LAYOUT -> OPENWRT_STOCK_LAYOUT`.
- `*-ubi-squashfs-sysupgrade.itb` — `OPENWRT_UBI_SYSUPGRADE`, used for `STOCK -> OPENWRT_UBI` and `OPENWRT_UBI -> OPENWRT_UBI`.
- Author network defaults are retained: **LAN4 becomes WAN after OpenWrt boot**. UrsusFlasher therefore recommends LAN2/LAN3 for flashing and continuous management access. LAN1/2.5G uses the separate EN8811H PHY and remains excluded from transition/recovery guidance.
- OpenWrt firmware files are kept byte-identical to the 2026-09-06 payload refresh; UrsusBoot is versioned independently and is alpha5-UBIUX1 in 0.2.56.

ONE-CLICK does not download mutable snapshots at runtime. Hash/size authority is `data/FIRMWARE_BUNDLE.json`.

Factory kernel/rootfs images are intentionally not part of the release runtime bundle.
