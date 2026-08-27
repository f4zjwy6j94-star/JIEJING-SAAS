#!/usr/bin/env python3
"""Contract tests for one backend-authoritative merchant Listing progress."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.merchant_project_status import _now_iso, build_merchant_project_status  # noqa: E402


IDENTITY = {
    "key": "project-incense",
    "source_report_id": "report-incense-market",
    "candidate_id": "candidate-incense",
}
SKU = "JJ-INCENSE-JC2023041300002-01"
OFFER_ID = "245675556011"


@dataclass
class FixtureRepository:
    tasks: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    confirmations: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)

    def list_tasks(self, *, company_id: str, store_id: str | None = None, limit: int | None = None):
        del limit
        return [
            item
            for item in self.tasks
            if item.get("company_id") == company_id and (not store_id or item.get("store_id") == store_id)
        ]

    def list_reports(self, *, company_id: str, task_id: str | None = None, limit: int | None = None):
        del limit
        task_ids = {item["task_id"] for item in self.tasks if item.get("company_id") == company_id}
        return [
            item
            for item in self.reports
            if item.get("task_id") in task_ids and (not task_id or item.get("task_id") == task_id)
        ]

    def list_confirmations(self, *, company_id: str, status: str | None = None, limit: int | None = None):
        del limit
        return [
            item
            for item in self.confirmations
            if item.get("company_id") == company_id and (not status or item.get("status") == status)
        ]

    def list_execution_results(self, *, company_id: str, limit: int | None = None):
        del limit
        confirmation_ids = {
            item["confirmation_id"]
            for item in self.confirmations
            if item.get("company_id") == company_id
        }
        return [item for item in self.executions if item.get("confirmation_id") in confirmation_ids]

    def list_media_asset_jobs(
        self,
        *,
        company_id: str,
        store_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ):
        del limit
        return [
            item
            for item in self.media
            if item.get("company_id") == company_id
            and (not store_id or item.get("store_id") == store_id)
            and (not status or item.get("status") == status)
        ]


def task(identity: dict[str, str] = IDENTITY, *, task_id: str = "task-incense", store_id: str = "store-a") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "company_id": "company-a",
        "store_id": store_id,
        "task_type": "merchant_product_facts",
        "status": "completed",
        "created_at": "2026-08-27T01:00:00Z",
        "updated_at": "2026-08-27T01:00:00Z",
        "input": {"listing_project_identity": identity},
        "output": {},
    }


def market_report() -> dict[str, Any]:
    return {
        "report_id": IDENTITY["source_report_id"],
        "task_id": "task-incense",
        "report_type": "ai_ceo.market_research",
        "status": "saved",
        "created_at": "2026-08-27T01:01:00Z",
        "report": {"secret_exposed": False},
    }


def fact_report(*, unknown: list[str] | None = None) -> dict[str, Any]:
    missing = list(unknown or [])
    return {
        "report_id": "report-incense-facts",
        "task_id": "task-incense",
        "report_type": "merchant.product_facts",
        "status": "saved",
        "created_at": "2026-08-27T01:02:00Z",
        "report": {
            "listing_project_identity": IDENTITY,
            "merchant_product_fact_packet": {
                "product_name": "禅意佛手托莲花倒流香炉",
                "merchant_confirmed_facts": {"sku": SKU},
                "unknown_facts": missing,
                "blocked_by": [f"merchant_product_fact_missing:{key}" for key in missing],
            },
            "secret_exposed": False,
        },
    }


def listing_report() -> dict[str, Any]:
    return {
        "report_id": "report-incense-listing",
        "task_id": "task-incense",
        "report_type": "listing.package",
        "status": "completed",
        "created_at": "2026-08-27T01:03:00Z",
        "report": {
            "listing_project_identity": IDENTITY,
            "sections": {"sku": SKU, "title": "Zen Hand Lotus Backflow Incense Burner"},
            "secret_exposed": False,
        },
    }


def media_job() -> dict[str, Any]:
    return {
        "media_job_id": "media-incense",
        "company_id": "company-a",
        "store_id": "store-a",
        "task_id": "task-incense",
        "status": "approved_for_listing",
        "created_at": "2026-08-27T01:02:30Z",
        "updated_at": "2026-08-27T01:02:45Z",
        "job": {"listing_project_identity": IDENTITY},
        "asset_review": {"status": "approved_for_listing_draft"},
        "asset_manifest": [{"listing_use_status": "approved_for_listing_draft"}],
        "merchant_review": {"decision": "approve_for_listing_draft"},
        "secret_exposed": False,
    }


def legacy_keyed_media_job(*, status: str = "approved_for_listing") -> dict[str, Any]:
    item = media_job()
    item["media_job_id"] = "media-incense-legacy-key"
    item["status"] = status
    item["job"] = {"listing_project_key": IDENTITY["key"]}
    return item


def draft_confirmation(identity: dict[str, str] = IDENTITY) -> dict[str, Any]:
    return {
        "confirmation_id": "confirm-incense-draft",
        "company_id": "company-a",
        "store_id": "store-a",
        "task_id": "task-incense",
        "action_type": "save_ebay_listing_draft",
        "status": "executed",
        "created_at": "2026-08-27T01:04:00Z",
        "item": {
            "listing_project_identity": identity,
            "publish_payload": {"listing": {"sku": SKU}},
        },
    }


def draft_execution() -> dict[str, Any]:
    return {
        "execution_id": "exec-incense-draft",
        "confirmation_id": "confirm-incense-draft",
        "task_id": "task-incense",
        "action_type": "save_ebay_listing_draft",
        "status": "saved_to_ebay_draft",
        "created_at": "2026-08-27T01:04:30Z",
        "result": {
            "status": "saved_to_ebay_draft",
            "platform_result": {
                "offer_id": OFFER_ID,
                "offer_status": "UNPUBLISHED",
                "sku": SKU,
                "public_listing_created": False,
                "published_to_ebay": False,
            },
        },
    }


def publish_confirmation(identity: dict[str, str] = IDENTITY, *, status: str = "executed") -> dict[str, Any]:
    return {
        "confirmation_id": "confirm-incense-publish",
        "company_id": "company-a",
        "store_id": "store-a",
        "task_id": "task-incense",
        "action_type": "publish_listing",
        "status": status,
        "created_at": "2026-08-27T01:05:00Z",
        "item": {
            "listing_project_identity": identity,
            "existing_ebay_draft": {"offer_id": OFFER_ID, "sku": SKU},
        },
    }


def publish_execution() -> dict[str, Any]:
    return {
        "execution_id": "exec-incense-publish",
        "confirmation_id": "confirm-incense-publish",
        "task_id": "task-incense",
        "action_type": "publish_listing",
        "status": "published_to_ebay",
        "created_at": "2026-08-27T01:05:30Z",
        "result": {
            "status": "published_to_ebay",
            "platform_result": {
                "listing_id": "listing-incense-001",
                "offer_id": OFFER_ID,
                "sku": SKU,
                "published_to_ebay": True,
                "public_listing_created": True,
            },
        },
    }


def build(repo: FixtureRepository, *, account_health: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_merchant_project_status(
        repository=repo,
        company_id="company-a",
        store_id="store-a",
        project_id=IDENTITY["key"],
        account_health=account_health or {"status": "healthy"},
        evidence_cutoff="2026-08-28T00:00:00Z",
    )


def assert_single_progress(snapshot: dict[str, Any]) -> None:
    assert snapshot["snapshot_version"] == "merchant_project_status_v1"
    assert snapshot["evidence_cutoff"] == "2026-08-28T00:00:00Z"
    assert len(snapshot["stages"]) == 8
    assert sum(1 for stage in snapshot["stages"] if stage["is_current"]) == 1
    assert isinstance(snapshot["blocker"], dict)
    assert isinstance(snapshot["next_action"], dict)
    assert snapshot["secret_exposed"] is False
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    for forbidden in ("secret_ref", "evidence_path", "provider_job", "queue_job", "access_token"):
        assert forbidden not in serialized


def main() -> None:
    assert "." in _now_iso().removesuffix("Z")

    empty = build(FixtureRepository())
    assert_single_progress(empty)
    assert empty["current_stage"] == "intake"
    assert empty["blocker"]["key"] == "project_evidence_missing"

    facts_blocked = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(unknown=["package_weight_g", "selling_price"])],
        )
    )
    assert_single_progress(facts_blocked)
    assert facts_blocked["current_stage"] == "facts"
    assert facts_blocked["blocker"]["key"] == "product_facts_missing"
    assert facts_blocked["next_action"]["action"] == "complete_product_facts"

    legacy_media_ready = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[legacy_keyed_media_job()],
        )
    )
    assert_single_progress(legacy_media_ready)
    assert legacy_media_ready["stages"][3]["status"] == "completed"
    assert legacy_media_ready["current_stage"] == "ebay_draft"

    draft_saved = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[media_job()],
            confirmations=[draft_confirmation()],
            executions=[draft_execution()],
        )
    )
    assert_single_progress(draft_saved)
    assert draft_saved["current_stage"] == "publish"
    assert draft_saved["project"]["sku"] == SKU
    assert draft_saved["project"]["offer_id"] == OFFER_ID
    assert draft_saved["stages"][5]["status"] == "completed"
    assert draft_saved["stages"][6]["status"] == "waiting"

    historical_failed_media = media_job()
    historical_failed_media["media_job_id"] = "media-incense-v1"
    historical_failed_media["status"] = "needs_rework"
    historical_failed_media["created_at"] = "2026-08-27T01:02:10Z"
    historical_failed_media["updated_at"] = "2026-08-27T01:02:20Z"
    rework_approved = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[historical_failed_media, media_job()],
            confirmations=[draft_confirmation()],
            executions=[draft_execution()],
        )
    )
    assert_single_progress(rework_approved)
    assert rework_approved["stages"][3]["status"] == "completed"
    assert rework_approved["current_stage"] == "publish"
    assert rework_approved["blocker"]["key"] != "media_review_or_generation_failed"

    downstream_draft_closes_stale_prerequisites = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(unknown=["package_weight_g", "selling_price"]), listing_report()],
            media=[legacy_keyed_media_job(status="needs_rework")],
            confirmations=[draft_confirmation()],
            executions=[draft_execution()],
        )
    )
    assert_single_progress(downstream_draft_closes_stale_prerequisites)
    assert downstream_draft_closes_stale_prerequisites["current_stage"] == "publish"
    assert all(
        stage["status"] == "completed"
        for stage in downstream_draft_closes_stale_prerequisites["stages"][:6]
    )
    assert downstream_draft_closes_stale_prerequisites["blocker"]["key"] != "product_facts_missing"
    assert downstream_draft_closes_stale_prerequisites["blocker"]["key"] != "media_review_or_generation_failed"

    restricted = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[media_job()],
            confirmations=[draft_confirmation()],
            executions=[draft_execution()],
        ),
        account_health={"status": "restricted", "onboarding_stage": "account_review_required"},
    )
    assert restricted["current_stage"] == "publish"
    assert restricted["blocker"]["key"] == "ebay_account_restricted"
    assert restricted["next_action"]["action"] == "wait_for_ebay_account_review"

    published = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[media_job()],
            confirmations=[draft_confirmation(), publish_confirmation()],
            executions=[draft_execution(), publish_execution()],
        )
    )
    assert_single_progress(published)
    assert published["current_stage"] == "records"
    assert published["overall_status"] == "published"
    assert published["project"]["listing_id"] == "listing-incense-001"
    assert published["stages"][6]["status"] == "completed"
    assert published["stages"][7]["status"] == "completed"
    assert published["blocker"]["key"] == "none"

    conflict_identity = {**IDENTITY, "candidate_id": "candidate-other"}
    conflicted = build(
        FixtureRepository(
            tasks=[task(), task(conflict_identity, task_id="task-conflict")],
            reports=[market_report(), fact_report()],
        )
    )
    assert_single_progress(conflicted)
    assert conflicted["overall_status"] == "blocked"
    assert conflicted["blocker"]["key"] == "listing_project_identity_conflict"

    historical_identity = {
        "key": "project-old-phone-case",
        "source_report_id": "report-old-case",
        "candidate_id": "candidate-old-case",
    }
    old_confirmation = publish_confirmation(historical_identity)
    old_confirmation["confirmation_id"] = "confirm-old-phone-case"
    old_confirmation["item"]["existing_ebay_draft"] = {"offer_id": "OLD-OFFER", "sku": "OLD-CASE-SKU"}
    old_execution = publish_execution()
    old_execution["confirmation_id"] = "confirm-old-phone-case"
    old_execution["result"]["platform_result"] = {
        "listing_id": "old-phone-case-listing",
        "offer_id": "OLD-OFFER",
        "sku": "OLD-CASE-SKU",
        "published_to_ebay": True,
        "public_listing_created": True,
    }
    isolated = build(
        FixtureRepository(
            tasks=[task(), task(historical_identity, task_id="task-old")],
            reports=[market_report(), fact_report(unknown=["selling_price"])],
            confirmations=[old_confirmation],
            executions=[old_execution],
        )
    )
    assert isolated["current_stage"] == "facts"
    assert isolated["project"]["sku"] in {"", SKU}
    assert isolated["project"]["offer_id"] == ""
    assert isolated["project"]["listing_id"] == ""
    assert isolated["overall_status"] != "published"

    wrong_store = task(store_id="store-b")
    cross_store = build(FixtureRepository(tasks=[wrong_store]))
    assert cross_store["blocker"]["key"] == "project_evidence_missing"

    local_timezone_task = task()
    local_timezone_task["created_at"] = "2026-08-28T03:00:00+08:00"
    local_timezone_task["updated_at"] = "2026-08-28T03:00:01+08:00"
    mixed_timezone = build(FixtureRepository(tasks=[local_timezone_task]))
    assert mixed_timezone["stages"][0]["status"] == "completed"
    assert mixed_timezone["blocker"]["key"] != "project_evidence_missing"

    print("PASS jiejing_listing_single_progress")


if __name__ == "__main__":
    main()
