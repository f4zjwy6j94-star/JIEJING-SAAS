#!/usr/bin/env python3
"""Offline regression for distinct search publication and retrieval timestamps."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.public_search import PublicSearchProbeAdapter, PublicSearchProbeConfig
from jiejing_saas.ai_ceo_chat import _source_records_from_search_snapshot
from jiejing_saas.repository import _normalize_ai_ceo_chat_history_turn


class PublicSearchTemporalMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        for target in (
            patch.object(
                PublicSearchProbeAdapter,
                "_resolve_connection",
                side_effect=AssertionError("snapshot regression must not resolve credentials"),
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("snapshot regression must not access the network"),
            ),
        ):
            target.start()
            self.addCleanup(target.stop)

    def snapshot(self, **timestamps: str) -> dict:
        return PublicSearchProbeAdapter().probe(
            PublicSearchProbeConfig(
                query="latest Nasdaq Composite close",
                provider="tavily",
                results=[
                    {
                        "title": "Nasdaq Composite close report",
                        "url": "https://example.com/market-close",
                        "content": "A public report whose publication date must remain explicit.",
                        **timestamps,
                    }
                ],
            )
        )

    def test_explicit_publication_and_capture_remain_distinct(self) -> None:
        result = self.snapshot(
            published_at=" 2026-09-28T20:10:00Z ",
            published_date="2026-09-27",
            captured_at=" 2026-09-29T02:00:00Z ",
            date="2026-09-26",
        )["results"][0]

        self.assertEqual(result.get("published_at"), "2026-09-28T20:10:00Z")
        self.assertEqual(result.get("captured_at"), "2026-09-29T02:00:00Z")
        self.assertEqual(result.get("date"), "2026-09-26")

    def test_provider_publication_date_alias_is_preserved(self) -> None:
        result = self.snapshot(published_date=" 2026-09-28 ")["results"][0]

        self.assertEqual(result.get("published_at"), "2026-09-28")
        self.assertEqual(result.get("captured_at"), "")

    def test_capture_does_not_prove_publication(self) -> None:
        result = self.snapshot(captured_at="2026-09-29T02:00:00Z")["results"][0]

        self.assertEqual(result.get("captured_at"), "2026-09-29T02:00:00Z")
        self.assertEqual(result.get("published_at"), "")

    def test_ambiguous_date_stays_unqualified(self) -> None:
        result = self.snapshot(date=" 2026-09-28 ")["results"][0]

        self.assertEqual(result.get("date"), "2026-09-28")
        self.assertEqual(result.get("captured_at"), "")
        self.assertEqual(result.get("published_at"), "")

    def test_missing_dates_remain_unknown(self) -> None:
        result = self.snapshot()["results"][0]

        self.assertEqual(result.get("captured_at"), "")
        self.assertEqual(result.get("published_at"), "")

    def test_snapshot_to_chat_preserves_explicit_publication_fields(self) -> None:
        for field in ("published_at", "published_date"):
            with self.subTest(field=field):
                snapshot = self.snapshot(
                    **{field: "2026-09-28T20:10:00Z"},
                    captured_at="2026-09-29T02:00:00Z",
                )
                records = _source_records_from_search_snapshot(snapshot)

                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["published_at"], "2026-09-28T20:10:00Z")
                self.assertEqual(records[0]["captured_at"], "2026-09-29T02:00:00Z")

    def test_snapshot_to_chat_does_not_upgrade_ambiguous_date(self) -> None:
        records = _source_records_from_search_snapshot(self.snapshot(date="2026-09-28"))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["published_at"], "")
        self.assertEqual(records[0]["captured_at"], "")

    def test_history_preserves_publication_update_and_retrieval_separately(self) -> None:
        row = _normalize_ai_ceo_chat_history_turn({
            "user_text": "请核对当前信息", "assistant_text": "已核对来源[S1]。",
            "source_records": [{"citation_id": "S1", "published_at": "2026-09-20",
                                "updated_at": "2026-09-28", "captured_at": "2026-09-29T02:00:00Z",
                                "title": "Official information", "url": "https://example.com/current"}],
        }, company_id="fixture-company", user_id="fixture-user")
        source = row["source_records"][0]
        self.assertEqual(source["published_at"], "2026-09-20")
        self.assertEqual(source["updated_at"], "2026-09-28")
        self.assertEqual(source["captured_at"], "2026-09-29T02:00:00Z")


if __name__ == "__main__":
    unittest.main(verbosity=2)
