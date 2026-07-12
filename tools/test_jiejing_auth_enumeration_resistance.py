#!/usr/bin/env python3
"""Guard public authentication against account-enumeration signals."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "jiejing_saas" / "repository.py"
API_SERVER = ROOT / "jiejing_saas" / "api_server.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    repository = REPOSITORY.read_text(encoding="utf-8")
    api_server = API_SERVER.read_text(encoding="utf-8")

    required_repository = [
        "AUTH_DUMMY_PASSWORD_SALT",
        "AUTH_DUMMY_PASSWORD_HASH",
        "verify_password(password, AUTH_DUMMY_PASSWORD_SALT, AUTH_DUMMY_PASSWORD_HASH)",
        'raise ValueError("invalid email or password")',
    ]
    for marker in required_repository:
        if marker not in repository:
            return fail(f"missing fixed-cost unknown-account authentication marker: {marker}")

    if "email already registered" in api_server:
        return fail("registration still exposes whether an email is already registered")
    if "account registration could not be completed" not in api_server:
        return fail("registration conflict does not use the generic public response")

    print("PASS auth enumeration resistance contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
