#!/usr/bin/env python3
"""Run the Jiejing controlled-staging security gate.

This is the deployment-time gate for the current phase. It does not claim
paid-production readiness; it verifies the safety controls needed for real
merchant staging tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.json_safe import json_default  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.staging_security_gate import build_controlled_staging_security_gate  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Jiejing controlled-staging security readiness.")
    parser.add_argument("--db", default="output/jiejing-controlled-staging-security/saas.sqlite")
    parser.add_argument("--runtime-db", default="output/jiejing-controlled-staging-security/runtime.sqlite")
    parser.add_argument("--output-root", default="output/jiejing-controlled-staging-security")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--company-id", default="")
    parser.add_argument("--store-id", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-latest", action="store_true", help="Write output/jiejing-controlled-staging-security/latest.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = _path(args.output_root)
    db_path = _path(args.db)
    runtime_db_path = _path(args.runtime_db)
    output_root.mkdir(parents=True, exist_ok=True)
    settings = SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=output_root,
        host=args.host,
        port=args.port,
    )
    repo = SaaSRepository(
        db_path,
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repo.initialize()
    result = build_controlled_staging_security_gate(
        settings,
        repo,
        project_root=ROOT,
        company_id=args.company_id or None,
        store_id=args.store_id or None,
    )
    if args.write_latest:
        (output_root / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
    else:
        _print_human(result)
    return 0 if result.get("controlled_staging_test_ready") else 2


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _print_human(result: dict[str, Any]) -> None:
    print(f"STATUS={result.get('status')}")
    print(f"CONTROLLED_STAGING_TEST_READY={result.get('controlled_staging_test_ready')}")
    print(f"PRODUCTION_GRADE_SAAS_SECURITY={result.get('production_grade_saas_security')}")
    print(f"REAL_PLATFORM_WRITES_ENABLED={result.get('real_platform_writes_enabled')}")
    print(f"BLOCKERS={result.get('blocker_count')}")
    print(f"WARNINGS={result.get('warning_count')}")
    for item in result.get("checks") or []:
        print(f"- {item.get('key')}: {item.get('status')} [{item.get('severity')}] {item.get('detail')}")


if __name__ == "__main__":
    raise SystemExit(main())
