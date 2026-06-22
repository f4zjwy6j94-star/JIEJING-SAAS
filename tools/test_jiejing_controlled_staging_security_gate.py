#!/usr/bin/env python3
"""Regression for the controlled staging security gate."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.staging_security_gate import build_controlled_staging_security_gate  # noqa: E402


ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP",
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    root = Path(tempfile.mkdtemp(prefix="jiejing-controlled-security-"))
    try:
        os.environ["JIEJING_SAAS_ENV"] = "staging"
        os.environ["JIEJING_SAAS_SESSION_SECRET"] = "controlled-staging-test-secret-with-enough-length"
        os.environ["JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP"] = "false"
        os.environ["JIEJING_ENABLE_REAL_PLATFORM_WRITES"] = "false"
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root,
            host="127.0.0.1",
            port=8788,
        )
        repo = SaaSRepository(settings.db_path)
        repo.initialize()
        fixture = repo.create_user_with_company(
            email="controlled@example.com",
            password="controlled-password",
            company_name="Controlled Merchant",
        )
        user = fixture["user"]
        company = fixture["company"]
        store = repo.create_store(
            company_id=company["company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Real Store", "marketplace": "EBAY_US"},
        )
        repo.create_secret_reference(
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            provider="model.openai",
            purpose="model_api_key",
            status="ready",
            metadata={
                "provider_key": "openai",
                "provider_label": "OpenAI",
                "model": "gpt-4.1-mini",
                "merchant_brings_own_key": True,
                "frontend_gets_raw_key_after_save": False,
                "runtime_gets_model_api_key": False,
                "reports_get_model_api_key": False,
                "secret_exposed": False,
            },
        )
        packet = repo.create_platform_data_packet(
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            packet={
                "platform": "ebay",
                "packet_type": "ebay_read_only_snapshot",
                "source_mode": "official_api",
                "source_label": "official_api",
                "status": "created",
                "ready_for_runtime": True,
                "present_resource_keys": ["store_profile", "account_business_policies"],
                "missing_resource_keys": [],
                "sections": [{"key": "store_profile", "data": {"marketplace_id": "EBAY_US"}, "source_type": "official_api"}],
                "safe_for_real_platform_write": False,
                "secret_exposed": False,
            },
        )
        if not packet.get("packet_id"):
            return fail("fixture should create an official packet")

        gate = build_controlled_staging_security_gate(
            settings,
            repo,
            project_root=ROOT,
            company_id=company["company_id"],
            store_id=store["store_id"],
        )
        if gate.get("controlled_staging_test_ready") is not True:
            return fail("controlled staging gate should pass for a safe staging fixture: " + json.dumps(gate, ensure_ascii=False))
        if gate.get("production_grade_saas_security") is not False or gate.get("can_accept_real_customers") is not False:
            return fail("controlled staging gate must not claim production-grade SaaS security")
        statuses = {item.get("key"): item.get("status") for item in gate.get("checks", [])}
        for key in {
            "session_secret",
            "demo_session",
            "real_platform_writes",
            "tenant_schema",
            "database_secret_scan",
            "byok_model_key_boundary",
            "official_packet_boundary",
            "merchant_surface_real_mode",
        }:
            if statuses.get(key) != "ready":
                return fail(f"{key} should be ready, got {statuses.get(key)}")

        os.environ["JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP"] = "true"
        unsafe_settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root,
            host="127.0.0.1",
            port=8788,
        )
        unsafe_gate = build_controlled_staging_security_gate(
            unsafe_settings,
            repo,
            project_root=ROOT,
            company_id=company["company_id"],
            store_id=store["store_id"],
        )
        if unsafe_gate.get("controlled_staging_test_ready") is not False:
            return fail("staging gate should block when demo-session bootstrap is enabled")
        if "demo_session" not in {item.get("key") for item in unsafe_gate.get("checks", []) if item.get("severity") == "blocker" and item.get("status") != "ready"}:
            return fail("demo-session blocker should be explicit")

        print("PASS jiejing_controlled_staging_security_gate")
        return 0
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
