#!/usr/bin/env python3
"""Contract tests for one backend-authoritative merchant Listing progress."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.merchant_project_status import _now_iso, build_merchant_project_status  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter, placeholder_count  # noqa: E402


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
    chats: list[dict[str, Any]] = field(default_factory=list)

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

    def list_ai_ceo_chat_history(self, *, company_id: str, user_id: str, limit: int = 30):
        del company_id, user_id, limit
        return list(self.chats)

    def get_task(self, *, company_id, task_id):
        return next((item for item in self.tasks if item.get("company_id") == company_id and item.get("task_id") == task_id), None)

    def get_report_for_company(self, *, company_id, report_id):
        for item in self.reports:
            owner = self.get_task(company_id=company_id, task_id=item.get("task_id"))
            if item.get("report_id") == report_id and owner:
                return {**item, "company_id": company_id, "store_id": owner.get("store_id")}
        return None

    def list_merchant_project_evidence(self, *, company_id, store_id, project_id, user_id, evidence_cutoff):
        del project_id, evidence_cutoff
        tasks = self.list_tasks(company_id=company_id, store_id=store_id)
        task_ids = {item["task_id"] for item in tasks}
        confirmations = [item for item in self.list_confirmations(company_id=company_id) if item.get("store_id") == store_id]
        confirmation_ids = {item["confirmation_id"] for item in confirmations}
        return {
            "tasks": tasks,
            "reports": [item for item in self.list_reports(company_id=company_id) if item.get("task_id") in task_ids],
            "confirmations": confirmations,
            "executions": [item for item in self.list_execution_results(company_id=company_id) if item.get("confirmation_id") in confirmation_ids],
            "media_jobs": self.list_media_asset_jobs(company_id=company_id, store_id=store_id),
            "chat_turns": [item for item in self.chats if not item.get("store_id") or item.get("store_id") == store_id] if user_id else [],
        }


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


def product_bound_task(*, task_id: str = "task-incense-product") -> dict[str, Any]:
    item = task(task_id=task_id)
    item["task_type"] = "ebay_draft_save_intake"
    item["title"] = "eBay draft save intake · 禅意佛手托莲花倒流香炉"
    item["input"] = {
        "listing_project_identity": {
            **IDENTITY,
            "product": "禅意佛手托莲花倒流香炉",
        }
    }
    return item


def ai_attempt_task(*, task_id: str, bound: bool) -> dict[str, Any]:
    item = task(task_id=task_id)
    item["task_type"] = "merchant_ceo_chat_attempt"
    item["title"] = "AI CEO model request attempt"
    item["created_at"] = "2026-08-27T23:56:32Z"
    item["updated_at"] = "2026-08-27T23:58:30Z"
    item["input"] = {"listing_project_identity": IDENTITY} if bound else {"route": "ebay_workflow"}
    return item


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
    item["legacy_project_identity_compatible"] = True
    return item


def unsafe_key_only_media_job() -> dict[str, Any]:
    item = media_job()
    item["media_job_id"] = "media-incense-key-only-unsafe"
    item["job"] = {"listing_project_key": IDENTITY["key"]}
    return item


def chat_turn(identity: dict[str, str] = IDENTITY, *, assistant_id: str = "chat-incense") -> dict[str, Any]:
    return {
        "assistant_id": assistant_id,
        "store_id": "store-a",
        "listing_project_identity": identity,
        "user_text": "继续处理这个禅意倒流香炉。",
        "assistant_text": "商品事实已保存，可以继续生成 Listing 草稿。",
        "status": "model_answered",
        "route": "ebay_workflow",
        "created_at": "2026-08-27T01:01:30Z",
    }


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
        user_id="user-a",
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


class MerchantProjectEvidenceScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-project-evidence-scope-", ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        self.identity = {
            "key": "project-tablet-stand",
            "source_report_id": "report-tablet-source",
            "candidate_id": "candidate-tablet",
        }

    def task(self, identity=None, *, company_id="company-a", store_id="store-a"):
        return self.repository.create_task(
            company_id=company_id, store_id=store_id, user_id="user-a",
            task_type="merchant_product_facts", title="Product information",
            input_data={"listing_project_identity": identity or self.identity},
        )

    def snapshot(self, **kwargs):
        return build_merchant_project_status(
            repository=self.repository, company_id="company-a", store_id="store-a",
            user_id="user-a", project_id=self.identity["key"], **kwargs,
        )

    def confirmation(self, task, identity, *, action_type="save_ebay_listing_draft"):
        return self.repository.create_confirmation(
            company_id=task["company_id"], store_id=task["store_id"], task_id=task["task_id"],
            runtime_run_id="local-fixture", action_type=action_type, title="Local fixture",
            item={"listing_project_identity": identity}, created_by="user-a",
        )

    def media(self, task, identity, *, status="approved_for_listing"):
        return self.repository.create_media_asset_job(
            company_id=task["company_id"], store_id=task["store_id"], task_id=task["task_id"],
            user_id="user-a", provider_job_key="local-fixture-no-provider",
            idempotency_key=f"{task['task_id']}:{identity['key']}:{status}", status=status,
            job_spec={"inputs": {"product_facts": {"listing_project_identity": identity}}},
        )

    def draft_result(self, confirmation):
        return self.repository.save_execution_result(
            confirmation=confirmation,
            result={"status": "saved_to_ebay_draft", "platform_result": {
                "offer_id": "unit-offer", "offer_status": "UNPUBLISHED", "sku": "UNIT-SKU",
                "public_listing_created": False, "published_to_ebay": False,
            }},
        )

    def test_other_projects_cannot_evict_existing_task_and_facts(self):
        source_task = self.repository.create_task(
            company_id="company-a", store_id="store-a", user_id="user-a",
            task_type="merchant_ceo_chat", title="New market project", input_data={"message": "新建商品项目"},
        )
        source_report = self.repository.save_ai_ceo_market_research_report(
            task=source_task, message="新建一个全新商品项目，完成市场调研，给出一个候选商品并推荐。",
            chat={"answer": "候选商品 1：不锈钢咖啡量勺\n推荐度评分：82/100\n最终推荐：不锈钢咖啡量勺。",
                  "route": "ebay_workflow", "status": "model_answered", "answer_quality": {"accepted": True},
                  "source_records": [{"title": "Local fixture", "url": "https://example.test/market"}]},
        )
        self.assertIsNotNone(source_report)
        self.identity = source_report["report"]["listing_project_identity"]
        old_task = self.task()
        facts = self.repository.save_merchant_product_fact_report(
            task=old_task, listing_project_identity=self.identity,
            packet={"product_name": "Tablet stand", "unknown_facts": ["material"],
                    "blocked_by": ["merchant_product_fact_missing:material"]},
        )
        before = self.snapshot()
        self.assertEqual(before["blocker"]["key"], "product_facts_missing")
        for index in range(500):
            self.task({**self.identity, "key": f"unrelated-project-{index}"})
        self.assertIsNotNone(self.repository.get_task(company_id="company-a", task_id=old_task["task_id"]))
        after = self.snapshot()
        self.assertEqual(after["blocker"]["key"], "product_facts_missing")
        self.assertEqual(after["stages"], before["stages"])
        record_ids = {item["record_id"] for item in after["work_record_index"]["items"]}
        self.assertIn(old_task["task_id"], record_ids)
        self.assertIn(facts["report_id"], record_ids)
        self.assertIn(source_task["task_id"], record_ids)
        self.assertIn(source_report["report_id"], record_ids)

    def test_shared_task_other_project_reports_cannot_evict_current_facts(self):
        shared_task = self.task()
        self.repository.save_merchant_product_fact_report(
            task=shared_task, listing_project_identity=self.identity,
            packet={"product_name": "Tablet stand", "unknown_facts": ["material"],
                    "blocked_by": ["merchant_product_fact_missing:material"]},
        )
        before = self.snapshot()
        for index in range(500):
            self.repository.save_merchant_product_fact_report(
                task=shared_task,
                listing_project_identity={**self.identity, "key": f"other-candidate-{index}"},
                packet={"product_name": "Other candidate", "unknown_facts": [], "blocked_by": []},
            )
        after = self.snapshot()
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(after["blocker"]["key"], "product_facts_missing")

    def test_other_projects_cannot_evict_media_or_platform_evidence(self):
        target_task = self.task()
        target_media = self.media(target_task, self.identity)
        target_confirmation = self.confirmation(target_task, self.identity)
        target_execution = self.draft_result(target_confirmation)
        self.repository.sync_ai_ceo_chat_history(
            company_id="company-a", user_id="user-a",
            turns=[{"assistant_id": "chat-target", "user_text": "Continue this product",
                    "assistant_text": "Review the current draft", "listing_project_identity": self.identity}],
        )
        before = self.snapshot(account_health={"status": "restricted"})
        self.assertEqual(before["blocker"]["key"], "ebay_account_restricted")
        other_task = self.task({**self.identity, "key": "other-task-project"})
        for index in range(500):
            other_identity = {**self.identity, "key": f"other-flow-{index}"}
            confirmation = self.confirmation(other_task, other_identity)
            self.draft_result(confirmation)
            if index < 200:
                self.media(other_task, other_identity)
            # The separate 50-turn retention policy is not widened by this
            # project-reader fix; validate reads of an actually retained chat.
            if index < 49:
                self.repository.sync_ai_ceo_chat_history(
                    company_id="company-a", user_id="user-a",
                    turns=[{"assistant_id": f"chat-other-{index}", "user_text": "Other product",
                            "assistant_text": "Another draft", "listing_project_identity": other_identity}],
                )
        after = self.snapshot(account_health={"status": "restricted"})
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(after["blocker"]["key"], "ebay_account_restricted")
        ids = {item["record_id"] for item in after["work_record_index"]["items"]}
        expected_ids = {target_media["media_job_id"], target_confirmation["confirmation_id"],
                        target_execution["execution_id"], "chat-target"}
        self.assertFalse(expected_ids - ids, f"missing project records: {expected_ids - ids}")
        self.assertEqual(after["overall_status"], "blocked")
        self.assertEqual(after["project"]["listing_id"], "")

    def test_cutoff_filters_before_window_with_offset_and_microsecond_precision(self):
        with patch("jiejing_saas.repository.now_iso", return_value="2026-09-05T08:00:00.123455+08:00"):
            old_task = self.task()
            self.repository.save_merchant_product_fact_report(
                task=old_task, listing_project_identity=self.identity,
                packet={"product_name": "Tablet stand", "unknown_facts": ["material"],
                        "blocked_by": ["merchant_product_fact_missing:material"]},
            )
        cutoff = "2026-09-05T00:00:00.123456Z"
        before = self.snapshot(evidence_cutoff=cutoff)
        with patch("jiejing_saas.repository.now_iso", return_value="2026-09-05T00:00:00.123457Z"):
            for _ in range(500):
                self.task()
        after = self.snapshot(evidence_cutoff=cutoff)
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(after["blocker"]["key"], "product_facts_missing")
        self.assertEqual(after["evidence_cutoff"], cutoff)

    def test_scope_and_full_identity_do_not_promote_other_merchant_evidence(self):
        target_task = self.task()
        self.repository.save_merchant_product_fact_report(
            task=target_task, listing_project_identity=self.identity,
            packet={"product_name": "Tablet stand", "unknown_facts": ["material"],
                    "blocked_by": ["merchant_product_fact_missing:material"]},
        )
        before = self.snapshot()
        excluded_ids = set()
        for company, store in (("company-b", "store-a"), ("company-a", "store-b")):
            other_identity = {**self.identity, "candidate_id": "other-candidate"}
            other_task = self.task(other_identity, company_id=company, store_id=store)
            other_facts = self.repository.save_merchant_product_fact_report(
                task=other_task, listing_project_identity=other_identity,
                packet={"product_name": "Other merchant", "unknown_facts": [], "blocked_by": []},
            )
            other_media = self.media(other_task, other_identity)
            other_confirmation = self.confirmation(other_task, other_identity)
            other_execution = self.draft_result(other_confirmation)
            excluded_ids.update((other_task["task_id"], other_facts["report_id"], other_media["media_job_id"],
                                 other_confirmation["confirmation_id"], other_execution["execution_id"]))
        self.repository.sync_ai_ceo_chat_history(
            company_id="company-a", user_id="different-user",
            turns=[{"assistant_id": "other-user-chat", "user_text": "Different account",
                    "assistant_text": "Not this user's project", "listing_project_identity": {
                        **self.identity, "candidate_id": "different-candidate"}}],
        )
        unsafe_media = self.repository.create_media_asset_job(
            company_id="company-a", store_id="store-a", task_id=target_task["task_id"], user_id="user-a",
            provider_job_key="local-fixture", idempotency_key="unsafe-key-only", status="approved_for_listing",
            job_spec={"listing_project_key": self.identity["key"]},
        )
        excluded_ids.add(unsafe_media["media_job_id"])
        after = self.snapshot()
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(after["blocker"]["key"], "product_facts_missing")
        ids = {item["record_id"] for item in after["work_record_index"]["items"]}
        self.assertFalse(ids & excluded_ids)
        self.assertNotIn("other-user-chat", ids)
        conflict_task = self.task({**self.identity, "candidate_id": "conflicting-candidate"})
        self.assertEqual(self.snapshot()["blocker"]["key"], "listing_project_identity_conflict")
        self.assertIsNotNone(conflict_task)

    def test_postgres_native_rows_and_parameterized_query_contract(self):
        """Replay the real PG adapter contract; not a PostgreSQL server test."""
        target_task = self.task()
        self.repository.save_merchant_product_fact_report(
            task=target_task, listing_project_identity=self.identity,
            packet={"product_name": "Tablet stand", "unknown_facts": ["material"],
                    "blocked_by": ["merchant_product_fact_missing:material"]},
        )
        self.media(target_task, self.identity)
        self.draft_result(self.confirmation(target_task, self.identity))
        self.repository.sync_ai_ceo_chat_history(
            company_id="company-a", user_id="user-a",
            turns=[{"assistant_id": "pg-chat", "user_text": "Current project",
                    "assistant_text": "Current answer", "listing_project_identity": self.identity}],
        )
        expected = self.snapshot(account_health={"status": "restricted"})
        tables = ("tasks", "reports", "confirmations", "execution_results", "media_asset_jobs", "ai_ceo_chat_turns")
        native_rows = {}
        with self.repository._connect() as connection:
            for table in tables:
                rows = [dict(row) for row in connection.execute(f"select * from {table}").fetchall()]
                for row in rows:
                    for key, value in list(row.items()):
                        if key.endswith("_json"):
                            row[key] = json.loads(value)
                        elif key in {"created_at", "updated_at"}:
                            row[key] = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                                timezone(timedelta(hours=8)))
                    if table == "reports":
                        row.update(company_id="company-a", store_id="store-a")
                native_rows[table] = rows
        observed_queries = []
        testcase = self

        class NativeCursor:
            def execute(self, sql, params):
                testcase.assertEqual(placeholder_count(sql), len(params))
                testcase.assertNotIn("json_extract", sql)
                testcase.assertNotIn("jiejing_evidence_time", sql)
                testcase.assertNotIn("project-tablet-stand", sql)
                testcase.assertEqual(params[0], "company-a")
                observed_queries.append(sql)
                if "where t.company_id = %s and r.report_id = %s" in sql:
                    self.rows = []  # No fabricated source report for this fixture.
                else:
                    testcase.assertIn("#>>", sql)
                    self.rows = next(native_rows[table] for table in tables if f"from {table} " in sql)

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class NativeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return NativeCursor()

        with patch.object(self.repository, "database_engine", "postgres"), \
                patch.object(self.repository, "_postgres_initialized", True), \
                patch.object(self.repository, "_connect", return_value=PostgresConnectionAdapter(NativeConnection())):
            observed = self.snapshot(account_health={"status": "restricted"})
        self.assertEqual(len(observed_queries), 7)
        self.assertEqual(observed["stages"], expected["stages"])
        self.assertEqual(observed["blocker"], expected["blocker"])
        self.assertEqual(observed["project"], expected["project"])
        self.assertEqual(observed["work_record_index"]["counts"], expected["work_record_index"]["counts"])

    def test_source_report_and_task_survive_the_projects_own_bounded_windows(self):
        source_task = self.repository.create_task(
            company_id="company-a", store_id="store-a", user_id="user-a",
            task_type="merchant_ceo_chat", title="New market project", input_data={"message": "新建商品项目"},
        )
        source_report = self.repository.save_ai_ceo_market_research_report(
            task=source_task, message="新建一个全新商品项目，完成市场调研，给出一个候选商品并推荐。",
            chat={"answer": "候选商品 1：不锈钢咖啡量勺\n推荐度评分：82/100\n最终推荐：不锈钢咖啡量勺。",
                  "route": "ebay_workflow", "status": "model_answered", "answer_quality": {"accepted": True},
                  "source_records": [{"title": "Local fixture", "url": "https://example.test/market"}]},
        )
        self.identity = source_report["report"]["listing_project_identity"]
        self.assertEqual(self.snapshot()["stages"][1]["status"], "completed")
        for _ in range(500):
            self.repository.save_merchant_product_fact_report(
                task=self.task(), listing_project_identity=self.identity,
                packet={"product_name": "Current product", "unknown_facts": ["material"],
                        "blocked_by": ["merchant_product_fact_missing:material"]},
            )
        after = self.snapshot()
        self.assertEqual(after["stages"][1]["status"], "completed")
        self.assertEqual(after["blocker"]["key"], "product_facts_missing")
        self.assertEqual(after["work_record_index"]["counts"]["task"], 501)

    def test_secondary_identity_cannot_fill_the_current_projects_media_window(self):
        target_task = self.task()
        self.media(target_task, self.identity)
        self.assertEqual(self.snapshot()["stages"][3]["status"], "completed")
        for index in range(200):
            self.repository.create_media_asset_job(
                company_id="company-a", store_id="store-a", task_id=target_task["task_id"], user_id="user-a",
                provider_job_key="local-fixture", idempotency_key=f"conflicting-media-{index}", status="approved_for_listing",
                job_spec={"listing_project_identity": {**self.identity, "key": f"other-primary-{index}"},
                          "inputs": {"product_facts": {"listing_project_identity": self.identity}}},
            )
        self.assertEqual(self.snapshot()["stages"][3]["status"], "completed")

    def test_exact_source_lookup_cannot_promote_an_explicit_other_project(self):
        other_identity = {**self.identity, "key": "explicit-other-project"}
        other_task = self.task(other_identity)
        other_report = self.repository.save_merchant_product_fact_report(
            task=other_task, listing_project_identity=other_identity,
            packet={"product_name": "Another product", "unknown_facts": [], "blocked_by": []},
        )
        self.identity = {**self.identity, "source_report_id": other_report["report_id"]}
        self.task()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["stages"][1]["status"], "waiting")
        record_ids = {item["record_id"] for item in snapshot["work_record_index"]["items"]}
        self.assertNotIn(other_report["report_id"], record_ids)
        self.assertNotIn(other_task["task_id"], record_ids)


def main() -> None:
    scope_result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(MerchantProjectEvidenceScopeTest)
    )
    assert scope_result.wasSuccessful(), "real-repository project evidence regressions failed"
    assert "." in _now_iso().removesuffix("Z")

    with tempfile.TemporaryDirectory(prefix="jiejing-new-market-project-status-", ignore_cleanup_errors=True) as temp:
        repository = SaaSRepository(Path(temp) / "saas.sqlite")
        unbound_task = repository.create_task(
            company_id="company-new-market-project",
            store_id="store-new-market-project",
            user_id="user-new-market-project",
            task_type="merchant_ceo_chat",
            title="AI CEO brand-new market research",
            input_data={"message": "新建一个全新商品项目。"},
        )
        saved_market_report = repository.save_ai_ceo_market_research_report(
            task=unbound_task,
            message="新建一个全新商品项目，完成市场调研，给出一个候选商品并推荐。",
            chat={
                "answer": "候选商品 1：不锈钢咖啡量勺\n推荐度评分：82/100\n最终推荐：不锈钢咖啡量勺。",
                "route": "ebay_workflow",
                "status": "model_answered",
                "answer_quality": {"accepted": True},
                "source_records": [{"title": "Market source", "url": "https://example.com/market"}],
            },
        )
        assert saved_market_report is not None
        generated_identity = saved_market_report["report"].get("listing_project_identity") or {}
        assert generated_identity.get("key", "").startswith("listing-project-"), generated_identity
        assert not (unbound_task.get("input") or {}).get("listing_project_identity"), unbound_task
        unrelated_task = repository.create_task(
            company_id="company-new-market-project",
            store_id="store-new-market-project",
            user_id="user-new-market-project",
            task_type="merchant_product_facts",
            title="Unbound facts task for the same store",
            input_data={"product_name": "不锈钢咖啡量勺"},
        )
        unrelated_facts_report = repository.save_merchant_product_fact_report(
            task=unrelated_task,
            packet={
                "product_name": "不锈钢咖啡量勺",
                "unknown_facts": ["material"],
                "blocked_by": ["product_fact_missing:material"],
            },
            listing_project_identity=generated_identity,
        )
        generated_snapshot = build_merchant_project_status(
            repository=repository,
            company_id="company-new-market-project",
            store_id="store-new-market-project",
            user_id="user-new-market-project",
            project_id=generated_identity["key"],
            account_health={"status": "healthy"},
        )
        generated_stages = {stage["key"]: stage for stage in generated_snapshot["stages"]}
        assert generated_stages["intake"]["status"] == "completed", generated_snapshot
        assert generated_stages["research"]["status"] == "completed", generated_snapshot
        assert generated_snapshot["current_stage"] == "facts", generated_snapshot
        assert generated_snapshot["blocker"]["key"] != "project_evidence_missing", generated_snapshot
        assert generated_snapshot["next_action"]["action"] == "complete_product_facts", generated_snapshot
        generated_record_ids = {
            item["record_id"] for item in generated_snapshot["work_record_index"]["items"]
        }
        assert unbound_task["task_id"] in generated_record_ids, generated_snapshot
        assert saved_market_report["report_id"] in generated_record_ids, generated_snapshot
        assert unrelated_facts_report["report_id"] in generated_record_ids, generated_snapshot
        assert unrelated_task["task_id"] not in generated_record_ids, generated_snapshot

    empty = build(FixtureRepository())
    assert_single_progress(empty)
    assert empty["current_stage"] == "intake"
    assert empty["blocker"]["key"] == "project_evidence_missing"

    facts_blocked = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(unknown=["package_weight_g", "selling_price"])],
            chats=[chat_turn()],
        )
    )
    assert_single_progress(facts_blocked)
    assert facts_blocked["current_stage"] == "facts"
    assert facts_blocked["blocker"]["key"] == "product_facts_missing"
    assert facts_blocked["next_action"]["action"] == "complete_product_facts"
    mismatched_fact_report = fact_report(unknown=["package_weight_g", "selling_price", "material"])
    mismatched_fact_report["report"]["merchant_product_fact_packet"]["blocked_by"].append(
        "merchant_product_fact_missing:source_rights"
    )
    mismatched_fact_counts = build(
        FixtureRepository(tasks=[task()], reports=[market_report(), mismatched_fact_report])
    )
    current_fact_stage = next(stage for stage in mismatched_fact_counts["stages"] if stage["key"] == "facts")
    assert current_fact_stage["detail"] == "4 项待补"
    assert mismatched_fact_counts["blocker"]["detail"] == "还有 4 项商品资料待商家确认。"
    record_index = facts_blocked["work_record_index"]
    assert record_index["contract_version"] == "merchant_project_work_record_index_v1"
    assert record_index["current_project_only"] is True
    indexed_ids = {item["record_id"] for item in record_index["items"]}
    assert {"chat-incense", "report-incense-facts", "task-incense"}.issubset(indexed_ids)
    assert all(
        item["target_view"] in {"cockpit", "activity", "product", "media", "confirm", "service"}
        for item in record_index["items"]
    )

    technical_tasks_do_not_relabel_product = build(
        FixtureRepository(
            tasks=[
                product_bound_task(),
                ai_attempt_task(task_id="task-bound-ai-attempt", bound=True),
                ai_attempt_task(task_id="task-unbound-ai-attempt", bound=False),
            ],
            reports=[market_report()],
        )
    )
    assert technical_tasks_do_not_relabel_product["project"]["product_name"] == "禅意佛手托莲花倒流香炉"
    technical_record_ids = {
        item["record_id"] for item in technical_tasks_do_not_relabel_product["work_record_index"]["items"]
    }
    assert "task-bound-ai-attempt" in technical_record_ids
    assert "task-unbound-ai-attempt" not in technical_record_ids
    bound_attempt_record = next(
        item
        for item in technical_tasks_do_not_relabel_product["work_record_index"]["items"]
        if item["record_id"] == "task-bound-ai-attempt"
    )
    assert bound_attempt_record["title"] == "AI CEO 处理记录"
    assert bound_attempt_record["summary"] == "AI CEO 本轮处理留痕。"
    assert all(
        item["title"] != "AI CEO model request attempt"
        for item in technical_tasks_do_not_relabel_product["work_record_index"]["items"]
    )

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

    unsafe_key_only = build(
        FixtureRepository(
            tasks=[task()],
            reports=[market_report(), fact_report(), listing_report()],
            media=[unsafe_key_only_media_job()],
        )
    )
    assert unsafe_key_only["stages"][3]["status"] == "waiting"
    assert "media-incense-key-only-unsafe" not in {
        item["record_id"] for item in unsafe_key_only["work_record_index"]["items"]
    }

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
