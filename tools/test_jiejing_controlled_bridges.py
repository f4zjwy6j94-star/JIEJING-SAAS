#!/usr/bin/env python3
"""Regression checks for the formal Jiejing controlled bridge contract."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.controlled_bridges import FORMAL_BRIDGE_KEYS, build_controlled_bridge_contract  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-controlled-bridges-test"
DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"
ENV_KEYS = [
    "JIEJING_SAAS_ENV",
    "JIEJING_DATABASE_ENGINE",
    "JIEJING_DATABASE_ADAPTER",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_ALLOW_HERMES_ADAPTERS",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    repo = SaaSRepository(DB, database_engine="sqlite")
    repo.initialize()
    _seed(repo)

    with patched_env(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:secret@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "postgres_durable",
            "JIEJING_QUEUE_URL": "",
            "JIEJING_ALLOW_HERMES_ADAPTERS": "false",
        }
    ):
        settings = _settings()
        contract = build_controlled_bridge_contract(settings, repo)
        bridges = {item.get("key"): item for item in contract.get("bridges", [])}
        if not FORMAL_BRIDGE_KEYS.issubset(bridges):
            return fail(f"formal bridge contract missing keys: {sorted(FORMAL_BRIDGE_KEYS - set(bridges))}")
        if contract.get("production_blockers"):
            return fail(f"Postgres durable staging bridge path should not keep bridge blockers: {contract.get('production_blockers')}")
        if contract.get("rules", {}).get("hermes_legacy_bridge_can_be_production_dependency") is not False:
            return fail("Hermes legacy bridge must never be a production dependency")
        if bridges.get("HermesLegacyBridge", {}).get("status") != "disabled_transitional_only":
            return fail("Hermes legacy bridge should be disabled/transitional by default")
        if bridges.get("QueueWorkerBridge", {}).get("capabilities", {}).get("concurrency_safe_claim") is not True:
            return fail("Postgres durable queue bridge must expose concurrency-safe claim")
        for key in FORMAL_BRIDGE_KEYS:
            guardrails = bridges[key].get("guardrails", {})
            if guardrails.get("frontend_gets_raw_secret") is not False:
                return fail(f"{key} may not expose raw secrets to frontend")
            if guardrails.get("runtime_gets_raw_secret") is not False:
                return fail(f"{key} may not expose raw secrets to Runtime")
            if guardrails.get("bypasses_confirmation_center") is not False:
                return fail(f"{key} may not bypass confirmation center")
        readiness = build_product_readiness(settings, repo)
        readiness_items = {item.get("key"): item for item in readiness.get("items", [])}
        if readiness_items.get("controlled_bridges", {}).get("status") != "ready":
            return fail(f"readiness should accept controlled bridges: {readiness_items.get('controlled_bridges')}")
        public_status = readiness.get("provider_status", {}).get("controlled_bridges", {})
        if public_status.get("formal_bridge_count") != 5 or public_status.get("production_blockers"):
            return fail(f"public controlled bridge status should expose five formal bridges without blockers: {public_status}")

    with patched_env(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:secret@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "postgres_durable",
            "JIEJING_ALLOW_HERMES_ADAPTERS": "true",
        }
    ):
        settings = _settings()
        blocked = build_controlled_bridge_contract(settings, repo)
        if "hermes_legacy_bridge_enabled" not in blocked.get("production_blockers", []):
            return fail(f"enabling Hermes adapters must block formal launch bridge contract: {blocked}")
        readiness = build_product_readiness(settings, repo)
        item = next((entry for entry in readiness.get("items", []) if entry.get("key") == "controlled_bridges"), {})
        if item.get("severity") != "blocker" or item.get("status") != "blocked_hermes_legacy_bridge_enabled":
            return fail(f"readiness must block Hermes legacy bridge dependency: {item}")

    print("PASS jiejing_controlled_bridges")
    return 0


def _settings() -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=DB,
        runtime_db_path=RUNTIME_DB,
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )


def _seed(repo: SaaSRepository) -> None:
    account = repo.create_user_with_company(
        email="controlled-bridges@example.com",
        password="unit-test-password",
        company_name="Controlled Bridges Test",
    )
    repo.create_store(
        company_id=account["company"]["company_id"],
        user_id=account["user"]["user_id"],
        payload={"platform": "ebay", "store_name": "Controlled Bridge Store", "marketplace": "EBAY_US"},
    )


@contextmanager
def patched_env(values: dict[str, str]):
    old = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
            if old.get(key) is not None:
                os.environ[key] = old[key] or ""


if __name__ == "__main__":
    raise SystemExit(main())
