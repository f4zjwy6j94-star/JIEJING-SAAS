#!/usr/bin/env python3
"""Regression for C-class model value rehearsal over sanitized packets."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.model_clients import ModelClient  # noqa: E402
from jiejing_runtime.models import JiejingTask  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.model_value_gate import build_model_value_gate  # noqa: E402
from jiejing_saas.model_value_rehearsal import run_model_value_rehearsal  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-model-value-rehearsal-test"


class FakeLiveModelClient(ModelClient):
    name = "fake-live-model-client"
    version = "c-class-test"

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        sections = task.output_contract.get("required_sections", [])
        return {
            "model_mode": "live_http_model",
            "model_configured": True,
            "merchant_readable_summary": f"Live-model rehearsal output for {task.task_type}.",
            "sections": {
                section: f"model-assisted {section}; source gaps stay labeled; confirmation remains required"
                for section in sections
            },
            "limits": ["Fake model client used for C-class regression only."],
        }


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "model-value.sqlite"
    runtime_db_path = OUT / "runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    previous = _set_model_env()
    try:
        settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
        repo = SaaSRepository(db_path)
        fixture = repo.create_user_with_company(
            email="model-value@jiejing.local",
            password="local-model-value-password",
            company_name="Jiejing Model Value Test",
        )
        user = fixture["user"]
        company = fixture["company"]
        store = repo.create_store(
            company_id=company["company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "northvalesource", "marketplace": "EBAY_US"},
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
                "resource_count": 6,
                "present_resource_keys": [
                    "store_profile",
                    "account_business_policies",
                    "inventory_and_offers",
                    "orders_and_fulfillment",
                    "finances",
                    "taxonomy_listing_metadata",
                ],
                "missing_resource_keys": [],
                "sections": [
                    {"key": "store_profile", "data": {"marketplace_id": "EBAY_US"}, "source_type": "official_api"},
                    {
                        "key": "account_business_policies",
                        "data": {
                            "fulfillment_policy_id": "fulfillmentPolicyId UNIT-FULFILLMENT",
                            "payment_policy_id": "paymentPolicyId UNIT-PAYMENT",
                            "return_policy_id": "returnPolicyId UNIT-RETURN",
                        },
                        "source_type": "official_api",
                    },
                    {"key": "inventory_and_offers", "data": {"sku": "UNIT-SPOONS", "listing_title": "Stainless Steel Measuring Spoons"}, "source_type": "official_api"},
                    {"key": "orders_and_fulfillment", "data": {"order_count": 2}, "source_type": "official_api"},
                    {"key": "finances", "data": {"transaction_count": 3}, "source_type": "official_api"},
                    {"key": "taxonomy_listing_metadata", "data": {"category_id": "20625", "required_aspects": ["Brand", "Material"]}, "source_type": "official_api"},
                ],
                "lineage": {"probe_live_read_performed": True},
                "safe_for_real_platform_write": False,
                "secret_exposed": False,
            },
        )
        blocked = run_model_value_rehearsal(
            settings=settings,
            repository=repo,
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            packet_id=packet["packet_id"],
            product="Stainless Steel Measuring Spoons",
            allow_live_model=False,
        )
        if blocked.get("status") != "blocked_before_model_rehearsal":
            return fail("rehearsal should block unless live model use is explicitly allowed or injected")
        if "live_model_rehearsal_not_requested" not in blocked.get("blockers", []):
            return fail("blocked rehearsal should explain live model gate")
        completed = run_model_value_rehearsal(
            settings=settings,
            repository=repo,
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            packet_id=packet["packet_id"],
            product="Stainless Steel Measuring Spoons",
            merchant_goal="Prove model-backed Market Report and Listing Package over official packet.",
            allow_live_model=True,
            model_client=FakeLiveModelClient(),
        )
        if completed.get("status") != "completed":
            return fail("injected live model rehearsal should complete")
        if set(completed.get("live_model_report_types", [])) != {"market.report", "listing.package"}:
            return fail("rehearsal should create live model evidence for market and listing reports")
        if completed.get("runtime_gets_raw_ebay_token") is not False or completed.get("frontend_gets_model_api_key") is not False:
            return fail("model value rehearsal must preserve token and model-key boundaries")
        reports = repo.list_reports(company_id=company["company_id"])
        report_types = {item.get("report_type") for item in reports}
        if not {"market.report", "listing.package"}.issubset(report_types):
            return fail("model value rehearsal should persist market and listing reports")
        for report in reports:
            if report.get("report_type") not in {"market.report", "listing.package"}:
                continue
            if not _contains_cjk(str(report.get("title") or "")):
                return fail(f"merchant-visible report title should be Chinese: {report.get('title')}")
            payload = report.get("report") if isinstance(report.get("report"), dict) else {}
            serialized_report = json.dumps(payload, ensure_ascii=False)
            if "Live-model rehearsal output" in serialized_report or "model-assisted" in serialized_report:
                return fail("model value rehearsal should repair English-heavy merchant-visible model output before saving")
            report_body = payload.get("report") if isinstance(payload.get("report"), dict) else payload
            if not _contains_cjk(str(report_body.get("merchant_readable_summary") or "")):
                return fail("merchant-readable report summary should be Chinese")
        gate = build_model_value_gate(settings, repo)
        if gate.get("ready_for_paid_value_claim") is not True:
            return fail("model value gate should pass when env is configured and live report evidence exists")
        if set((gate.get("evidence") or {}).get("live_model_report_types", [])) != {"market.report", "listing.package"}:
            return fail("model value gate should read persisted live model evidence")
        if set((gate.get("evidence") or {}).get("source_packet_linked_live_report_types", [])) != {"market.report", "listing.package"}:
            return fail("model value gate should require live reports to link back to a sanitized official packet")
        if (gate.get("evidence") or {}).get("sanitized_official_packet_count_sampled") != 1:
            return fail("model value gate should sample the sanitized official packet source chain")

        smoke_fixture = repo.create_user_with_company(
            email="codex-model-value-noise@local.invalid",
            password="local-smoke-password",
            company_name="Codex Browser Smoke",
        )
        smoke_user = smoke_fixture["user"]
        smoke_company = smoke_fixture["company"]
        smoke_store = repo.create_store(
            company_id=smoke_company["company_id"],
            user_id=smoke_user["user_id"],
            payload={
                "platform": "ebay",
                "store_name": "Codex UI Smoke Store",
                "marketplace": "EBAY_US",
                "settings": {"created_from": "codex_browser_smoke"},
            },
        )
        smoke_task = repo.create_task(
            company_id=smoke_company["company_id"],
            store_id=smoke_store["store_id"],
            user_id=smoke_user["user_id"],
            task_type="browser_smoke",
            title="Synthetic browser smoke noise",
            input_data={"created_from": "codex_browser_smoke"},
        )
        repo.save_runtime_outputs(
            task=smoke_task,
            runtime_result={
                "run_id": "browser-smoke-noise",
                "results": [
                    {
                        "task_type": "market.report",
                        "status": "completed",
                        "summary": f"Synthetic smoke report {index}",
                        "report": {"model_mode": "deterministic_fallback"},
                    }
                    for index in range(120)
                ],
                "confirmations": [],
            },
        )
        noisy_gate = build_model_value_gate(settings, repo)
        if noisy_gate.get("ready_for_paid_value_claim") is not True:
            return fail("synthetic browser smoke reports must not displace controlled model value proof")
        if set((noisy_gate.get("evidence") or {}).get("live_model_report_types", [])) != {"market.report", "listing.package"}:
            return fail("controlled live-model proof must remain visible after high-volume smoke reports")

        launch_gate = build_commercial_launch_gate(settings, repo)
        launch_groups = {item.get("key"): item for item in launch_gate.get("groups", [])}
        if launch_groups.get("official_ebay_read_loop", {}).get("status") != "ready":
            return fail("commercial launch gate should recognize the official packet proof")
        if launch_groups.get("model_agent_value", {}).get("status") != "ready":
            return fail("commercial launch gate should recognize model-backed Agent value proof")
        if launch_gate.get("paid_commercial_launch_ready") is not False:
            return fail("commercial launch gate must stay blocked until managed infra, billing and backups are ready")
        if launch_gate.get("real_platform_writes_enabled") is not False:
            return fail("commercial launch gate must not enable real writes")
        serialized = json.dumps({"completed": completed, "reports": reports, "gate": gate}, ensure_ascii=False)
        for forbidden in ["access_token", "refresh_token", "client_secret", "UNIT-SECRET", "published_to_ebay\": true"]:
            if forbidden in serialized:
                return fail(f"model value rehearsal leaked forbidden marker: {forbidden}")
        print("PASS jiejing_model_value_rehearsal")
        return 0
    finally:
        _restore_env(previous)


def _set_model_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_MODEL_PROVIDER",
        "JIEJING_MODEL_API_KEY",
        "JIEJING_MODEL_BASE_URL",
        "JIEJING_MODEL",
        "JIEJING_MODEL_DISABLE_LIVE",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
        "JIEJING_EBAY_WRITE_LIVE",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_MODEL_PROVIDER": "chat",
            "JIEJING_MODEL_API_KEY": "unit-model-key-not-returned",
            "JIEJING_MODEL_BASE_URL": "https://model.example/v1",
            "JIEJING_MODEL": "unit-model",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
        }
    )
    os.environ.pop("JIEJING_MODEL_DISABLE_LIVE", None)
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


if __name__ == "__main__":
    raise SystemExit(main())
