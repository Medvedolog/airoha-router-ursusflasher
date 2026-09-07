# Exact OpenWrt SDK / GCC toolchain

The current FUDAN1 build used the exact Airoha AN7581 OpenWrt SDK whose compiler reports:

```text
OpenWrt GCC 14.4.0 r35906+7-3d1645ee26
SDK archive SHA256:
6ec133d3810812111d719b53c37dcd83501fe534a8d5f149d5f91e0a657991ac
```

The archive is split into sub-100-MB parts only to satisfy GitHub's per-blob size limit. Reassembly must reproduce the exact SHA256 above.

A similarly named later SDK (`r35925`) was present in the development inputs but is **not** the FUDAN1 reproduction toolchain and is intentionally not bundled here.
