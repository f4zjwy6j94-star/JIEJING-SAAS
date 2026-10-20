#!/usr/bin/env python3
"""A zero-write evidence failure must safely restore a claimed publish."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import (  # noqa: E402
    EXTERNAL_EXECUTION_PROCESSING_STATUS,
    ConfirmationDecisionConflict,
    SaaSRepository,
)
from jiejing_saas.ebay_write_adapter import build_ebay_execution_plan


def main() -> int:
    output_dir = ROOT / "output" / "test-jiejing-publish-claim-prewrite-abort"
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "saas.sqlite"
    if db_path.exists():
        db_path.unlink()
    repository = SaaSRepository(db_path, database_engine="sqlite")
    account = repository.create_user_with_company(
        email="publish-prewrite-abort@example.test",
        password="Password123!",
        company_name="Publish prewrite abort",
    )
    user = account["user"]
    company_id = user["default_company_id"]
    user_id = user["user_id"]
    store = repository.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": "Prewrite abort", "marketplace": "EBAY_US"},
    )
    task = repository.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="merchant_listing_publish_intake",
        title="Prewrite abort",
        input_data={"secret_exposed": False},
    )
    confirmation = repository.create_confirmation(
        company_id=company_id,
        store_id=store["store_id"],
        task_id=task["task_id"],
        runtime_run_id="merchant_listing_publish_intake",
        action_type="publish_listing",
        title="Prewrite abort",
        item={"publish_payload": {"listing":{"sku":"ABORT-EXACT"},"secret_exposed": False}, "secret_exposed": False},
        created_by=user_id,
    )
    repository.decide_confirmation(
        company_id=company_id,
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=user_id,
        note="Approve fixture before final evidence check.",
        expected_access_epochs=repository.access_session_epochs(user_id=user_id,company_id=company_id),
    )
    connection=repository.create_platform_connection(company_id=company_id,store_id=store['store_id'],user_id=user_id,
        payload={'platform':'ebay','connection_type':'oauth','status':'publish_authorized',
            'scopes':['https://api.ebay.com/oauth/api_scope/sell.inventory'],'create_secret_ref':True})
    with repository._connect() as conn:
        conn.execute("update secret_refs set status='stored' where secret_ref=?",(connection['secret_ref'],))
    request=SimpleNamespace(company_id=company_id,store_id=store['store_id'],task_id=task['task_id'],
        confirmation_id=confirmation['confirmation_id'],action_type='publish_listing',payload=confirmation['item']['publish_payload'])
    claimed = repository.claim_external_execution(
        company_id=company_id,
        confirmation_id=confirmation["confirmation_id"],
        user_id=user_id,
        expected_access_epochs=repository.access_session_epochs(user_id=user_id,company_id=company_id),
        operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',
            connections=repository.ebay_execution_connections(company_id=company_id,store_id=store['store_id'])),
    )
    assert claimed["status"] == EXTERNAL_EXECUTION_PROCESSING_STATUS
    restored = repository.abort_publish_execution_claim_before_write(
        company_id=company_id,
        confirmation_id=confirmation["confirmation_id"],
        user_id=user_id,
        reason_code="publish_evidence_changed",
    )
    assert restored["status"] == "needs_revision"
    assert restored["real_platform_write_attempted"] is False
    current = repository.get_confirmation(
        company_id=company_id,
        confirmation_id=confirmation["confirmation_id"],
    )
    assert current and current["status"] == "needs_revision"
    try:
        repository.abort_publish_execution_claim_before_write(
            company_id=company_id,
            confirmation_id=confirmation["confirmation_id"],
            user_id=user_id,
        )
    except ConfirmationDecisionConflict:
        pass
    else:
        raise AssertionError("a restored claim must not be abortable twice")

    print("PASS jiejing_publish_claim_prewrite_abort")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
