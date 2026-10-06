#!/usr/bin/env python3
"""Platform-funded model reservations release only zero-request attempts."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import (  # noqa: E402
    PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV,
    SaaSBackendHandler,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="jiejing-platform-trial-old-schema-", ignore_cleanup_errors=True) as temp:
        legacy_path = Path(temp) / "legacy.sqlite"
        period_key = "a" * 64
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                create table platform_model_trial_reservations (
                  reservation_id text primary key,
                  company_id text not null,
                  period_key text not null,
                  slot_number integer not null,
                  route_scope text not null,
                  created_at text not null,
                  unique (company_id, period_key, slot_number)
                )
                """
            )
            connection.execute(
                "insert into platform_model_trial_reservations values (?, ?, ?, ?, ?, ?)",
                ("trialres_legacy_slot", "company-legacy", period_key, 3, "merchant_ceo_chat", "2026-09-01T00:00:00+00:00"),
            )
        legacy_repository = SaaSRepository(legacy_path)
        legacy_repository.initialize()
        legacy_usage = legacy_repository.platform_model_trial_reservation_usage(
            company_id="company-legacy",
            period_key=period_key,
        )
        if legacy_usage.get("baseline_used") != 2 or legacy_usage.get("reservation_used") != 3:
            raise AssertionError(f"legacy reservation rows must retain their task baseline and consumed slot: {legacy_usage}")

    with tempfile.TemporaryDirectory(prefix="jiejing-platform-trial-lifecycle-", ignore_cleanup_errors=True) as temp:
        repository = SaaSRepository(Path(temp) / "saas.sqlite")
        account = repository.create_user_with_company(
            email="platform-trial-lifecycle@local.invalid",
            password="platform-trial-lifecycle-password",
            company_name="Platform Trial Lifecycle",
        )
        company_id = account["company"]["company_id"]
        user_id = account["user"]["user_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user_id,
            payload={"platform": "ebay", "store_name": "Lifecycle Store", "marketplace": "EBAY_US"},
        )
        repository.upsert_platform_trial_activation(
            company_id=company_id,
            user_id=user_id,
            status="active",
            platform_trial_allowed=True,
            requires_challenge=True,
            challenge_attested=True,
            decision_reason="test_verified",
        )
        handler = object.__new__(SaaSBackendHandler)
        handler.repository = repository
        identity = {"company_id": company_id, "user_id": user_id}

        with patch.dict(os.environ, {PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV: "2"}, clear=False):
            zero_request_task = repository.create_task(
                company_id=company_id,
                store_id=store["store_id"],
                user_id=user_id,
                task_type="merchant_ceo_chat",
                title="zero-request platform attempt",
                task_id="task_zero_request_platform_fixture",
                input_data={
                    "model_resolution_mode": "platform_managed_default",
                    "model_usage_owner": "jiejing_platform_trial",
                },
            )
            repository.update_task_status(
                task_id=zero_request_task["task_id"],
                company_id=company_id,
                status="failed",
                output={
                    "usage_consumed": False,
                    "model_request_count": 0,
                    "ai_ceo_chat": {"status": "internal_dependency_failed"},
                },
                audit_summary="zero provider request regression fixture",
            )
            before_reservation = handler._platform_model_trial_quota(identity=identity)
            if before_reservation.get("used") != 0 or before_reservation.get("allowed") is not True:
                raise AssertionError(
                    "an AI CEO task that made zero provider requests must not consume trial quota: "
                    f"{before_reservation}"
                )

            first = handler._reserve_platform_model_trial(
                identity=identity,
                route_scope="listing_draft_generation",
            )
            first_id = str(first.get("reservation_id") or "")
            if first.get("allowed") is not True or not first_id:
                raise AssertionError(f"first request must obtain an addressable reservation: {first}")

            released = repository.settle_platform_model_trial_reservation(
                company_id=company_id,
                reservation_id=first_id,
                request_count=0,
            )
            after_release = handler._platform_model_trial_quota(identity=identity)
            if released.get("status") != "released":
                raise AssertionError(f"zero-request settlement must release its reservation: {released}")
            if after_release.get("used") != 0 or after_release.get("remaining") != 2 or after_release.get("allowed") is not True:
                raise AssertionError(f"zero-request settlement must restore the trial unit: {after_release}")

            historical_task = repository.create_task(
                company_id=company_id,
                store_id=store["store_id"],
                user_id=user_id,
                task_type="listing_draft_generation",
                title="historical platform request",
                task_id="task_historical_platform_fixture",
                input_data={"model_usage_owner": "jiejing_platform_trial"},
            )
            repository.update_task_status(
                task_id=historical_task["task_id"],
                company_id=company_id,
                status="completed",
                output={"usage_consumed": True, "model_request_count": 1},
                audit_summary="historical platform request fixture",
            )

            second = handler._reserve_platform_model_trial(
                identity=identity,
                route_scope="merchant_ceo_chat",
            )
            second_id = str(second.get("reservation_id") or "")
            if second.get("allowed") is not True or not second_id or second_id == first_id:
                raise AssertionError(f"released slot must be safely reusable with a fresh token: {second}")

            stale_release = repository.settle_platform_model_trial_reservation(
                company_id=company_id,
                reservation_id=first_id,
                request_count=0,
            )
            after_stale_release = handler._platform_model_trial_quota(identity=identity)
            if stale_release.get("settled") is not False or after_stale_release.get("used") != 2:
                raise AssertionError(
                    "a stale release token must not release a later request that reused the slot: "
                    f"{stale_release} {after_stale_release}"
                )

            consumed = repository.settle_platform_model_trial_reservation(
                company_id=company_id,
                reservation_id=second_id,
                request_count=1,
            )
            exhausted = handler._platform_model_trial_quota(identity=identity)
            if consumed.get("status") != "consumed":
                raise AssertionError(f"provider entry must consume the reservation: {consumed}")
            if exhausted.get("used") != 2 or exhausted.get("remaining") != 0 or exhausted.get("allowed") is not False:
                raise AssertionError(f"a consumed request must keep the trial exhausted: {exhausted}")

        # Two released rows can outnumber current remaining quota after a
        # historical usage backfill. Concurrent reuse must serialize the quota
        # calculation, not merely make each individual row claim atomic.
        race_period = "b" * 64
        released_ids = []
        for _ in range(2):
            reservation = repository.reserve_platform_model_trial_slot(
                company_id=company_id, period_key=race_period, historical_used=0,
                limit=2, route_scope="listing_draft_generation",
            )
            released_ids.append(reservation["reservation_id"])
        for reservation_id in released_ids:
            repository.settle_platform_model_trial_reservation(
                company_id=company_id, reservation_id=reservation_id, request_count=0,
            )
        claim_barrier = threading.Barrier(2)
        original_connect = repository._connect

        def race_connection():
            connection = original_connect()

            def hold_before_claim(sql):
                if "set reservation_id =" in sql.lower():
                    try:
                        claim_barrier.wait(timeout=0.5)
                    except threading.BrokenBarrierError:
                        pass  # A database lock correctly serialized the peer.

            connection.set_trace_callback(hold_before_claim)
            return connection

        def claim_released_slot(_):
            return repository.reserve_platform_model_trial_slot(
                company_id=company_id, period_key=race_period, historical_used=1,
                limit=2, route_scope="listing_draft_generation",
            )

        with patch.object(repository, "initialize", return_value=None), patch.object(repository, "_connect", race_connection):
            with ThreadPoolExecutor(max_workers=2) as executor:
                race_results = list(executor.map(claim_released_slot, range(2)))
        if sum(result.get("allowed") is True for result in race_results) != 1:
            raise AssertionError(f"concurrent released-slot reuse exceeded the remaining trial quota: {race_results}")
        race_usage = repository.platform_model_trial_reservation_usage(company_id=company_id, period_key=race_period)
        if race_usage.get("reservation_used") != 2:
            raise AssertionError(f"concurrent released-slot reuse corrupted durable usage: {race_usage}")

    print("PASS jiejing_platform_trial_reservation_lifecycle")


if __name__ == "__main__":
    main()
