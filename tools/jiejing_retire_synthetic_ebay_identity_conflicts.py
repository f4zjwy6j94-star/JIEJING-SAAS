#!/usr/bin/env python3
"""Value-free operator tool for retiring synthetic eBay identity conflicts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply the narrowly scoped synthetic eBay identity retirement contract."
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite",
        help="SQLite path; ignored by the Postgres adapter except for repository initialization compatibility.",
    )
    parser.add_argument(
        "--apply-confirmation",
        default="",
        help="Exact phrase required to mutate. Omit for the default dry-run.",
    )
    parser.add_argument(
        "--database-engine",
        choices=("sqlite", "postgres"),
        default=(os.environ.get("JIEJING_DATABASE_ENGINE") or "sqlite").strip().lower(),
    )
    args = parser.parse_args()
    repository = SaaSRepository(
        Path(args.db_path),
        database_engine=args.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL") or "",
    )
    try:
        result = (
            repository.retire_synthetic_ebay_identity_conflicts(
                confirmation_phrase=args.apply_confirmation
            )
            if args.apply_confirmation
            else repository.plan_synthetic_ebay_identity_conflict_retirement()
        )
    except (ValueError, RuntimeError) as exc:
        status = str(exc)
        if status not in {
            "synthetic_ebay_identity_retirement_confirmation_required",
            "synthetic_ebay_identity_retirement_conflict",
        }:
            status = "synthetic_ebay_identity_retirement_failed"
        print(
            json.dumps(
                {
                    "status": status,
                    "data_mutated": False,
                    "secret_exposed": False,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("merchant_conflict_count"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
