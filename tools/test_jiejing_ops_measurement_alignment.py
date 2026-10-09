"""Isolated synthetic analytics regression; never reads the production database."""
import sys
import gc
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiejing_saas.operations_metering import hash_analytics_identifier, sanitize_analytics_event
from jiejing_saas.repository import SaaSRepository


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jiejing-ops-alignment-", dir=os.environ.get("JIEJING_TEST_OUTPUT_DIR"))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.repo = SaaSRepository(Path(self.tmp.name) / "synthetic.sqlite", database_engine="sqlite")
        self.now = datetime(2026, 10, 8, 17, 30, tzinfo=timezone.utc)

    def event(self, key, visitor, timestamp, **kwargs):
        digest = hash_analytics_identifier(key + visitor + timestamp)
        self.repo.record_platform_analytics_event(event_key=key, page_key="landing", event_id_hash=digest, visitor_hash=hash_analytics_identifier(visitor), session_hash=hash_analytics_identifier(visitor), **kwargs)
        with self.repo._connect() as conn:
            conn.execute("update platform_analytics_events set occurred_at = ? where event_id_hash = ?", (timestamp, digest))

    def test_summary_matches_trend_and_excludes_future_and_performance(self):
        self.event("page_view", "visible", "2026-10-09T01:00:00+08:00")
        self.event("performance_sample", "only-performance", "2026-10-08T17:00:00+00:00")
        self.event("page_view", "future", "2026-10-09T02:00:00+08:00")
        result = self.repo.platform_operations_overview(period_days=1, now_utc=self.now)
        self.assertEqual(result["traffic_analytics"]["visitors"], 1)
        self.assertEqual(result["traffic_analytics"]["page_views"], 1)
        self.assertEqual(result["traffic_analytics"]["daily_trend"][0]["visitors"], 1)
        self.assertEqual(result["period"]["timezone"], "Asia/Shanghai")
        self.assertEqual(result["period"]["started_at"], "2026-10-08T16:00:00+00:00")

    def test_source_allowlist_and_unknown_history(self):
        base = {"event_key": "page_view", "page_key": "landing"}
        safe = sanitize_analytics_event(base | {"metadata": {"traffic_source": "douyin", "referrer": "https://private.invalid/", "email": "private@invalid.test"}})
        self.assertEqual(safe["metadata"], {"traffic_source": "douyin"})
        self.assertNotIn("traffic_source", sanitize_analytics_event(base | {"metadata": {"traffic_source": "private@invalid.test"}})["metadata"])
        self.event("page_view", "douyin", "2026-10-09T01:00:00+08:00", metadata=safe["metadata"])
        self.event("page_view", "legacy", "2026-10-09T01:00:00+08:00")
        self.event("page_view", "bad", "2026-10-09T01:00:00+08:00", metadata={"traffic_source": "private@invalid.test"})
        rows = self.repo.platform_operations_overview(period_days=1, now_utc=self.now)["traffic_analytics"]["source_breakdown"]
        self.assertEqual({row["source"]: row["page_views"] for row in rows}, {"douyin": 1, "unknown": 2})
        self.assertNotIn("private@", str(rows))

    def test_tasks_share_beijing_window_and_snapshot_end(self):
        merchant = self.repo.create_user_with_company(email="ops-alignment@jiejing-shop.cn", password="synthetic-only-password", company_name="Merchant fixture")
        ids = {"company_id": merchant["company"]["company_id"], "user_id": merchant["user"]["user_id"]}
        store = self.repo.create_store(**ids, payload={"platform": "ebay", "store_name": "Synthetic", "marketplace": "EBAY_US"})
        for timestamp in ("2026-10-08T15:59:59+00:00", "2026-10-08T17:00:00+00:00", "2026-10-09T01:15:00+08:00", "2026-10-08T18:00:00+00:00"):
            task = self.repo.create_task(**ids, store_id=store["store_id"], task_type="merchant_ceo_chat", title="Synthetic task", input_data={"test_fixture": True, "model_usage_required": True})
            with self.repo._connect() as conn:
                conn.execute("update tasks set created_at = ? where task_id = ?", (timestamp, task["task_id"]))
        with self.repo._connect() as conn:
            conn.execute("update schema_migrations set applied_at = ? where migration_id = ?", ("2026-10-09T00:30:00+08:00", "20260714_platform_operations_metering"))
        result = self.repo.platform_operations_overview(period_days=1, now_utc=self.now)
        self.assertEqual(sum(result["tasks"].values()), 2)
        self.assertEqual(result["unit_economics"]["current_unmetered_model_tasks"], 2)

    def test_identified_test_accounts_are_excluded_but_anonymous_visits_remain(self):
        account = self.repo.create_user_with_company(email="identified@jiejing-shop.cn", password="synthetic-only-password", company_name="Synthetic fixture")
        user_id = account["user"]["user_id"]
        with self.repo._connect() as conn:
            conn.execute("update users set account_classification = 'synthetic_test' where user_id = ?", (user_id,))
        self.event("page_view", "known-test", "2026-10-09T01:00:00+08:00", user_id=user_id, metadata={"traffic_source": "douyin"})
        self.event("page_view", "anonymous", "2026-10-09T01:00:00+08:00")
        traffic = self.repo.platform_operations_overview(period_days=1, now_utc=self.now)["traffic_analytics"]
        self.assertEqual(traffic["visitors"], 1)
        self.assertEqual(traffic["source_breakdown"][0]["source"], "unknown")


if __name__ == "__main__":
    unittest.main()
