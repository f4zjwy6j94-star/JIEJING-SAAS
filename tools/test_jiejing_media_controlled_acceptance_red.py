#!/usr/bin/env python3
"""RED contracts for media settlement and ops-only controlled acceptance points.

All repositories in this module are temporary SQLite repositories. The CLI
subprocess receives a non-live environment and the HTTP check binds only to
localhost; these contracts cannot call a provider or production.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import textwrap
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.media_asset_pipeline import build_media_asset_generation_packet  # noqa: E402
from jiejing_saas.provider_job_runner import ProviderJobRunner  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402
from jiejing_saas.worker import LocalQueueWorker  # noqa: E402
CONTROLLED_POINTS = 320
CONTROLLED_TTL_HOURS = 24
CONTROLLED_APPROVAL = "I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS"
CONTROLLED_SOURCE = "controlled_acceptance"
CLI_PATH = ROOT / "tools" / "jiejing_media_controlled_acceptance.py"

_LIVE_ENV_EXACT = {
    "DATABASE_URL",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_URL",
    "JIEJING_REDIS_URL",
    "REDIS_URL",
}
_LIVE_ENV_PREFIXES = (
    "PG",
    "JIEJING_POSTGRES",
    "JIEJING_DATABASE_POOL",
    "JIEJING_QUEUE_",
    "JIEJING_VAULT_",
    "JIEJING_EBAY_",
    "EBAY_",
    "JIEJING_WECHAT_",
    "WECHAT_",
    "JIEJING_STRIPE_",
    "STRIPE_",
    "JIEJING_ALIPAY_",
    "ALIPAY_",
    "JIEJING_MEDIA_",
    "FAL_",
    "OPENAI_",
    "DEEPSEEK_",
    "JIEJING_MODEL_",
    "JIEJING_WEB_SEARCH_",
    "TAVILY_",
    "SERPER_",
)

_SAFE_OS_ENV_KEYS = (
    "COMSPEC",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)


def _isolated_cli_env(
    *,
    db_path: Path,
    runtime_db_path: Path,
    output_root: Path,
    enabled: bool | None,
    company_allowlist: tuple[str, ...],
) -> dict[str, str]:
    """Return an environment that cannot inherit a live DB or provider key."""

    env = {key: os.environ[key] for key in _SAFE_OS_ENV_KEYS if os.environ.get(key)}
    env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_DATABASE_ENGINE": "sqlite",
            "JIEJING_DATABASE_ADAPTER": "sqlite-local",
            "JIEJING_SAAS_DB_PATH": str(db_path),
            "JIEJING_RUNTIME_DB_PATH": str(runtime_db_path),
            "JIEJING_OUTPUT_ROOT": str(output_root),
            "JIEJING_QUEUE_PROVIDER": "local_worker",
            "JIEJING_EXECUTION_ADAPTER": "demo_no_platform_write",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_EBAY_DRAFT_SAVE_LIVE": "false",
            "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "false",
            "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "false",
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false",
            "JIEJING_NETWORK_DISABLED": "true",
            "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_COMPANY_ALLOWLIST": ",".join(company_allowlist),
        }
    )
    if enabled is not None:
        env["JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_ENABLED"] = "true" if enabled else "false"
    return env


@contextmanager
def _temporary_safe_process_env(*, db_path: Path, runtime_db_path: Path, output_root: Path) -> Iterator[None]:
    """Isolate settings construction without leaking mutations to later tests."""

    safe = _isolated_cli_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=output_root,
        enabled=False,
        company_allowlist=(),
    )
    affected = {
        key
        for key in os.environ
        if key in _LIVE_ENV_EXACT or key.upper().startswith(_LIVE_ENV_PREFIXES) or key.startswith("JIEJING_")
    }
    affected.update(key for key in safe if key.startswith("JIEJING_") or key in _LIVE_ENV_EXACT)
    before = {key: os.environ.get(key) for key in affected}
    try:
        for key in affected:
            os.environ.pop(key, None)
        os.environ.update({key: value for key, value in safe.items() if key in affected})
        yield
    finally:
        for key in affected:
            os.environ.pop(key, None)
        for key, value in before.items():
            if value is not None:
                os.environ[key] = value


def _post_local(base_url: str, path: str, payload: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


class MediaSettlementContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-media-settlement-red-", ignore_cleanup_errors=True)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        fixture = self.repository.create_user_with_company(
            email=f"settlement-{id(self)}@example.test",
            password="local-test-password",
            company_name="Media settlement RED contract",
        )
        self.company_id = fixture["company"]["company_id"]
        self.user_id = fixture["user"]["user_id"]
        self.email = fixture["user"]["email"]
        self.worker = LocalQueueWorker(repository=self.repository, runtime_bridge=object())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _reservation(
        self,
        *,
        points: int = CONTROLLED_POINTS,
        inputs: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        nonce = len(self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100))
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=points,
            idempotency_key=f"settlement-red-grant-{nonce}-v1",
            reference_type="test_fixture",
            reference_id=f"settlement-red-{nonce}",
            details={"credit_source": "purchased", "source_reference_id": f"settlement-red-{nonce}"},
        )
        reserved = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=points,
            idempotency_key=f"settlement-red-reserve-{nonce}-v1",
            reference_type="media_job",
            reference_id=f"settlement-red-job-{nonce}",
        )
        quote = {
            "estimated_points": points,
            "points_per_image": 80,
            "image_count": 4,
            "generation_tier": "standard",
            "video_requested": False,
        }
        job_body = {
            "idempotency_key": f"settlement-red-job-{nonce}",
            "provider_job_key": "media.asset_generation",
            "inputs": inputs or self._canonical_inputs(),
            "media_credits": {"quote": quote, "reservation": reserved},
        }
        task = {"company_id": self.company_id, "user_id": self.user_id}
        return task, job_body

    @staticmethod
    def _canonical_inputs(
        *,
        missing_product_fact: bool = False,
        missing_source_fact: bool = False,
        commercial_rights_confirmed: bool = True,
    ) -> dict[str, Any]:
        return {
            "creative_job_spec": {
                "job_type": "eBay_listing_asset_package",
                "product_facts_required": [
                    "product_identity",
                    "confirmed_material_or_pending_label",
                    "reference_images_or_source_notes",
                ],
                "review_gates": [
                    "fact_consistency_review",
                    "commercial_use_rights_review",
                    "platform_image_video_policy_review",
                    "listing_use_approval",
                ],
                "blocked_claims": ["unverified_certification"],
            },
            "product_facts": {
                "product": "Unbranded stainless steel tumbler",
                "supplier_facts": {"material": "" if missing_product_fact else "stainless steel"},
                "allowed_claims": ["merchant-confirmed reusable tumbler"],
                "forbidden_claims": ["medical"],
                "reference_images": (
                    [] if missing_source_fact else ["https://merchant-source.example.test/tumbler-source.png"]
                ),
                "target_marketplace_rules": {"platform": "ebay", "marketplace": "EBAY_US"},
            },
            "commercial_rights_confirmed": commercial_rights_confirmed,
            "image_count": 4,
            "image_sizes": ["1600x1600"],
            "scene_types": ["white_background", "detail_page", "lifestyle_scene", "dimension_image"],
            "generation_tier": "standard",
            "live_provider_requested": True,
        }

    @staticmethod
    def _canonical_provider_output(
        *,
        inputs: dict[str, Any],
        returned_images: int = 2,
        live_provider_called: bool = True,
        provider_status: str | None = None,
    ) -> dict[str, Any]:
        base = {
            "packet_type": "asset_manifest",
            "provider_family": "media",
            "source_record_type": "media_provider",
            "status": "dry_run_ready",
            "missing_inputs": [],
            "live_provider_called": False,
            "secret_exposed": False,
        }
        live_snapshot = None
        if live_provider_called:
            live_snapshot = {
                "provider": "fixture_media_provider",
                "status": "returned",
                "assets": [
                    {
                        "asset_id": f"canonical-live-asset-{index}",
                        "asset_type": "product_image",
                        "url": f"https://cdn.example.test/canonical-asset-{index}.png",
                        "dimensions": "1600x1600",
                    }
                    for index in range(returned_images)
                ],
            }
        packet = build_media_asset_generation_packet(
            base=base,
            contract_key="media.asset_generation",
            inputs=inputs,
            captured_at="2026-08-23T00:00:00+00:00",
            live_media_snapshot=live_snapshot,
        )
        safety = packet.get("safety") if isinstance(packet.get("safety"), dict) else {}
        return {
            "status": provider_status or (
                "completed_live_media_provider" if live_provider_called else "blocked_before_live_media_provider"
            ),
            "provider_job_key": "media.asset_generation",
            "missing_inputs": [],
            "output_packet": packet,
            "safety": safety,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    @classmethod
    def _manifest_blocked_output(cls, *, inputs: dict[str, Any]) -> dict[str, Any]:
        base = {
            "packet_type": "asset_manifest",
            "provider_family": "media",
            "source_record_type": "media_provider",
            "status": "dry_run_ready",
            "missing_inputs": [],
            "live_provider_called": False,
            "secret_exposed": False,
        }
        packet = build_media_asset_generation_packet(
            base=base,
            contract_key="media.asset_generation",
            inputs=inputs,
            captured_at="2026-08-23T00:00:00+00:00",
            live_media_snapshot={
                "provider": "fixture_media_provider",
                "status": "returned",
                "assets": [
                    {
                        "asset_id": "malformed-live-asset",
                        "asset_type": "product_image",
                        "url": "ftp://unsupported.example.test/malformed.png",
                        "dimensions": "1600x1600",
                    }
                ],
            },
        )
        safety = packet.get("safety") if isinstance(packet.get("safety"), dict) else {}
        return {
            "status": "completed_live_media_provider",
            "provider_job_key": "media.asset_generation",
            "missing_inputs": [],
            "output_packet": packet,
            "safety": safety,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    @staticmethod
    def _reservation_id(job_body: dict[str, Any]) -> str:
        return str(job_body["media_credits"]["reservation"]["ledger_entry"]["ledger_id"])

    def _terminal_entries(self, reservation_id: str) -> list[dict[str, Any]]:
        return [
            item
            for item in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if item.get("reservation_id") == reservation_id and item.get("operation_type") in {"settle", "release"}
        ]

    def _assert_full_release(
        self,
        provider_output: dict[str, Any],
        *,
        inputs: dict[str, Any] | None = None,
        live_provider_called: bool | None = None,
    ) -> None:
        task, job_body = self._reservation(inputs=inputs)
        safety = provider_output.get("safety") if isinstance(provider_output.get("safety"), dict) else {}
        called = bool(safety.get("live_provider_called")) if live_provider_called is None else live_provider_called
        try:
            result = self.worker._settle_media_credit_reservation(
                task=task,
                job_body=job_body,
                provider_output=provider_output,
                live_provider_called=called,
            )
        except Exception as exc:  # pragma: no cover - missing behavior stays FAIL, never ERROR
            self.fail(f"failed media output must release safely: {type(exc).__name__}: {exc}")
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertIsInstance(result, dict)
        self.assertEqual("released", result.get("status"))
        self.assertEqual(CONTROLLED_POINTS, result.get("points"))
        self.assertEqual(CONTROLLED_POINTS, account.get("available_points"))
        self.assertEqual(0, account.get("reserved_points"))
        terminal = self._terminal_entries(self._reservation_id(job_body))
        self.assertEqual(["release"], [item.get("operation_type") for item in terminal])

    def _assert_pre_provider_block(self, *, inputs: dict[str, Any], expected_blocker: str) -> None:
        task, job_body = self._reservation(inputs=inputs)
        fake_snapshot = {
            "provider": "fixture_media_provider",
            "status": "returned",
            "assets": [
                {
                    "asset_id": "must-not-be-generated",
                    "asset_type": "product_image",
                    "url": "https://cdn.example.test/must-not-be-generated.png",
                    "dimensions": "1600x1600",
                }
            ],
        }
        with _temporary_safe_process_env(
            db_path=Path(self.temp.name) / "runner.sqlite",
            runtime_db_path=Path(self.temp.name) / "runner-runtime.sqlite",
            output_root=Path(self.temp.name) / "runner-output",
        ), patch.dict(os.environ, {"JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true"}, clear=False), patch(
            "jiejing_saas.provider_job_runner.MediaGenerationAdapter.generate",
            return_value=fake_snapshot,
        ) as generate:
            provider_output = ProviderJobRunner().run(
                company_id=self.company_id,
                store_id="store_media_preflight_fixture",
                user_id=self.user_id,
                task_id="task_media_preflight_fixture",
                job_id="job_media_preflight_fixture",
                job_body=job_body,
            )
        try:
            settlement = self.worker._settle_media_credit_reservation(
                task=task,
                job_body=job_body,
                provider_output=provider_output,
                live_provider_called=bool((provider_output.get("safety") or {}).get("live_provider_called")),
            )
        except Exception as exc:
            self.fail(f"pre-provider authorization block must release safely: {type(exc).__name__}: {exc}")
        blockers = {
            str(item)
            for item in [*(provider_output.get("missing_inputs") or []), *(provider_output.get("blocked_by") or [])]
        }
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual(0, generate.call_count, "missing pre-provider authorization must prevent media spend")
        self.assertIn(expected_blocker, blockers)
        self.assertFalse((provider_output.get("safety") or {}).get("live_provider_called"))
        self.assertEqual("released", settlement.get("status"))
        self.assertEqual(CONTROLLED_POINTS, account.get("available_points"))
        self.assertEqual(0, account.get("reserved_points"))

    def test_pre_provider_missing_product_fact_blocks_call_and_releases(self) -> None:
        self._assert_pre_provider_block(
            inputs=self._canonical_inputs(missing_product_fact=True),
            expected_blocker="confirmed_material_or_pending_label",
        )

    def test_pre_provider_missing_source_fact_blocks_call_and_releases(self) -> None:
        self._assert_pre_provider_block(
            inputs=self._canonical_inputs(missing_source_fact=True),
            expected_blocker="reference_images_or_source_notes",
        )

    def test_pre_provider_missing_commercial_rights_blocks_call_and_releases(self) -> None:
        self._assert_pre_provider_block(
            inputs=self._canonical_inputs(commercial_rights_confirmed=False),
            expected_blocker="commercial_use_rights_authorization",
        )

    def test_manifest_validation_blocked_state_releases_full_reservation(self) -> None:
        inputs = self._canonical_inputs()
        output = self._manifest_blocked_output(inputs=inputs)
        task, job_body = self._reservation(inputs=inputs)
        result = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=output,
            live_provider_called=True,
        )
        validation = output["output_packet"].get("asset_manifest_validation") or {}
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual(
            ("blocked_incomplete_manifest", "released", CONTROLLED_POINTS, 0),
            (
                validation.get("status"),
                result.get("status"),
                account.get("available_points"),
                account.get("reserved_points"),
            ),
            "the packet builder and settlement must both reject an unsupported live asset reference",
        )

    def test_post_generation_product_fact_block_releases_full_reservation(self) -> None:
        inputs = self._canonical_inputs(missing_product_fact=True)
        output = self._canonical_provider_output(inputs=inputs)
        self.assertEqual("blocked_missing_product_facts", output["output_packet"]["asset_review"]["status"])
        self._assert_full_release(output, inputs=inputs)

    def test_post_generation_source_fact_block_releases_full_reservation(self) -> None:
        inputs = self._canonical_inputs(missing_source_fact=True)
        output = self._canonical_provider_output(inputs=inputs)
        self.assertEqual("blocked_missing_product_facts", output["output_packet"]["asset_review"]["status"])
        self._assert_full_release(output, inputs=inputs)

    def test_provider_failure_releases_full_reservation(self) -> None:
        inputs = self._canonical_inputs()
        self._assert_full_release(
            self._canonical_provider_output(
                inputs=inputs,
                provider_status="failed_provider_call",
                returned_images=0,
                live_provider_called=False,
            ),
            inputs=inputs,
            live_provider_called=False,
        )

    def test_canonical_needs_review_two_of_four_settles_but_stays_listing_blocked(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        packet = provider_output["output_packet"]
        self.assertEqual("manifest_ready", packet["asset_manifest_validation"]["status"])
        self.assertEqual("waiting_for_human_asset_review", packet["asset_review"]["status"])
        self.assertTrue(packet["asset_review"]["confirmation_center_required_before_listing_use"])
        self.assertEqual(
            {"needs_review"},
            {str(item.get("status")) for item in packet["asset_review"]["review_gates"]},
        )
        self.assertTrue(
            all(asset.get("listing_use_status") == "not_ready_for_listing_until_review" for asset in packet["asset_manifest"])
        )
        result = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=provider_output,
            live_provider_called=True,
        )
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual("settled", result.get("status"))
        self.assertEqual(160, result.get("points"))
        self.assertEqual(160, account.get("available_points"))
        self.assertEqual(0, account.get("reserved_points"))

    def test_duplicate_provider_callback_settles_same_reservation_once(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        first = self.worker._settle_media_credit_reservation(
            task=task, job_body=job_body, provider_output=output, live_provider_called=True
        )
        first_account = self.repository.get_media_credit_account(company_id=self.company_id)
        try:
            replay = self.worker._settle_media_credit_reservation(
                task=task, job_body=job_body, provider_output=output, live_provider_called=True
            )
        except Exception as exc:
            self.fail(f"duplicate provider callback must be idempotent: {type(exc).__name__}: {exc}")
        replay_account = self.repository.get_media_credit_account(company_id=self.company_id)
        terminal = self._terminal_entries(self._reservation_id(job_body))
        self.assertEqual(first_account, replay_account)
        self.assertEqual(first.get("points"), replay.get("points"))
        self.assertEqual(["settle"], [item.get("operation_type") for item in terminal])

    def test_duplicate_provider_failure_releases_same_reservation_once(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        output = self._canonical_provider_output(
            inputs=inputs,
            provider_status="failed_provider_call",
            returned_images=0,
            live_provider_called=False,
        )
        first = self.worker._settle_media_credit_reservation(
            task=task, job_body=job_body, provider_output=output, live_provider_called=False
        )
        first_account = self.repository.get_media_credit_account(company_id=self.company_id)
        try:
            replay = self.worker._settle_media_credit_reservation(
                task=task, job_body=job_body, provider_output=output, live_provider_called=False
            )
        except Exception as exc:
            self.fail(f"duplicate release callback must be idempotent: {type(exc).__name__}: {exc}")
        replay_account = self.repository.get_media_credit_account(company_id=self.company_id)
        terminal = self._terminal_entries(self._reservation_id(job_body))
        self.assertEqual(first_account, replay_account)
        self.assertEqual(first.get("points"), replay.get("points"))
        self.assertEqual(["release"], [item.get("operation_type") for item in terminal])

    def test_valid_output_settles_and_later_human_needs_rework_does_not_reverse_ledger(self) -> None:
        inputs = self._canonical_inputs()
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "needs-rework-ledger", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Needs-rework ledger boundary",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        media_job = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key="needs-rework-ledger-boundary-v1",
            job_spec={"inputs": inputs},
            status="waiting_review",
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=CONTROLLED_POINTS,
            idempotency_key="needs-rework-linked-grant-v1",
            reference_type="test_fixture",
            reference_id=media_job["media_job_id"],
            details={"credit_source": "purchased", "source_reference_id": "needs-rework-linked-source"},
        )
        reservation = self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="reserve",
            points=CONTROLLED_POINTS,
            idempotency_key="needs-rework-linked-reserve-v1",
            reference_type="media_job",
            reference_id=media_job["media_job_id"],
        )
        job_body = {
            "idempotency_key": "needs-rework-ledger-boundary-v1",
            "provider_job_key": "media.asset_generation",
            "media_job_id": media_job["media_job_id"],
            "inputs": inputs,
            "media_credits": {
                "quote": {
                    "estimated_points": CONTROLLED_POINTS,
                    "points_per_image": 80,
                    "image_count": 4,
                    "generation_tier": "standard",
                    "video_requested": False,
                },
                "reservation": reservation,
            },
        }
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        self.repository.update_media_asset_job(
            company_id=self.company_id,
            media_job_id=media_job["media_job_id"],
            status="waiting_review",
            provider_output=provider_output,
        )
        first = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=provider_output,
            live_provider_called=True,
        )
        reservation_id = self._reservation_id(job_body)
        settled_account = self.repository.get_media_credit_account(company_id=self.company_id)
        settled_terminal = self._terminal_entries(reservation_id)

        safe_root = Path(self.temp.name)
        with _temporary_safe_process_env(
            db_path=safe_root / "review-http.sqlite",
            runtime_db_path=safe_root / "review-runtime.sqlite",
            output_root=safe_root / "review-output",
        ):
            settings = SaaSSettings.from_env(
                db_path=safe_root / "review-http.sqlite",
                runtime_db_path=safe_root / "review-runtime.sqlite",
                output_root=safe_root / "review-output",
                host="127.0.0.1",
                port=0,
            )
        sessions = SessionManager(secret="needs-rework-same-reservation-local-http-secret")

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

        TestHandler.repository = self.repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = sessions.create_token(user_id=self.user_id, company_id=self.company_id, email=self.email)
        try:
            status, response = _post_local(
                f"http://127.0.0.1:{server.server_address[1]}",
                f"/media-asset-jobs/{media_job['media_job_id']}/review",
                {"decision": "needs_rework", "note": "merchant rejected this generated version"},
                token,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        reviewed = response.get("media_asset_job") if isinstance(response.get("media_asset_job"), dict) else {}
        review = response.get("review") if isinstance(response.get("review"), dict) else {}
        reviewed_account = self.repository.get_media_credit_account(company_id=self.company_id)
        reviewed_terminal = self._terminal_entries(reservation_id)
        self.assertEqual("settled", first.get("status"))
        self.assertEqual(200, status, response)
        self.assertEqual("needs_rework", reviewed.get("status"))
        self.assertEqual("needs_rework", (reviewed.get("asset_review") or {}).get("listing_use_status"))
        self.assertFalse(review.get("listing_draft_writeback_allowed"))
        self.assertEqual(settled_account, reviewed_account)
        self.assertEqual(settled_terminal, reviewed_terminal)
        self.assertEqual(["settle"], [item.get("operation_type") for item in reviewed_terminal])


class ControlledAcceptancePointContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-controlled-media-red-", ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "saas.sqlite"
        self.runtime_db_path = self.root / "runtime.sqlite"
        self.output_root = self.root / "output"
        self.repository = SaaSRepository(self.db_path, database_engine="sqlite", database_url="")
        fixture = self.repository.create_user_with_company(
            email="controlled-media-owner@example.test",
            password="local-test-password",
            company_name="Controlled media acceptance",
        )
        self.email = fixture["user"]["email"]
        self.company_id = fixture["company"]["company_id"]
        self.user_id = fixture["user"]["user_id"]
        other = self.repository.create_user_with_company(
            email="controlled-media-other@example.test",
            password="local-test-password",
            company_name="Other controlled media tenant",
        )
        self.other_company_id = other["company"]["company_id"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _grant_raw_controlled_source(self, *, expires_at: datetime | None = None, source_ref: str = "acceptance-source") -> dict:
        expiry = expires_at or (datetime.now(timezone.utc) + timedelta(hours=CONTROLLED_TTL_HOURS))
        try:
            return self.repository.apply_media_credit_operation(
                company_id=self.company_id,
                user_id=self.user_id,
                operation_type="grant",
                points=CONTROLLED_POINTS,
                idempotency_key=f"controlled-acceptance-{source_ref}-v1",
                reference_type=CONTROLLED_SOURCE,
                reference_id=source_ref,
                details={
                    "credit_source": CONTROLLED_SOURCE,
                    "source_reference_id": source_ref,
                    "expires_at": expiry.isoformat(),
                },
            )
        except Exception as exc:
            self.fail(f"controlled acceptance source grant is missing: {type(exc).__name__}: {exc}")

    def _bucket_evidence(self, *, source_reference_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                select source_type, source_reference_id, granted_points, remaining_points,
                       reserved_points, expires_at, status
                from media_credit_buckets
                where company_id = ? and source_reference_id = ?
                """,
                (self.company_id, source_reference_id),
            ).fetchone()
        return dict(row) if row else None

    def _run_cli(
        self,
        *,
        account_email: str | None = None,
        expected_company_id: str | None = None,
        owner_confirmation_phrase: str = "",
        enabled: bool | None = False,
        company_allowlist: tuple[str, ...] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if not CLI_PATH.is_file():
            return 127, {"ok": False, "status": "blocked", "reason": "controlled_acceptance_cli_missing"}
        command = [
            sys.executable,
            str(CLI_PATH),
            "--account-email",
            account_email if account_email is not None else self.email,
            "--expected-company-id",
            expected_company_id if expected_company_id is not None else self.company_id,
        ]
        if owner_confirmation_phrase:
            command.extend(["--owner-confirmation-phrase", owner_confirmation_phrase])
        env = _isolated_cli_env(
            db_path=self.db_path,
            runtime_db_path=self.runtime_db_path,
            output_root=self.output_root,
            enabled=enabled,
            company_allowlist=company_allowlist if company_allowlist is not None else (self.company_id,),
        )
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 126, {"ok": False, "status": "blocked", "reason": f"controlled_acceptance_cli_{type(exc).__name__.lower()}"}
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return completed.returncode, {"ok": False, "status": "blocked", "reason": "controlled_acceptance_cli_no_json"}
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = {"ok": False, "status": "blocked", "reason": "controlled_acceptance_cli_invalid_json"}
        return completed.returncode, payload if isinstance(payload, dict) else {}

    def test_controlled_acceptance_remains_independent_source_and_not_purchased(self) -> None:
        before = self.repository.get_media_credit_account(company_id=self.company_id)
        self._grant_raw_controlled_source()
        summary = self.repository.get_media_credit_account(company_id=self.company_id)
        bucket = self._bucket_evidence(source_reference_id="acceptance-source") or {}
        self.assertEqual(before.get("included_points", 0), summary.get("included_points", 0))
        self.assertEqual(before.get("purchased_points", 0), summary.get("purchased_points", 0))
        if "controlled_acceptance_points" in summary:
            self.assertEqual(CONTROLLED_POINTS, summary.get("controlled_acceptance_points"))
        self.assertEqual(CONTROLLED_SOURCE, bucket.get("source_type"))
        self.assertEqual(CONTROLLED_POINTS, bucket.get("remaining_points"))
        self.assertEqual(0, bucket.get("reserved_points"))

    def test_exact_source_reserve_never_uses_plan_or_purchased_points(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="controlled-plan-source-v1",
            reference_type="billing_order",
            reference_id="paid-plan-order",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "paid-plan-order",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="controlled-purchased-source-v1",
            reference_type="billing_order",
            reference_id="paid-pack-order",
            details={"credit_source": "purchased", "source_reference_id": "paid-pack-order"},
        )
        self._grant_raw_controlled_source()
        before = self.repository.get_media_credit_account(company_id=self.company_id)
        try:
            reserved = self.repository.reserve_media_credit_source(
                company_id=self.company_id,
                user_id=self.user_id,
                source_type=CONTROLLED_SOURCE,
                source_reference_id="acceptance-source",
                points=CONTROLLED_POINTS,
                idempotency_key="controlled-acceptance-exact-reserve-v1",
                reference_type="media_job",
                reference_id="controlled-media-job",
            )
        except Exception as exc:
            self.fail(f"controlled_acceptance exact-source reserve is missing: {type(exc).__name__}: {exc}")
        account = reserved.get("account", {})
        controlled_bucket = self._bucket_evidence(source_reference_id="acceptance-source") or {}
        plan_bucket = self._bucket_evidence(source_reference_id="paid-plan-order") or {}
        purchased_bucket = self._bucket_evidence(source_reference_id="paid-pack-order") or {}
        self.assertEqual(before.get("included_points"), account.get("included_points"))
        self.assertEqual(before.get("purchased_points"), account.get("purchased_points"))
        self.assertEqual(CONTROLLED_SOURCE, controlled_bucket.get("source_type"))
        self.assertEqual(CONTROLLED_POINTS, controlled_bucket.get("remaining_points"))
        self.assertEqual(CONTROLLED_POINTS, controlled_bucket.get("reserved_points"))
        self.assertEqual(0, plan_bucket.get("reserved_points"))
        self.assertEqual(0, purchased_bucket.get("reserved_points"))

    def test_expired_controlled_acceptance_points_cannot_be_consumed_or_fall_back(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="expired-control-plan-v1",
            reference_type="billing_order",
            reference_id="expired-control-plan",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "expired-control-plan",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="expired-control-pack-v1",
            reference_type="billing_order",
            reference_id="expired-control-pack",
            details={"credit_source": "purchased", "source_reference_id": "expired-control-pack"},
        )
        self._grant_raw_controlled_source(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1), source_ref="expired-acceptance-source"
        )
        try:
            self.repository.reserve_media_credit_source(
                company_id=self.company_id,
                user_id=self.user_id,
                source_type=CONTROLLED_SOURCE,
                source_reference_id="expired-acceptance-source",
                points=80,
                idempotency_key="expired-control-reserve-v1",
                reference_type="media_job",
                reference_id="expired-controlled-media-job",
            )
        except ValueError as exc:
            self.assertNotIn("unsupported media credit source", str(exc))
        else:
            self.fail("expired controlled acceptance points must be impossible to reserve")
        plan_bucket = self._bucket_evidence(source_reference_id="expired-control-plan") or {}
        purchased_bucket = self._bucket_evidence(source_reference_id="expired-control-pack") or {}
        expired_bucket = self._bucket_evidence(source_reference_id="expired-acceptance-source") or {}
        self.assertEqual(0, plan_bucket.get("reserved_points"))
        self.assertEqual(0, purchased_bucket.get("reserved_points"))
        self.assertEqual(0, expired_bucket.get("reserved_points"))

    def test_controlled_acceptance_is_disabled_by_default(self) -> None:
        code, payload = self._run_cli(owner_confirmation_phrase=CONTROLLED_APPROVAL, enabled=None)
        self.assertNotEqual(0, code)
        self.assertEqual("controlled_acceptance_disabled", payload.get("reason"))
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id).get("available_points"))

    def test_controlled_acceptance_requires_explicit_company_whitelist(self) -> None:
        code, payload = self._run_cli(
            owner_confirmation_phrase=CONTROLLED_APPROVAL,
            enabled=True,
            company_allowlist=(self.other_company_id,),
        )
        self.assertNotEqual(0, code)
        self.assertEqual("controlled_acceptance_company_not_allowlisted", payload.get("reason"))
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id).get("available_points"))

    def test_controlled_acceptance_rejects_account_company_tenant_mismatch(self) -> None:
        code, payload = self._run_cli(
            enabled=True,
            owner_confirmation_phrase=CONTROLLED_APPROVAL,
            account_email=self.email,
            expected_company_id=self.other_company_id,
            company_allowlist=(self.company_id, self.other_company_id),
        )
        self.assertNotEqual(0, code)
        self.assertEqual("controlled_acceptance_account_company_mismatch", payload.get("reason"))
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id).get("available_points"))
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.other_company_id).get("available_points"))

    def test_controlled_acceptance_requires_owner_confirmation_phrase(self) -> None:
        code, payload = self._run_cli(owner_confirmation_phrase="", enabled=True)
        self.assertNotEqual(0, code)
        self.assertEqual("controlled_acceptance_owner_approval_required", payload.get("reason"))
        self.assertEqual(CONTROLLED_APPROVAL, payload.get("required_approval"))

    def test_controlled_acceptance_requires_exact_owner_confirmation_phrase(self) -> None:
        code, payload = self._run_cli(
            owner_confirmation_phrase="WRONG_CONTROLLED_MEDIA_ACCEPTANCE_PHRASE",
            enabled=True,
        )
        self.assertNotEqual(0, code)
        self.assertEqual("controlled_acceptance_owner_approval_required", payload.get("reason"))
        self.assertEqual(CONTROLLED_APPROVAL, payload.get("required_approval"))

    def test_cli_grants_fixed_24h_source_once_and_writes_audit_evidence(self) -> None:
        before = datetime.now(timezone.utc)
        account_before = self.repository.get_media_credit_account(company_id=self.company_id)
        first_code, first = self._run_cli(owner_confirmation_phrase=CONTROLLED_APPROVAL, enabled=True)
        after = datetime.now(timezone.utc)
        self.assertEqual(0, first_code, first)
        self.assertTrue(first.get("ok"))
        self.assertEqual(self.company_id, first.get("company_id"))
        self.assertEqual(self.email, first.get("account_email"))
        self.assertEqual(CONTROLLED_SOURCE, first.get("credit_source"))
        self.assertEqual(CONTROLLED_POINTS, first.get("points_granted"))
        self.assertEqual(CONTROLLED_TTL_HOURS, first.get("ttl_hours"))
        self.assertFalse(first.get("duplicate_request"))
        self.assertFalse(first.get("external_provider_action_triggered"))
        self.assertFalse(first.get("real_platform_write_performed"))
        self.assertFalse(first.get("secret_exposed"))
        expiry = datetime.fromisoformat(str(first.get("expires_at") or "").replace("Z", "+00:00"))
        self.assertGreaterEqual(expiry, before + timedelta(hours=23, minutes=55))
        self.assertLessEqual(expiry, after + timedelta(hours=24, minutes=5))

        replay_code, replay = self._run_cli(owner_confirmation_phrase=CONTROLLED_APPROVAL, enabled=True)
        self.assertEqual(0, replay_code, replay)
        self.assertTrue(replay.get("duplicate_request"))
        self.assertEqual(first.get("source_reference_id"), replay.get("source_reference_id"))

        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual(account_before.get("included_points", 0), account.get("included_points", 0))
        self.assertEqual(account_before.get("purchased_points", 0), account.get("purchased_points", 0))
        if "controlled_acceptance_points" in account:
            self.assertEqual(CONTROLLED_POINTS, account.get("controlled_acceptance_points"))
        bucket = self._bucket_evidence(source_reference_id=str(first.get("source_reference_id") or "")) or {}
        self.assertEqual(CONTROLLED_SOURCE, bucket.get("source_type"))
        self.assertEqual(CONTROLLED_POINTS, bucket.get("remaining_points"))
        controlled_grants = [
            item
            for item in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if item.get("operation_type") == "grant" and item.get("reference_type") == CONTROLLED_SOURCE
        ]
        self.assertEqual(1, len(controlled_grants))
        audits = self.repository.list_audit_logs(company_id=self.company_id, limit=100)
        acceptance_audits = [
            item
            for item in audits
            if item.get("action_type") == "media_credit.controlled_acceptance.granted"
        ]
        self.assertEqual(1, len(acceptance_audits), "controlled grant must leave one tenant-scoped audit record")
        audit = acceptance_audits[0]
        details = audit.get("details") if isinstance(audit.get("details"), dict) else {}
        self.assertEqual(self.company_id, audit.get("company_id"))
        self.assertEqual("media_credit_bucket", audit.get("target_type"))
        self.assertEqual(str(first.get("source_reference_id")), audit.get("target_id"))
        self.assertEqual(CONTROLLED_SOURCE, details.get("credit_source"))
        self.assertEqual(CONTROLLED_POINTS, details.get("points"))
        self.assertEqual(CONTROLLED_TTL_HOURS, details.get("ttl_hours"))
        self.assertFalse(details.get("external_provider_action_triggered"))
        self.assertFalse(audit.get("secret_exposed"))

    def test_cli_requires_account_and_company_but_exposes_no_points_or_expiry_override(self) -> None:
        if not CLI_PATH.is_file():
            self.fail("ops-only controlled acceptance CLI is missing")
        help_run = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            cwd=ROOT,
            env=_isolated_cli_env(
                db_path=self.db_path,
                runtime_db_path=self.runtime_db_path,
                output_root=self.output_root,
                enabled=False,
                company_allowlist=(),
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(0, help_run.returncode)
        self.assertIn("--account-email", help_run.stdout)
        self.assertIn("--expected-company-id", help_run.stdout)
        self.assertNotIn("--idempotency-key", help_run.stdout)
        self.assertIn("--owner-confirmation-phrase", help_run.stdout)
        self.assertNotIn("--approve-controlled-media-acceptance", help_run.stdout)
        self.assertNotIn("--source-reference-id", help_run.stdout)
        self.assertNotIn("--source-ref", help_run.stdout)
        self.assertNotIn("--source-key", help_run.stdout)
        self.assertNotIn("--points", help_run.stdout)
        self.assertNotIn("--ttl", help_run.stdout)
        self.assertNotIn("--expires", help_run.stdout)

    def test_cli_rejects_idempotency_override_and_cannot_create_a_second_grant(self) -> None:
        first_code, first = self._run_cli(owner_confirmation_phrase=CONTROLLED_APPROVAL, enabled=True)
        self.assertEqual(0, first_code, first)
        before = [
            item
            for item in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if item.get("operation_type") == "grant" and item.get("reference_type") == CONTROLLED_SOURCE
        ]
        attempted = subprocess.run(
            [
                sys.executable,
                str(CLI_PATH),
                "--account-email",
                self.email,
                "--expected-company-id",
                self.company_id,
                "--owner-confirmation-phrase",
                CONTROLLED_APPROVAL,
                "--idempotency-key",
                "attacker-selected-second-grant",
                "--source-reference-id",
                "attacker-selected-second-source",
            ],
            cwd=ROOT,
            env=_isolated_cli_env(
                db_path=self.db_path,
                runtime_db_path=self.runtime_db_path,
                output_root=self.output_root,
                enabled=True,
                company_allowlist=(self.company_id,),
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        after = [
            item
            for item in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if item.get("operation_type") == "grant" and item.get("reference_type") == CONTROLLED_SOURCE
        ]
        self.assertNotEqual(0, attempted.returncode)
        self.assertEqual(before, after)

    def test_queued_standard_media_job_reserves_only_controlled_acceptance_bucket(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="http-controlled-plan-v1",
            reference_type="billing_order",
            reference_id="http-controlled-plan",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "http-controlled-plan",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="http-controlled-pack-v1",
            reference_type="billing_order",
            reference_id="http-controlled-pack",
            details={"credit_source": "purchased", "source_reference_id": "http-controlled-pack"},
        )
        self._grant_raw_controlled_source(source_ref="http-controlled-acceptance")
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "controlled-http-store", "marketplace": "EBAY_US"},
        )
        with _temporary_safe_process_env(
            db_path=self.db_path, runtime_db_path=self.runtime_db_path, output_root=self.output_root
        ):
            settings = SaaSSettings.from_env(
                db_path=self.db_path,
                runtime_db_path=self.runtime_db_path,
                output_root=self.output_root,
                host="127.0.0.1",
                port=0,
            )
        sessions = SessionManager(secret="controlled-acceptance-media-queue-local-secret")

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

        TestHandler.repository = self.repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
        TestHandler.queue_worker = LocalQueueWorker(repository=self.repository, runtime_bridge=object())
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = sessions.create_token(user_id=self.user_id, company_id=self.company_id, email=self.email)
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with patch.dict(
                os.environ,
                {
                    "JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "true",
                    "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_ENABLED": "true",
                    "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_COMPANY_ALLOWLIST": self.company_id,
                    "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false",
                },
                clear=False,
            ), patch("jiejing_saas.provider_job_runner.MediaGenerationAdapter.generate") as generate:
                status, body = _post_local(
                    base_url,
                    f"/stores/{store['store_id']}/provider-jobs/queue",
                    {
                        "provider_job_key": "media.asset_generation",
                        "idempotency_key": "controlled-http-standard-media-v1",
                        "inputs": MediaSettlementContractTest._canonical_inputs(),
                        "run_mode": "queued",
                    },
                    token,
                )
            self.assertEqual(0, generate.call_count)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        controlled = self._bucket_evidence(source_reference_id="http-controlled-acceptance") or {}
        plan = self._bucket_evidence(source_reference_id="http-controlled-plan") or {}
        purchased = self._bucket_evidence(source_reference_id="http-controlled-pack") or {}
        reservation = ((body.get("media_credits") or {}).get("reservation") or {}) if isinstance(body, dict) else {}
        self.assertEqual(202, status, body)
        self.assertEqual("queued", (body.get("queue_job") or {}).get("status"))
        self.assertEqual(
            CONTROLLED_SOURCE,
            ((reservation.get("ledger_entry") or {}).get("details") or {}).get("credit_source"),
        )
        self.assertEqual(CONTROLLED_POINTS, controlled.get("reserved_points"))
        self.assertEqual(0, plan.get("reserved_points"))
        self.assertEqual(0, purchased.get("reserved_points"))

    def test_authenticated_local_http_has_no_controlled_acceptance_grant_route(self) -> None:
        for router in (SaaSBackendHandler._handle_post, SaaSBackendHandler.do_POST):
            source = textwrap.dedent(inspect.getsource(router))
            tree = ast.parse(source)
            string_constants = {
                "".join(character for character in node.value.lower() if character.isalnum())
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            normalized_source = "".join(character for character in source.lower() if character.isalnum())
            self.assertNotIn(
                "controlledacceptance",
                normalized_source,
                f"{router.__name__} must not register any controlled-acceptance route or handler",
            )
            self.assertFalse(
                any("controlled" in value and "acceptance" in value for value in string_constants),
                f"{router.__name__} must not contain any controlled-acceptance public path literal",
            )
        with _temporary_safe_process_env(
            db_path=self.db_path, runtime_db_path=self.runtime_db_path, output_root=self.output_root
        ):
            settings = SaaSSettings.from_env(
                db_path=self.db_path,
                runtime_db_path=self.runtime_db_path,
                output_root=self.output_root,
                host="127.0.0.1",
                port=0,
            )
        sessions = SessionManager(secret="controlled-acceptance-local-route-test-secret")

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

        TestHandler.repository = self.repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(user_id=self.user_id, company_id=self.company_id, email=self.email)
        before_ledger = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
        before_audits = self.repository.list_audit_logs(company_id=self.company_id, limit=100)
        try:
            for path in (
                "/media-controlled-acceptance/grant",
                "/api/media-controlled-acceptance/grant",
                "/media/controlled-acceptance/grant",
            ):
                status, body = _post_local(
                    base_url,
                    path,
                    {
                        "account_email": self.email,
                        "company_id": self.company_id,
                        "points": CONTROLLED_POINTS,
                "owner_confirmation_phrase": CONTROLLED_APPROVAL,
                    },
                    token,
                )
                self.assertEqual(404, status, {"path": path, "body": body})
                self.assertNotIn("points_granted", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(before_ledger, self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100))
        self.assertEqual(before_audits, self.repository.list_audit_logs(company_id=self.company_id, limit=100))
        self.assertEqual(0, self.repository.get_media_credit_account(company_id=self.company_id).get("available_points"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
