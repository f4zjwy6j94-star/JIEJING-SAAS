#!/usr/bin/env python3
"""Regression for Jiejing plans, media points, and provider-neutral merchant data."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog  # noqa: E402
from jiejing_saas.billing_plan import PLAN_CATALOG  # noqa: E402
from jiejing_saas.media_credits import MEDIA_CREDIT_PACKS, build_media_credit_summary  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.worker import LocalQueueWorker  # noqa: E402


OUT = ROOT / "output" / "jiejing-commercial-entitlements-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    repo = SaaSRepository(OUT / "saas.sqlite")
    fixture = repo.create_user_with_company(
        email="commercial-entitlements@jiejing.local",
        password="commercial-entitlements-password",
        company_name="Jiejing Commercial Entitlements Test",
    )
    company_id = fixture["company"]["company_id"]
    user_id = fixture["user"]["user_id"]

    plan_rows = {item["key"]: item for item in PLAN_CATALOG}
    if list(plan_rows) != ["free", "starter", "operator", "team"]:
        return fail(f"plan catalog should expose exactly four ordered plans: {list(plan_rows)}")
    expected_prices = {"free": 0, "starter": 9900, "operator": 19900, "team": 29900}
    for key, amount_minor in expected_prices.items():
        if plan_rows[key].get("amount_minor") != amount_minor or plan_rows[key].get("duration_days") != 30:
            return fail(f"plan {key} has the wrong 30-day price contract: {plan_rows[key]}")
        if plan_rows[key].get("media_points_included") != 0:
            return fail(f"plan {key} must not bundle recurring media points")

    catalog_text = json.dumps(build_provider_job_contract_catalog(merchant_safe=True), ensure_ascii=False).lower()
    if "media.fal_asset_generation" in catalog_text or "fal media generation" in catalog_text:
        return fail("merchant-safe provider catalog exposed a replaceable media provider")
    if "media.asset_generation" not in catalog_text:
        return fail("provider-neutral media generation contract is missing")

    grant = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="grant",
        points=300,
        idempotency_key="welcome-points-v1",
        reference_type="onboarding",
        reference_id="welcome",
    )
    replay = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="grant",
        points=300,
        idempotency_key="welcome-points-v1",
        reference_type="onboarding",
        reference_id="welcome",
    )
    if grant.get("account", {}).get("available_points") != 300 or replay.get("duplicate_request") is not True:
        return fail(f"welcome grant should be idempotent: {grant}, {replay}")

    reserved = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="reserve",
        points=120,
        idempotency_key="media-job-1-reserve",
        reference_type="media_job",
        reference_id="media-job-1",
    )
    reservation_id = str(reserved.get("ledger_entry", {}).get("ledger_id") or "")
    if not reservation_id or reserved.get("account", {}).get("available_points") != 180:
        return fail(f"media points should reserve before generation: {reserved}")

    settled = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="settle",
        points=90,
        idempotency_key="media-job-1-settle",
        reference_type="media_job",
        reference_id="media-job-1",
        reservation_id=reservation_id,
    )
    account = settled.get("account", {})
    if account.get("balance_points") != 210 or account.get("reserved_points") != 0 or account.get("available_points") != 210:
        return fail(f"settlement should charge actual points and release the remainder: {settled}")

    second = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="reserve",
        points=50,
        idempotency_key="media-job-2-reserve",
        reference_type="media_job",
        reference_id="media-job-2",
    )
    released = repo.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="release",
        points=50,
        idempotency_key="media-job-2-release",
        reference_type="media_job",
        reference_id="media-job-2",
        reservation_id=str(second.get("ledger_entry", {}).get("ledger_id") or ""),
    )
    if released.get("account", {}).get("available_points") != 210:
        return fail(f"failed media work should return all reserved points: {released}")

    summary = build_media_credit_summary(repo, company_id=company_id)
    serialized = json.dumps(summary, ensure_ascii=False).lower()
    if summary.get("account", {}).get("available_points") != 210:
        return fail(f"merchant summary should show the current balance: {summary}")
    if [item.get("points") for item in MEDIA_CREDIT_PACKS] != [1000, 5000, 10000]:
        return fail(f"media point packs are not the approved fixed packs: {MEDIA_CREDIT_PACKS}")
    for forbidden in ("media.fal_asset_generation", "fal media generation", "api_key", "client_secret", "refresh_token", "provider_url"):
        if forbidden in serialized:
            return fail(f"merchant media summary leaked internal detail: {forbidden}")

    actual_points, actual_source = LocalQueueWorker._reported_media_points(
        {"output_packet": {"usage": {"media_points": 90}}},
        reserved_points=120,
    )
    if actual_points != 90 or actual_source != "provider_usage":
        return fail(f"worker did not use normalized actual media usage: {actual_points}, {actual_source}")
    capped_points, _ = LocalQueueWorker._reported_media_points(
        {"usage": {"media_points": 999}},
        reserved_points=120,
    )
    if capped_points != 120:
        return fail(f"reported usage must never exceed the reserved quote: {capped_points}")
    fallback_points, fallback_source = LocalQueueWorker._reported_media_points({}, reserved_points=120)
    if fallback_points != 120 or fallback_source != "reserved_quote":
        return fail(f"missing provider usage should settle the disclosed quote: {fallback_points}, {fallback_source}")

    print("PASS jiejing_commercial_entitlements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
