#!/usr/bin/env python3
"""Grant one expiring media-point bucket for owner-controlled acceptance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.media_credits import grant_controlled_media_acceptance_points  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Owner-only controlled media acceptance grant; no provider call or public route is involved."
    )
    parser.add_argument("--account-email", required=True)
    parser.add_argument("--expected-company-id", required=True)
    parser.add_argument("--owner-confirmation-phrase", default="")
    args = parser.parse_args()

    settings = SaaSSettings.from_env(
        db_path=Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite"),
        runtime_db_path=Path(os.environ.get("JIEJING_RUNTIME_DB_PATH") or "/data/runtime.sqlite"),
        output_root=Path(os.environ.get("JIEJING_OUTPUT_ROOT") or "/data/output"),
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(
        settings.db_path,
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repository.initialize()
    result = grant_controlled_media_acceptance_points(
        repository,
        account_email=args.account_email,
        expected_company_id=args.expected_company_id,
        owner_confirmation_phrase=args.owner_confirmation_phrase,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
