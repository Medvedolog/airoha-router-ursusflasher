# Proven-code porting provenance

Source snapshot used for the first LAB build:

```text
Nokia-Router-MedveFlasher-1.0.0-rc25fix2-FULL-GITHUB
```

Copied into Ursus:

- `data/proven_backend.py` <- MedveFlasher `data/master.py`, with only release identity/path and Rich-runtime dependency adjustments before the first hardware gate;
- `data/stock_web.py` <- MedveFlasher `data/stock_web.py`;
- tcboot patch1 payload/source/rebuild verifier <- the supplied `UrsusFlasher-MD-tcboot-direct-sysupgrade-patch1-WRITE-LAB-20260818` package.

The new `data/master.py` is Ursus-native orchestration and exposes only the new beginner UI. No external MedveFlasher tree is imported at runtime.
