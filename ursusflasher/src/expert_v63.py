#!/usr/bin/env python3
from __future__ import annotations

import expert_multi
import one_key_v63

# EXPERT item 1 uses base.one_key; bind it to the v0.2.63 guarded ONE-KEY.
expert_multi.base.one_key = one_key_v63


def main() -> int:
    return expert_multi.main()


if __name__ == "__main__":
    raise SystemExit(main())
