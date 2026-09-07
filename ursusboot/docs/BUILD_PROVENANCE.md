# UrsusBoot FUDAN1 build provenance

```text
Target                   Nokia XG-040G-MD / Airoha AN7581
U-Boot upstream          v2026.07
OpenWrt baseline         3d1645ee26d6a2e20be71d7fa1716721bac78e53
Toolchain                OpenWrt GCC 14.4.0 r35906+7-3d1645ee26
SOURCE_DATE_EPOCH        1788446468
Fudan PR head            c58a6187fe9fb77b1e691c642fccc7de6f4b2966
Patch 120 provenance     d5a5c9eb2ee9ff5b4cc0be15ac7f4879d4c2f247
Patch 121 provenance     8211f2d74b356a02fe38aeea5b74030ac156461f
```

Historical byte-reproduction chain before the Fudan delta:

```text
HWFIX3 raw SHA256  fe150f81b98a9ad02dbba6764722383652d5982056c429faad4c427ef8373548
UIFIX1 raw SHA256  921d53f396bec54613c792e6a31388e5a12a481fdcf963875dda2fad86499a67
FUDAN1 raw SHA256  a41a81a011e19d1498d5ff0773dfd6bf9bd4c56beb3e7a46ce4622a643a30703
```

FUDAN1 uses the exact current source snapshot archived under `ursusboot/source/`. The snapshot was produced from the successfully built tree after `make distclean`; build outputs are preserved separately under `ursusboot/artifacts/`.

The two Fudan U-Boot patches are preserved separately under `ursusboot/patches/openwrt-pr24025/` for provenance. The authoritative reproducible build input is the exact source snapshot, avoiding ambiguity from historical OpenWrt/shared-Airoha patch ordering.
