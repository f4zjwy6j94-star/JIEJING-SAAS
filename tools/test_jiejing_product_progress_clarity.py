"""Display-only regressions: count fields, never weaken publication blockers."""
import unittest

from test_jiejing_listing_single_progress import FixtureRepository, build, fact_report, task


class ProductProgressClarityTest(unittest.TestCase):
    def snapshot(self, fields, extra):
        report = fact_report(unknown=fields)
        report["report"]["merchant_product_fact_packet"]["blocked_by"].extend(extra)
        result = build(FixtureRepository(tasks=[task()], reports=[report]))
        stage = next(row for row in result["stages"] if row["key"] == "facts")
        return result, stage

    def test_simulation_and_source_rules_are_not_two_more_missing_fields(self):
        fields = ["sku", "item_location", "image_urls", "image_rights_confirmed", "merchant_owned_product_confirmed"]
        result, stage = self.snapshot(fields, ["simulation_only_product_facts", "merchant_product_source_unconfirmed"])
        self.assertEqual(stage["detail"], "5 项待补")
        self.assertEqual(result["blocker"]["detail"], "还有 5 项商品资料待商家确认。")
        self.assertEqual(stage["status"], "blocked")

    def test_union_of_field_keys_keeps_extra_field_and_deduplicates(self):
        result, stage = self.snapshot(["sku", "sku"], ["merchant_product_fact_missing:sku", "merchant_product_fact_missing:material", "merchant_product_source_unconfirmed"])
        self.assertEqual(stage["detail"], "2 项待补")
        self.assertEqual(result["current_stage"], "facts")

    def test_simulation_with_complete_fields_stays_blocked_not_zero_missing(self):
        result, stage = self.snapshot([], ["simulation_only_product_facts"])
        self.assertEqual(stage["detail"], "仅供演练")
        self.assertEqual(stage["status"], "blocked")
        self.assertEqual(result["blocker"]["title"], "演练商品不能用于发布")

    def test_other_review_rule_with_complete_fields_stays_blocked(self):
        result, stage = self.snapshot([], ["listing_product_fact_sensitive_text"])
        self.assertEqual(stage["detail"], "资料待核对")
        self.assertEqual(stage["status"], "blocked")
        self.assertEqual(result["blocker"]["title"], "商品资料仍需核对")

    def test_complete_real_facts_are_unchanged(self):
        _, stage = self.snapshot([], [])
        self.assertEqual(stage["status"], "completed")
        self.assertEqual(stage["detail"], "商品事实已补齐")


if __name__ == "__main__":
    unittest.main()
