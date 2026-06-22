#!/usr/bin/env python3
"""Regression for the read-only Jiejing current-state guard."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_current_state_guard.py"),
            "--json",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return fail(f"guard should be readable without side effects: {result.stderr[:500]}")
    payload = json.loads(result.stdout)
    if payload.get("real_platform_writes_enabled") is not False:
        return fail("guard must keep real platform writes disabled")
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ["AUTHORIZATION_URL=", "access_token", "refresh_token", "client_secret"]:
        if forbidden in text:
            return fail(f"guard leaked or produced a forbidden operator value: {forbidden}")
    if payload.get("callback_completed") and not any("Do not run OAuth prepare" in item for item in payload.get("no_repeat_actions", [])):
        return fail("completed OAuth state must block repeated prepare/open authorization actions")
    if payload.get("sync_completed") and not any("Do not run a fresh eBay read-only sync" in item for item in payload.get("no_repeat_actions", [])):
        return fail("completed sync state must block repeated progress-check syncs")
    print("PASS jiejing_current_state_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
