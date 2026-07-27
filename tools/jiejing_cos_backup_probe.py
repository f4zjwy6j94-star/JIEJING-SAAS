#!/usr/bin/env python3
"""Run one redacted synthetic COS backup upload/readback/delete probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.cos_backup_probe import execute_cos_backup_probe  # noqa: E402


def main() -> int:
    result = execute_cos_backup_probe()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
