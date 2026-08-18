# UrsusFlasher 0.1.0-md-lab1fix10

Nokia XG-040G-MD / Airoha AN7581 — tcboot-based OpenWrt install and recovery kit.

The rollup root is intentionally minimal. Start with `START.cmd` on Windows or `START.sh` on Linux.

Documentation:

- Russian instructions: `doc/INSTRUCTIONS_RU.md`
- English instructions: `doc/INSTRUCTIONS_EN.md`
- Architecture and tcboot know-how (RU): `doc/ARCHITECTURE_RU.md`
- Architecture and tcboot know-how (EN): `doc/ARCHITECTURE_EN.md`
- Changelog: `doc/CHANGELOG_RU.md`, `doc/CHANGELOG_EN.md`
- Historical LAB notes: `doc/history/`

Hardware-verified tcboot WebFailsafe entry for MD:

```text
power OFF
power ON
immediately press Reset
hold Reset for 10 seconds
release Reset
```

Do not hold Reset before applying power; that is the early BootROM `Press x` path.
