#!/usr/bin/env python3
"""Contract test for the controlled model-value proof operator command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-controlled-model-value-proof-test"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "saas.sqlite"
    runtime_db_path = OUT / "runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)

    settings = SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    repo = SaaSRepository(db_path, database_engine=settings.database_engine)
    fixture = repo.create_user_with_company(
        email="controlled-proof@jiejing.local",
        password="local-controlled-proof-password",
        company_name="Controlled Proof Test",
    )
    user = fixture["user"]
    company = fixture["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "proof-store", "marketplace": "EBAY_US"},
    )

    repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "source_mode": "manual_input",
            "status": "created",
            "present_resource_keys": ["store_profile"],
            "missing_resource_keys": [],
            "secret_exposed": False,
        },
    )
    safe_packet = repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "packet_cached_sanitized",
            "present_resource_keys": ["store_profile", "account_business_policies"],
            "missing_resource_keys": [],
            "sections": [],
            "secret_exposed": False,
        },
    )

    env = os.environ.copy()
    env.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_DATABASE_ENGINE": "sqlite",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_controlled_model_value_proof.py"),
            "--db",
            str(db_path),
            "--runtime-db",
            str(runtime_db_path),
            "--output-root",
            str(OUT),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return 1
    payload = json.loads(completed.stdout)
    if payload.get("status") != "ready_for_controlled_execution":
        print(payload)
        return 1
    if payload.get("packet_id") != safe_packet["packet_id"]:
        print("FAIL command did not select latest safe official packet")
        return 1
    if payload.get("would_call_live_model") is not False:
        print("FAIL dry run must not call the model")
        return 1
    if payload.get("real_platform_writes_enabled") is not False:
        print("FAIL command must keep platform writes disabled")
        return 1
    if payload.get("secret_exposed") is not False:
        print("FAIL command must not expose secrets")
        return 1
    if repo.list_reports(company_id=company["company_id"]):
        print("FAIL dry run must not persist reports")
        return 1
    serialized = completed.stdout.lower()
    for forbidden in ("api_key", "access_token", "refresh_token", "client_secret", "password"):
        if forbidden in serialized:
            print(f"FAIL output leaked forbidden marker: {forbidden}")
            return 1
    print("PASS jiejing_controlled_model_value_proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
