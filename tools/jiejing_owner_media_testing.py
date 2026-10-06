#!/usr/bin/env python3
"""Grant the fixed private owner media-testing allowance."""

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
from jiejing_saas.media_credits import grant_owner_media_testing_points  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Private allowlisted owner media-testing grant; it never calls a provider or opens public charging."
    )
    parser.add_argument("--account-email", required=True)
    parser.add_argument("--expected-company-id", required=True)
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
    result = grant_owner_media_testing_points(
        repository,
        account_email=args.account_email,
        expected_company_id=args.expected_company_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
