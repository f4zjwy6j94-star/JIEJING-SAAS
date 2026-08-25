#!/usr/bin/env python3
"""Regression check for degraded readiness when the SaaS database is unavailable."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler, initialize_repository_for_startup  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.postgres_repository_runtime import postgres_connect_timeout_seconds  # noqa: E402
from jiejing_saas.readiness import build_product_readiness_or_degraded  # noqa: E402


class FailingRepository:
    def system_counts(self) -> dict[str, int]:
        raise TimeoutError("managed postgres connection timed out")

    def product_readiness_evidence(self) -> dict[str, object]:
        raise TimeoutError("managed postgres connection timed out")


class StartupFailingRepository:
    def initialize(self) -> None:
        raise RuntimeError("Postgres repository initialization failed: connection timeout expired")


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    settings = SaaSSettings(
        environment="staging",
        session_secret_configured=True,
        session_secret_is_default=False,
        requested_real_platform_writes=False,
        database_engine="postgres",
        database_url_configured=True,
        database_adapter="postgres-managed",
        queue_provider="redis_streams",
        queue_url_configured=True,
        vault_provider="vault",
        vault_enabled=True,
        execution_adapter="confirmation_gated",
        ebay_oauth_environment="production",
        ebay_client_id="client-id-present",
        ebay_ru_name="ru-name-present",
        ebay_client_secret_configured=True,
        ebay_account_deletion_endpoint_url="https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion",
        ebay_account_deletion_verification_token_configured=False,
        ebay_access_token_configured=False,
        ebay_refresh_token_configured=False,
        ebay_oauth_live_exchange_enabled=True,
        ebay_token_refresh_live_enabled=True,
        ebay_read_only_live_enabled=True,
        ebay_write_live_enabled=False,
        ebay_draft_save_live_enabled=False,
        ebay_controlled_publish_live_enabled=False,
        allow_hermes_adapters=False,
        cors_origin="https://staging.example.test",
        internal_admin_emails=(),
        host="127.0.0.1",
        port=8788,
        db_path=ROOT / "output/test-readiness-degraded/saas.sqlite",
        runtime_db_path=ROOT / "output/test-readiness-degraded/runtime.sqlite",
        output_root=ROOT / "output/test-readiness-degraded",
    )
    readiness = build_product_readiness_or_degraded(settings, FailingRepository())  # type: ignore[arg-type]

    if readiness.get("status") != "degraded" or readiness.get("degraded") is not True:
        return fail(f"readiness should return degraded status: {readiness}")
    if readiness.get("degraded_reason") != "database_unavailable":
        return fail(f"degraded reason should identify database unavailability: {readiness}")
    if readiness.get("production_ready") is not False or readiness.get("beta_ready") is not False:
        return fail("degraded readiness must not claim production or beta readiness")
    if readiness.get("blocker_count") != 1:
        return fail(f"degraded readiness should expose one database blocker: {readiness.get('blocker_count')}")
    item_keys = {item.get("key") for item in readiness.get("items", [])}
    if "database_reachability" not in item_keys:
        return fail(f"degraded readiness should include database reachability item: {item_keys}")
    if readiness.get("secret_exposed") is not False:
        return fail("degraded readiness must not expose secrets")

    startup_error = initialize_repository_for_startup(StartupFailingRepository(), settings)  # type: ignore[arg-type]
    if not isinstance(startup_error, RuntimeError):
        return fail("staging startup should degrade when Postgres initialization times out")
    if not SaaSBackendHandler._is_database_unavailable_exception(startup_error):
        return fail("database timeout should map to a 503 dependency error response")
    try:
        initialize_repository_for_startup(StartupFailingRepository(), replace(settings, environment="production"))  # type: ignore[arg-type]
    except RuntimeError:
        pass
    else:
        return fail("production startup must still fail closed when repository initialization fails")

    previous_timeout = os.environ.get("JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS")
    try:
        os.environ.pop("JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS", None)
        if postgres_connect_timeout_seconds() != 3:
            return fail("default Postgres connect timeout should be short enough for readiness degradation")
        os.environ["JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS"] = "999"
        if postgres_connect_timeout_seconds() != 15:
            return fail("Postgres connect timeout should be bounded")
        os.environ["JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS"] = "not-a-number"
        if postgres_connect_timeout_seconds() != 3:
            return fail("invalid Postgres connect timeout should fall back to the safe default")
    finally:
        if previous_timeout is None:
            os.environ.pop("JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS", None)
        else:
            os.environ["JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS"] = previous_timeout

    print("PASS jiejing_readiness_degraded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
