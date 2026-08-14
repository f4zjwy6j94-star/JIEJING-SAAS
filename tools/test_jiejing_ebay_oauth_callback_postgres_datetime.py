from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ebay_oauth_callback import (
    OAUTH_CALLBACK_STATE_TTL_SECONDS,
    _oauth_state_age_seconds,
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    now = datetime.now(timezone.utc)

    postgres_age = _oauth_state_age_seconds({"created_at": now - timedelta(seconds=2)})
    if postgres_age is None or not 0 <= postgres_age <= 10:
        return fail("timezone-aware Postgres datetime must remain a fresh OAuth state")

    explicit_iso_age = _oauth_state_age_seconds(
        {"created_at": (now - timedelta(seconds=2)).isoformat()}
    )
    if explicit_iso_age is None or not 0 <= explicit_iso_age <= 10:
        return fail("explicit-zone ISO state timestamps must remain supported")

    invalid_cases = {
        "naive Postgres datetime": now.replace(tzinfo=None),
        "future Postgres datetime": now + timedelta(minutes=5),
        "malformed timestamp": "not-a-timestamp",
    }
    for label, created_at in invalid_cases.items():
        if _oauth_state_age_seconds({"created_at": created_at}) is not None:
            return fail(f"{label} must fail closed before token exchange")

    expired_age = _oauth_state_age_seconds(
        {"created_at": now - timedelta(seconds=OAUTH_CALLBACK_STATE_TTL_SECONDS + 1)}
    )
    if expired_age is None or expired_age <= OAUTH_CALLBACK_STATE_TTL_SECONDS:
        return fail("an actually expired Postgres datetime must remain expired")

    print("PASS jiejing_ebay_oauth_callback_postgres_datetime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
