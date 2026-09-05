#!/usr/bin/env python3
"""Unit contract for the seven-day platform-funded AI trial window."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.repository import SaaSRepository


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    old_limit = os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT")
    old_days = os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS")
    os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = "1"
    os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS"] = "7"
    try:
        with tempfile.TemporaryDirectory(prefix="jiejing-trial-window-", ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "trial.sqlite"
            repository = SaaSRepository(db_path)
            repository.initialize()
            repository.upsert_platform_trial_activation(
                company_id="company-trial-window",
                user_id="user-trial-window",
                status="active",
                platform_trial_allowed=True,
                welcome_media_points_granted=0,
                requires_challenge=True,
                challenge_attested=True,
                decision_reason="unit_test",
            )

            handler = object.__new__(SaaSBackendHandler)
            handler.repository = repository
            active = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if active.get("allowed") is not True or active.get("trial_limit") != 1:
                return fail(f"fresh seven-day trial should be active with one request: {active}")
            if active.get("trial_duration_days") != 7 or active.get("trial_expired") is not False:
                return fail(f"fresh trial should expose the seven-day window: {active}")

            first_started_at = active.get("trial_started_at")
            reservation = handler._reserve_platform_model_trial(
                identity={"company_id": "company-trial-window"},
                route_scope="listing_draft_generation",
            )
            if reservation.get("allowed") is not True:
                return fail(f"fresh trial should reserve its only request: {reservation}")

            repository.upsert_platform_trial_activation(
                company_id="company-trial-window",
                user_id="user-trial-window",
                status="active",
                platform_trial_allowed=True,
                welcome_media_points_granted=0,
                requires_challenge=True,
                challenge_attested=True,
                decision_reason="unit_test_repeated_active_decision",
            )
            repeated = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if repeated.get("trial_started_at") != first_started_at:
                return fail(f"repeated active decision must preserve the first trial start: {repeated}")
            if repeated.get("used") != 1 or repeated.get("remaining") != 0 or repeated.get("allowed") is not False:
                return fail(f"repeated active decision must not refill an exhausted trial: {repeated}")

            activation = repository.get_platform_trial_activation(company_id="company-trial-window") or {}
            expired_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            activation["activated_at"] = expired_at
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "update platform_trial_activations set activated_at = ?, activation_json = ? where company_id = ?",
                    (expired_at, json.dumps(activation, ensure_ascii=False), "company-trial-window"),
                )

            expired = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if expired.get("allowed") is not False or expired.get("trial_expired") is not True:
                return fail(f"trial older than seven days must be blocked: {expired}")
            if expired.get("blocked_by") != "platform_default_model_trial_expired":
                return fail(f"expired trial should expose the value-free expiry reason: {expired}")
            if expired.get("merchant_byok_unaffected") is not True:
                return fail(f"trial expiry must not block merchant BYOK: {expired}")
    finally:
        if old_limit is None:
            os.environ.pop("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT", None)
        else:
            os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = old_limit
        if old_days is None:
            os.environ.pop("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS", None)
        else:
            os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS"] = old_days

    print("PASS jiejing_platform_trial_window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
