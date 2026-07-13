#!/usr/bin/env python3
"""Upsert one validated secret from stdin into a private backend env file."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


SECRET_PATTERNS = {
    "JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN": re.compile(r"^[A-Za-z0-9_-]{32,80}$"),
    "JIEJING_EBAY_CLIENT_SECRET": re.compile(r"^[A-Za-z0-9._-]{20,200}$"),
}


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    target = Path(sys.argv[1]).resolve()
    key = sys.argv[2]
    pattern = SECRET_PATTERNS.get(key)
    if pattern is None:
        return 3
    value = sys.stdin.read().strip()
    if not pattern.fullmatch(value):
        return 4
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not replaced:
                output.append(f"{key}={value}")
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(target)
    os.chmod(target, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
