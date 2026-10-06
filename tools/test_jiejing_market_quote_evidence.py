#!/usr/bin/env python3
"""Contracts for source-grounded market quote answers."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.market_quote_evidence import (  # noqa: E402
    market_quote_answer_quality,
    new_york_market_time,
)


NOW = "2026-09-29T02:20:00+00:00"
MESSAGE = "今天纳斯达克指数收盘多少点？"


class MarketQuoteAnswerQualityTest(unittest.TestCase):
    def test_accepts_same_source_instrument_session_and_numbers(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertTrue(quality["accepted"], quality)
        self.assertEqual(quality["reasons"], [])

    def test_rejects_exact_numbers_when_source_has_no_trading_date(self) -> None:
        quality = market_quote_answer_quality(
            "今天纳斯达克综合指数收于26,939.37点，上涨3.34点（0.01%）[S3]。",
            [
                {
                    "citation_id": "S3",
                    "title": "NASDAQ Composite (^IXIC) quote",
                    "snippet": "Nasdaq Composite 26,939.37, +3.34 (+0.01%).",
                    "published_at": "2026-09-29T01:55:00Z",
                    "captured_at": "2026-09-29T02:18:00Z",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("cited_source_trading_date_required", quality["reasons"])

    def test_rejects_unknown_citation_id(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,820.38点[ S9 ]。".replace("[ S9 ]", "[S9]"),
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38.",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_numeric_claim_valid_citation_required", quality["reasons"])

    def test_rejects_numbers_not_present_in_the_cited_source(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,939.37点，上涨3.34点（0.01%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_numeric_claim_not_supported_by_citation", quality["reasons"])

    def test_rejects_nasdaq_100_as_evidence_for_nasdaq_composite(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S4]。",
            [
                {
                    "citation_id": "S4",
                    "title": "Nasdaq-100 Index NDX",
                    "snippet": "2026-09-28 Nasdaq-100 closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("cited_source_instrument_mismatch", quality["reasons"])

    def test_rejects_old_session_presented_as_today_close(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-25交易日，纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-25 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("cited_source_not_requested_session", quality["reasons"])

    def test_rejects_direction_opposite_to_cited_source(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,820.38点，上涨248.34点（0.92%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_direction_not_supported_by_citation", quality["reasons"])

    def test_accepts_short_honest_insufficient_evidence_answer_without_numbers(self) -> None:
        quality = market_quote_answer_quality(
            "当前来源没有可核验的交易日期，无法确认今天的收盘点位。",
            [],
            message=MESSAGE,
            now=NOW,
        )

        self.assertTrue(quality["accepted"], quality)
        self.assertEqual(quality["reasons"], [])

    def test_unitless_close_value_still_requires_numeric_support(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，NASDAQ Composite closed at 26939.37 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38.",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_numeric_claim_not_supported_by_citation", quality["reasons"])

    def test_numeric_close_answer_must_name_absolute_trading_date(self) -> None:
        quality = market_quote_answer_quality(
            "今天纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_answer_trading_date_required", quality["reasons"])

    def test_accepts_dated_timestamped_intraday_ticker_quote(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-29 10:31 ET，NVDA现价为$187.25 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NVDA stock quote",
                    "snippet": "2026-09-29 10:31 ET NVDA trading at $187.25.",
                }
            ],
            message="What is NVDA stock price now?",
            now="2026-09-29T14:35:00+00:00",
        )

        self.assertTrue(quality["accepted"], quality)
        self.assertEqual(quality["reasons"], [])

    def test_accepts_complete_chinese_trading_date_in_source_content(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026年9月28日交易日，纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026年9月28日 Nasdaq Composite收于26,820.38，下跌248.34（0.92%）。",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertTrue(quality["accepted"], quality)

    def test_rejects_unsupported_unitless_table_value(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数：26,939.37 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite: 26,820.38.",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_numeric_claim_not_supported_by_citation", quality["reasons"])

    def test_rejects_value_mixed_across_two_sessions_in_one_source(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,939.37点 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": (
                        "2026-09-25 Nasdaq Composite closed at 26,939.37. "
                        "2026-09-28 Nasdaq Composite closed at 26,820.38."
                    ),
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("cited_source_not_requested_session", quality["reasons"])

    def test_rejects_other_ticker_as_evidence_for_chinese_company_name(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-29 10:31 ET，英伟达现价为$187.25 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "AAPL stock quote",
                    "snippet": "2026-09-29 10:31 ET AAPL trading at $187.25.",
                }
            ],
            message="英伟达现在股价多少？",
            now="2026-09-29T14:35:00+00:00",
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("cited_source_instrument_mismatch", quality["reasons"])

    def test_rejects_answer_that_switches_requested_index(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克100指数收于26,820.38点 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26,820.38.",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_answer_instrument_mismatch", quality["reasons"])

    def test_accepts_english_complete_date_and_sanitized_decimal_spacing(self) -> None:
        quality = market_quote_answer_quality(
            "As of September 28, 2026, the Nasdaq Composite closed at 26820.38, down 248.34 (0.92%) [S1].",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": (
                        "September 28, 2026 Nasdaq Composite closed at 26,820. 38, "
                        "down 248. 34 (0. 92%)."
                    ),
                }
            ],
            message="What was the Nasdaq Composite close on September 28, 2026?",
            now=NOW,
        )

        self.assertTrue(quality["accepted"], quality)

    def test_public_new_york_clock_handles_day_boundary(self) -> None:
        market_time = new_york_market_time(
            datetime(2026, 9, 29, 2, 20, tzinfo=timezone.utc)
        )

        self.assertEqual(market_time.date().isoformat(), "2026-09-28")
        self.assertEqual((market_time.hour, market_time.minute), (22, 20))

    def test_english_and_traditional_close_questions_use_completed_session(self) -> None:
        record = {'citation_id': 'S1', 'title': 'NASDAQ Composite ^IXIC',
                  'snippet': '2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).'}
        for message in ('NASDAQ Composite close today?', '今天納斯達克指數收盤多少點？'):
            with self.subTest(message=message):
                quality = market_quote_answer_quality(
                    '美國2026-09-28交易日，納斯達克綜合指數收盤26,820.38點，下跌248.34點（0.92%）[S1]。',
                    [record], message=message, now=NOW)
                self.assertTrue(quality['accepted'], quality)

    def test_rejects_unsupported_bare_integer_table_value(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数：26939 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": "2026-09-28 Nasdaq Composite closed at 26820.",
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_numeric_claim_not_supported_by_citation", quality["reasons"])

    def test_rejects_previous_close_value_as_current_session_close(self) -> None:
        quality = market_quote_answer_quality(
            "截至美国2026-09-28交易日，纳斯达克综合指数收于26,939.37点 [S1]。",
            [
                {
                    "citation_id": "S1",
                    "title": "NASDAQ Composite ^IXIC",
                    "snippet": (
                        "2026-09-28 Nasdaq Composite Current/Close 26,820.38; "
                        "Previous Close 26,939.37."
                    ),
                }
            ],
            message=MESSAGE,
            now=NOW,
        )

        self.assertFalse(quality["accepted"], quality)
        self.assertIn("market_close_claim_not_supported_by_close_field", quality["reasons"])


if __name__ == "__main__":
    unittest.main()
