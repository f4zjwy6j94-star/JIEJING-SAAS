"""Semantic claim review uses the provider boundary and real report persistence."""
import copy
import json
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import test_jiejing_listing_buyer_copy_rewrite as rewrite_fixture
from tools.listing_claim_review_fixture import supported_review
from jiejing_saas.listing_draft_generation import ListingDraftGenerationError


class ReviewBoundary(rewrite_fixture.LocalModelBoundary):
    def __init__(self):
        super().__init__()
        self.review_transform = lambda result: result

    def generate_text(self, **kwargs):
        prompt = json.loads(kwargs["user_prompt"])
        if prompt.get("contract") != "listing_claim_review_v1":
            return super().generate_text(**kwargs)
        self.calls.append(kwargs)
        result = self.review_transform(supported_review(prompt))
        return {"text": json.dumps(result), "_usage": {"input_tokens": 80, "output_tokens": 50, "total_tokens": 130}}


class ListingClaimReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = rewrite_fixture.BuyerCopyRewriteTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = ReviewBoundary()
        self.fixture.model = self.model

    def generate(self):
        return self.fixture.generate(generation_mode="rewrite_buyer_copy")

    def test_semantic_rejection_of_unbacked_claim_preserves_prior_report_and_editor(self):
        self.model.output["selling_points"][0] = "Built for a lifetime of reliable use"
        def reject(result):
            result["reviews"][2].update(verdict="unsupported", evidence_keys=[])
            return result
        self.model.review_transform = reject
        before = self.fixture.repository.list_reports(company_id=self.fixture.company_id)
        with self.assertRaises(ListingDraftGenerationError) as error:
            self.generate()
        self.assertEqual("listing_final_copy_semantic_unsupported", error.exception.failure_code)
        self.assertEqual(2, error.exception.model_usage["request_count"])
        self.assertEqual(before, self.fixture.repository.list_reports(company_id=self.fixture.company_id))

    def test_supported_review_is_bound_to_final_copy_and_counts_provider_usage(self):
        result = self.generate()
        self.assertEqual("completed", result["status"])
        self.assertEqual(2, result["model_usage"]["request_count"])
        review = result["listing_handoff"]["claim_review"]
        self.assertEqual("listing_claim_review_v1", review["contract_version"])
        self.assertEqual("supported", review["status"])
        stored = next(row for row in self.fixture.repository.list_reports(company_id=self.fixture.company_id)
                      if row["report_id"] == result["report"]["report_id"])
        self.assertEqual(review, stored["report"]["listing_handoff"]["listing_fields"]["claim_review"])
        final = result["listing_handoff"]["buyer_copy_rewrite"]["fields"]
        for key in set(self.fixture.fields) - {"title", "description", "selling_points"}:
            self.assertEqual(self.fixture.fields[key], final[key])
        prompt = json.loads(self.model.calls[-1]["user_prompt"])
        self.assertEqual(final["title"], prompt["buyer_copy"]["title"])

    def test_review_timeout_preserves_old_copy_without_an_automatic_retry(self):
        def timeout(_value):
            raise TimeoutError("synthetic review timeout")
        self.model.review_transform = timeout
        before = self.fixture.repository.list_reports(company_id=self.fixture.company_id)
        with self.assertRaises(ListingDraftGenerationError) as error:
            self.generate()
        self.assertEqual("listing_model_timeout", error.exception.failure_code)
        self.assertEqual(2, len(self.model.calls))
        self.assertEqual(before, self.fixture.repository.list_reports(company_id=self.fixture.company_id))

    def test_incomplete_stale_unknown_or_malformed_review_cannot_save(self):
        def missing(value):
            value["reviews"].pop()
            return value
        def stale(value):
            value["reviews"][0]["text"] = "Different product"
            return value
        def invented(value):
            value["reviews"][0]["evidence_keys"] = ["not_a_fact"]
            return value
        for transform in (missing, stale, invented, lambda _: {"accepted": True}):
            with self.subTest(transform=transform.__name__):
                self.model.review_transform = transform
                before = len(self.model.calls)
                with self.assertRaises(ListingDraftGenerationError) as error:
                    self.generate()
                self.assertEqual("listing_final_copy_semantic_review_invalid", error.exception.failure_code)
                self.assertEqual(2, len(self.model.calls) - before)


if __name__ == "__main__":
    unittest.main()
