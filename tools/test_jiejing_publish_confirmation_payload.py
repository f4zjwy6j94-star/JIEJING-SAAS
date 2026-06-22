#!/usr/bin/env python3
"""Regression for publish payload stored inside SaaS confirmation items."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import _execution_payload_from_context  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "test-jiejing-publish-confirmation-payload"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "saas.sqlite"
    if db_path.exists():
        db_path.unlink()
    repo = SaaSRepository(db_path, database_engine="sqlite")
    account = repo.create_user_with_company(
        email="publish-payload@example.test",
        password="Password123!",
        company_name="Publish Payload Test",
    )
    user = account["user"]
    store = repo.create_store(
        company_id=user["default_company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "payload-store", "marketplace": "EBAY_US"},
    )
    task = repo.create_task(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="product_workflow",
        title="Publish payload context",
        input_data={"product": "Sunglasses"},
    )
    confirmation_payload = {
        "listing": {"sku": "JJ-SUNGLASSES-UNIT", "title": "Unit Sunglasses"},
        "asset_manifest": {"assets": [{"asset_type": "image", "url": "https://example.test/image.jpg"}]},
        "finance_review": {"net_profit_money": {"value": "2.10", "currency": "USD"}},
    }
    confirmation = repo.create_confirmation(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        task_id=task["task_id"],
        runtime_run_id="run_publish_payload_unit",
        action_type="publish_listing",
        title="Confirm publish payload",
        item={"publish_payload": confirmation_payload},
        created_by=user["user_id"],
    )
    latest_marker = repo.create_confirmation(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        task_id=task["task_id"],
        runtime_run_id="run_publish_payload_unit",
        action_type="publish_listing",
        title="Newest confirmation should be returned by limited list",
        item={"publish_payload": confirmation_payload, "marker": "newest"},
        created_by=user["user_id"],
        confirmation_id="confirm_newest_publish_payload",
    )
    limited = repo.list_confirmations(company_id=user["default_company_id"], status="pending", limit=1)
    if not limited or limited[0]["confirmation_id"] != latest_marker["confirmation_id"]:
        return fail(f"limited confirmation list should return newest records first: {limited}")
    merged = _execution_payload_from_context(
        repository=repo,
        company_id=user["default_company_id"],
        confirmation=confirmation,
        body_payload={"listing": {"quantity": 3}, "source": "unit"},
    )
    if merged.get("listing", {}).get("sku") != "JJ-SUNGLASSES-UNIT":
        return fail(f"confirmation publish payload was not merged: {merged}")
    if merged.get("listing", {}).get("quantity") != 3:
        return fail("body payload should still override/extend confirmation payload")
    if len(merged.get("asset_manifest", {}).get("assets", [])) != 1:
        return fail("asset manifest from confirmation item should be preserved")
    if not merged.get("finance_review", {}).get("net_profit_money"):
        return fail("finance review from confirmation item should be preserved")
    print("PASS publish_confirmation_payload_context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
