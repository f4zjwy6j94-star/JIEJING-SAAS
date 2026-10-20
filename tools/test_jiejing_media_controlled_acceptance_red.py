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
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import (  # noqa: E402
    SaaSBackendHandler,
    _compensate_provider_queue_creation_failure,
    _create_provider_job_queue_records,
    _merchant_safe_replaceable_media_provider,
    _reconcile_media_asset_job_review_readiness,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.media_asset_pipeline import (  # noqa: E402
    build_media_asset_generation_packet,
    media_asset_is_video,
    media_manifest_matches_approved_quote,
)
from jiejing_saas.media_source_assets import MediaSourceAsset, MediaSourceAssetError  # noqa: E402
from jiejing_saas.provider_job_runner import ProviderJobRunner  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402
from jiejing_saas.worker import LocalQueueWorker  # noqa: E402
CONTROLLED_POINTS = 320
CONTROLLED_TTL_HOURS = 24
CONTROLLED_APPROVAL = "I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS"
CONTROLLED_SOURCE = "controlled_acceptance"
CONTROLLED_SOURCE_REFERENCE_PREFIX = "controlled-media-acceptance-v1"
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
        with urllib.request.urlopen(request, timeout=30) as response:
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

    def test_worker_retries_one_transient_private_source_read(self) -> None:
        content = b"merchant-private-source"
        asset = MediaSourceAsset(
            asset_id="media_src_aaaaaaaaaaaaaaaa",
            content_type="image/png",
            size_bytes=len(content),
            sha256="a" * 64,
            original_filename="merchant-source.png",
            created_at=1,
            retention_expires_at=2,
            width=1,
            height=1,
            file_path=Path(self.temp.name) / "merchant-source.png",
        )

        class TransientStore:
            def __init__(self) -> None:
                self.calls = 0

            def read_for_provider(self, **_kwargs: Any) -> tuple[MediaSourceAsset, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise MediaSourceAssetError("asset_not_found", "transient mount visibility miss")
                return asset, content

        source_store = TransientStore()
        worker = LocalQueueWorker(
            repository=self.repository,
            runtime_bridge=object(),
            settings=SimpleNamespace(output_root=Path(self.temp.name)),
            media_source_asset_store=source_store,  # type: ignore[arg-type]
        )
        with patch("jiejing_saas.worker.time.sleep") as sleep_mock:
            hydrated = worker._hydrate_private_media_source(
                company_id=self.company_id,
                store_id="store_source_retry",
                job_body={
                    "provider_job_key": "media.asset_generation",
                    "inputs": {"product_facts": {"source_asset_id": asset.asset_id}},
                },
            )

        self.assertEqual(2, source_store.calls)
        sleep_mock.assert_called_once()
        self.assertTrue(hydrated["inputs"].get("private_media_source_hydrated"))
        self.assertTrue(str(hydrated["inputs"].get("reference_image_url") or "").startswith("data:image/png;base64,"))

    def test_worker_does_not_retry_permanent_private_source_errors(self) -> None:
        class PermanentFailureStore:
            def __init__(self) -> None:
                self.calls = 0

            def read_for_provider(self, **_kwargs: Any) -> tuple[MediaSourceAsset, bytes]:
                self.calls += 1
                raise MediaSourceAssetError("asset_scope_mismatch", "wrong tenant")

        source_store = PermanentFailureStore()
        worker = LocalQueueWorker(
            repository=self.repository,
            runtime_bridge=object(),
            settings=SimpleNamespace(output_root=Path(self.temp.name)),
            media_source_asset_store=source_store,  # type: ignore[arg-type]
        )
        with patch("jiejing_saas.worker.time.sleep") as sleep_mock:
            with self.assertRaisesRegex(MediaSourceAssetError, "wrong tenant"):
                worker._hydrate_private_media_source(
                    company_id=self.company_id,
                    store_id="store_source_retry",
                    job_body={
                        "provider_job_key": "media.asset_generation",
                        "inputs": {"product_facts": {"source_asset_id": "media_src_aaaaaaaaaaaaaaaa"}},
                    },
                )

        self.assertEqual(1, source_store.calls)
        sleep_mock.assert_not_called()

    def test_media_retry_preflights_private_source_before_creating_child(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "retry-source-preflight", "marketplace": "EBAY_US"},
        )
        inputs = self._canonical_inputs()
        inputs["product_facts"]["source_asset_id"] = "media_src_aaaaaaaaaaaaaaaa"
        inputs["product_facts"]["source_image_sha256"] = "a" * 64
        original_task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Retry source preflight original",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        original = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=original_task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key="retry-source-preflight-original-v1",
            job_spec={
                "provider_job_key": "media.asset_generation",
                "contract_version": "test-contract",
                "inputs": inputs,
                "media_credits": None,
            },
            status="needs_rework",
        )
        safe_root = Path(self.temp.name)
        with _temporary_safe_process_env(
            db_path=safe_root / "retry-source-preflight-http.sqlite",
            runtime_db_path=safe_root / "retry-source-preflight-runtime.sqlite",
            output_root=safe_root / "retry-source-preflight-output",
        ):
            settings = SaaSSettings.from_env(
                db_path=safe_root / "retry-source-preflight-http.sqlite",
                runtime_db_path=safe_root / "retry-source-preflight-runtime.sqlite",
                output_root=safe_root / "retry-source-preflight-output",
                host="127.0.0.1",
                port=0,
            )
        sessions = SessionManager(secret="retry-source-preflight-local-http-secret")

        class MissingSourceStore:
            def __init__(self) -> None:
                self.calls = 0

            def read_for_provider(self, **_kwargs: Any) -> tuple[MediaSourceAsset, bytes]:
                self.calls += 1
                raise MediaSourceAssetError("asset_not_found", "source no longer retained")

        source_store = MissingSourceStore()

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

        TestHandler.repository = self.repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
        TestHandler.queue_worker = self.worker
        TestHandler.media_source_asset_store = source_store  # type: ignore[assignment]
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = sessions.create_token(user_id=self.user_id, company_id=self.company_id, email=self.email)
        try:
            with patch.dict(
                os.environ,
                {
                    "JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "true",
                    "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true",
                    "JIEJING_QUEUE_PROVIDER": "local_worker",
                },
                clear=False,
            ):
                status, response = _post_local(
                    f"http://127.0.0.1:{server.server_address[1]}",
                    f"/media-asset-jobs/{original['media_job_id']}/retry",
                    {"reason": "merchant requested a corrected image", "run_mode": "queued"},
                    token,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        child_key = f"media-rework:{original['media_job_id']}:v2"
        child = self.repository.get_media_asset_job_by_idempotency(
            company_id=self.company_id,
            idempotency_key=child_key,
        )
        reserve_entries = [
            entry
            for entry in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if entry.get("operation_type") == "reserve" and entry.get("reference_id") == child_key
        ]
        self.assertEqual(422, status, response)
        self.assertEqual(["private_media_source_asset_not_found"], response.get("missing_inputs"))
        self.assertFalse(response.get("provider_call_triggered"))
        self.assertFalse(response.get("triggers_real_charge"))
        self.assertEqual(1, source_store.calls)
        self.assertIsNone(child)
        self.assertEqual([], reserve_entries)

    def test_postgres_shaped_credit_timestamps_survive_media_queue_persistence(self) -> None:
        """Postgres returns timestamptz values as datetimes; the queue graph must persist them safely."""

        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "postgres-shaped-media-credit", "marketplace": "EBAY_US"},
        )
        credit_state = {
            "enforcement_enabled": True,
            "quote": {
                "estimated_points": 20,
                "points_per_image": 20,
                "image_count": 1,
                "generation_tier": "fast",
                "video_requested": False,
            },
            "reservation": {
                "status": "reserved",
                "ledger_entry": {
                    "ledger_id": "mcredit_postgres_timestamp_contract",
                    "operation_type": "reserve",
                    "points": 20,
                    "created_at": datetime(2026, 8, 24, 8, 18, 52, tzinfo=timezone.utc),
                },
            },
        }
        creation_state: dict[str, Any] = {}
        task, media_job, queue_job = _create_provider_job_queue_records(
            self.repository,
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            title="Postgres-shaped controlled media acceptance",
            provider_job_key="media.asset_generation",
            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
            contract_version="postgres-shaped-media-credit-v1",
            safe_inputs=self._canonical_inputs(),
            media_idempotency_key="postgres-shaped-media-credit-v1",
            media_request_fingerprint="postgres-shaped-media-credit-fingerprint-v1",
            media_credit_state=credit_state,
            is_media_provider_job=True,
            secret_ref="",
            run_mode="queued",
            creation_state=creation_state,
        )

        self.assertEqual("committed", creation_state.get("stage"))
        self.assertEqual("queued", task.get("status"))
        self.assertIsInstance(media_job, dict)
        self.assertEqual("queued", (media_job or {}).get("status"))
        self.assertEqual("queued", queue_job.get("status"))
        persisted_timestamp = (
            task.get("input", {})
            .get("media_credits", {})
            .get("reservation", {})
            .get("ledger_entry", {})
            .get("created_at")
        )
        self.assertEqual("2026-08-24T08:18:52+00:00", persisted_timestamp)

    def test_browser_media_redaction_preserves_safe_manifest_transport_url(self) -> None:
        asset_url = "https://v3b.fal.media/files/b/fixture/generated.jpg"
        browser_payload = _merchant_safe_replaceable_media_provider(
            {
                "media_provider": "fal",
                "asset_manifest": [
                    {
                        "url": asset_url,
                        "url_or_file_path": asset_url,
                        "source_provider_or_upload": "fal",
                    }
                ],
                "diagnostic": "fal driver is replaceable",
            }
        )

        self.assertEqual("jiejing_media_router", browser_payload.get("media_provider"))
        self.assertEqual("jiejing_media_router driver is replaceable", browser_payload.get("diagnostic"))
        asset = browser_payload.get("asset_manifest", [{}])[0]
        self.assertEqual(asset_url, asset.get("url"))
        self.assertEqual(asset_url, asset.get("url_or_file_path"))
        self.assertEqual("jiejing_media_router", asset.get("source_provider_or_upload"))

    def test_browser_media_redaction_rejects_capability_bearing_manifest_url(self) -> None:
        unsafe_url = "https://v3b.fal.media/files/generated.jpg?signature=do-not-return"
        browser_payload = _merchant_safe_replaceable_media_provider(
            {"asset_manifest": [{"url": unsafe_url}]}
        )

        self.assertEqual("", browser_payload.get("asset_manifest", [{}])[0].get("url"))

    def test_browser_redaction_preserves_public_urls_outside_media_manifest(self) -> None:
        url = "https://v3b.fal.media/files/b/fixture/gold-set.jpg"
        other = "https://fal.media/files/detail.jpg"
        for separator in ("\n", " ", ",", ";", "，", "；"):
            urls = separator.join((url, other))
            with self.subTest(separator=separator):
                payload = _merchant_safe_replaceable_media_provider({
                    "merchant_confirmed_facts": {"image_urls": urls},
                    "source_records": [{"type": "merchant_product_image", "url": url}],
                    "fields": {"images": urls},
                    "publish_prefill": {"imageUrls": [url, other]},
                    "media_provider": "fal",
                    "diagnostic": "fal driver is replaceable",
                })
                self.assertEqual(payload["merchant_confirmed_facts"]["image_urls"], urls)
                self.assertEqual(payload["source_records"][0]["url"], url)
                self.assertEqual(payload["fields"]["images"], urls)
                self.assertEqual(payload["publish_prefill"]["imageUrls"], [url, other])
                self.assertEqual(payload["media_provider"], "jiejing_media_router")
                self.assertEqual(payload["diagnostic"], "jiejing_media_router driver is replaceable")

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
                "supplier_facts": {
                    "material": "" if missing_product_fact else "stainless steel",
                    "package_dimensions_cm": {"length": 10, "width": 10, "height": 18},
                },
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
        self.assertEqual(
            ["release"],
            [item.get("operation_type") for item in self._terminal_entries(self._reservation_id(job_body))],
            "a pre-provider blocker must close the reservation with exactly one release",
        )

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

    def test_pre_provider_non_deliverable_source_placeholder_blocks_call_and_releases(self) -> None:
        inputs = self._canonical_inputs()
        inputs["product_facts"]["reference_images"] = ["merchant-upload-placeholder"]
        self._assert_pre_provider_block(
            inputs=inputs,
            expected_blocker="reference_images_or_source_notes",
        )

    def test_pre_provider_missing_commercial_rights_blocks_call_and_releases(self) -> None:
        self._assert_pre_provider_block(
            inputs=self._canonical_inputs(commercial_rights_confirmed=False),
            expected_blocker="commercial_use_rights_authorization",
        )

    def test_pre_provider_missing_product_identity_blocks_call_and_releases(self) -> None:
        inputs = self._canonical_inputs()
        inputs["product_facts"]["product"] = ""
        self._assert_pre_provider_block(inputs=inputs, expected_blocker="product_identity")

    def test_pre_provider_dimension_scene_without_dimensions_blocks_call_and_releases(self) -> None:
        inputs = self._canonical_inputs()
        inputs["product_facts"]["supplier_facts"].pop("package_dimensions_cm")
        self._assert_pre_provider_block(
            inputs=inputs,
            expected_blocker="confirmed_dimensions_or_pending_label",
        )

    def test_pre_provider_listing_without_marketplace_rules_blocks_call_and_releases(self) -> None:
        inputs = self._canonical_inputs()
        inputs["product_facts"].pop("target_marketplace_rules")
        self._assert_pre_provider_block(inputs=inputs, expected_blocker="target_marketplace_rules")

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

    def test_provider_blocked_state_releases_full_reservation(self) -> None:
        inputs = self._canonical_inputs()
        output = self._canonical_provider_output(
            inputs=inputs,
            provider_status="blocked_provider_quota",
            returned_images=0,
            live_provider_called=False,
        )
        output["missing_inputs"] = ["media_provider_quota_blocked"]
        self._assert_full_release(output, inputs=inputs, live_provider_called=False)

    def test_mixed_failed_and_rights_blocked_assets_settle_only_deliverable_files(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        output = self._canonical_provider_output(inputs=inputs, returned_images=3)
        manifest = output["output_packet"]["asset_manifest"]
        manifest[1]["status"] = "failed"
        manifest[2]["commercial_use_status"] = "blocked_rights"
        result = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=output,
            live_provider_called=True,
        )
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual("settled", result.get("status"))
        self.assertEqual(80, result.get("points"))
        self.assertEqual("successful_asset_count", result.get("points_source"))
        self.assertEqual(240, account.get("available_points"))

    def test_all_supported_image_manifest_types_use_actual_asset_count(self) -> None:
        for asset_type in ("main_image", "detail_page", "size_chart", "lifestyle_image"):
            with self.subTest(asset_type=asset_type):
                inputs = self._canonical_inputs()
                task, job_body = self._reservation(inputs=inputs)
                output = self._canonical_provider_output(inputs=inputs, returned_images=1)
                output["output_packet"]["asset_manifest"][0]["asset_type"] = asset_type
                result = self.worker._settle_media_credit_reservation(
                    task=task,
                    job_body=job_body,
                    provider_output=output,
                    live_provider_called=True,
                )
                self.assertEqual("settled", result.get("status"))
                self.assertEqual(80, result.get("points"))
                self.assertEqual("successful_asset_count", result.get("points_source"))

    def test_unpriced_video_output_releases_the_full_reservation(self) -> None:
        for mixed_with_image in (False, True):
            with self.subTest(mixed_with_image=mixed_with_image):
                inputs = self._canonical_inputs()
                available_before = self.repository.get_media_credit_account(company_id=self.company_id).get("available_points", 0)
                task, job_body = self._reservation(inputs=inputs)
                output = self._canonical_provider_output(
                    inputs=inputs,
                    returned_images=2 if mixed_with_image else 1,
                )
                manifest = output["output_packet"]["asset_manifest"]
                manifest[-1]["asset_type"] = "product_video"
                manifest[-1]["url_or_file_path"] = "https://cdn.example.test/unpriced-video.mp4"
                result = self.worker._settle_media_credit_reservation(
                    task=task,
                    job_body=job_body,
                    provider_output=output,
                    live_provider_called=True,
                )
                account = self.repository.get_media_credit_account(company_id=self.company_id)
                self.assertEqual("released", result.get("status"))
                self.assertEqual(available_before + CONTROLLED_POINTS, account.get("available_points"))
                self.assertEqual(0, account.get("reserved_points"))

    def test_extensionless_video_mime_cannot_settle_as_an_image(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        packet = build_media_asset_generation_packet(
            base={
                "packet_type": "asset_manifest",
                "provider_family": "media",
                "source_record_type": "media_provider",
                "status": "dry_run_ready",
                "missing_inputs": [],
                "live_provider_called": False,
                "secret_exposed": False,
            },
            contract_key="media.asset_generation",
            inputs=inputs,
            captured_at="2026-08-23T00:00:00+00:00",
            live_media_snapshot={
                "provider": "fixture_media_provider",
                "status": "returned",
                "assets": [
                    {
                        "asset_id": "extensionless-video",
                        "asset_type": "provider_blob",
                        "url": "https://cdn.example.test/object?id=video-1",
                        "mime_type": "video/mp4",
                        "status": "generated",
                        "commercial_use_status": "needs_rights_review",
                    }
                ],
            },
        )
        manifest = packet.get("asset_manifest") if isinstance(packet.get("asset_manifest"), list) else []
        self.assertEqual(1, len(manifest))
        self.assertEqual("video/mp4", manifest[0].get("mime_type"))
        self.assertTrue(media_asset_is_video(manifest[0]))
        self.assertTrue(packet.get("safety", {}).get("calls_video_provider"))
        self.assertFalse(packet.get("safety", {}).get("calls_image_provider"))
        self.assertFalse(media_manifest_matches_approved_quote(job_body["media_credits"]["quote"], manifest))
        provider_output = {
            "status": "completed_live_media_provider",
            "provider_job_key": "media.asset_generation",
            "missing_inputs": [],
            "output_packet": packet,
            "safety": packet.get("safety") if isinstance(packet.get("safety"), dict) else {},
        }
        settlement = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=provider_output,
            live_provider_called=True,
        )
        self.assertEqual("released", settlement.get("status"))

    def test_conflicting_image_type_and_video_mime_fails_closed(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        packet = build_media_asset_generation_packet(
            base={
                "packet_type": "asset_manifest",
                "provider_family": "media",
                "source_record_type": "media_provider",
                "status": "dry_run_ready",
                "missing_inputs": [],
                "live_provider_called": False,
                "secret_exposed": False,
            },
            contract_key="media.asset_generation",
            inputs=inputs,
            captured_at="2026-08-23T00:00:00+00:00",
            live_media_snapshot={
                "provider": "fixture_media_provider",
                "status": "returned",
                "assets": [
                    {
                        "asset_id": "conflicting-media-type",
                        "asset_type": "product_image",
                        "url": "https://cdn.example.test/object?id=conflict-1",
                        "mime_type": "video/mp4",
                        "status": "generated",
                        "commercial_use_status": "needs_rights_review",
                    }
                ],
            },
        )
        manifest = packet.get("asset_manifest") if isinstance(packet.get("asset_manifest"), list) else []
        self.assertFalse(any(item.get("asset_id") == "conflicting-media-type" for item in manifest if isinstance(item, dict)))
        self.assertEqual("blocked_incomplete_manifest", packet.get("asset_manifest_validation", {}).get("status"))
        self.assertFalse(packet.get("live_provider_called"))
        provider_output = {
            "status": "completed_live_media_provider",
            "provider_job_key": "media.asset_generation",
            "missing_inputs": [],
            "output_packet": packet,
            "safety": packet.get("safety") if isinstance(packet.get("safety"), dict) else {},
        }
        settlement = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=provider_output,
            live_provider_called=True,
        )
        self.assertEqual("released", settlement.get("status"))

    def test_settled_provider_returned_job_is_read_repaired_to_waiting_review(self) -> None:
        inputs = self._canonical_inputs()
        task_stub, job_body = self._reservation(inputs=inputs)
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "settlement-read-repair", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Settlement read repair",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        media_job = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key="settlement-read-repair-v1",
            job_spec={
                "inputs": inputs,
                "media_credits": {
                    **job_body["media_credits"],
                    "enforcement_enabled": True,
                },
            },
            status="running",
        )
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        provider_returned = self.repository.update_media_asset_job(
            company_id=self.company_id,
            media_job_id=media_job["media_job_id"],
            status="provider_returned",
            provider_output=provider_output,
            error_reason="media_credit_settlement_pending",
        )
        settled = self.worker._settle_media_credit_reservation(
            task=task_stub,
            job_body={**job_body, "media_job_id": media_job["media_job_id"]},
            provider_output=provider_output,
            live_provider_called=True,
        )
        self.assertEqual("settled", settled.get("status"))
        repaired = _reconcile_media_asset_job_review_readiness(
            self.repository,
            company_id=self.company_id,
            media_job=provider_returned,
        )
        self.assertEqual("waiting_review", repaired.get("status"))
        second = _reconcile_media_asset_job_review_readiness(
            self.repository,
            company_id=self.company_id,
            media_job=repaired,
        )
        self.assertEqual("waiting_review", second.get("status"))

    def _released_failed_media_job(self, *, status: str = "provider_returned") -> dict[str, Any]:
        inputs = self._canonical_inputs()
        _, job_body = self._reservation(inputs=inputs)
        store = self.repository.create_store(
            company_id=self.company_id, user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "released-media-recovery", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id, store_id=store["store_id"], user_id=self.user_id,
            task_type="provider_job", title="Released media recovery",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        media = self.repository.create_media_asset_job(
            company_id=self.company_id, store_id=store["store_id"], task_id=task["task_id"],
            user_id=self.user_id, provider_job_key="media.asset_generation",
            idempotency_key=job_body["idempotency_key"],
            job_spec={**job_body, "media_credits": {**job_body["media_credits"], "enforcement_enabled": True}},
        )
        job_body.update({"kind": "provider_job", "media_job_id": media["media_job_id"]})
        queue = self.repository.create_queue_job(
            company_id=self.company_id, task_id=task["task_id"], job_data=job_body, publish=False,
        )
        self.repository.update_media_asset_job(
            company_id=self.company_id, media_job_id=media["media_job_id"], status=status,
            queue_job_id=queue["job_id"], provider_output=self._canonical_provider_output(inputs=inputs),
            error_reason="media_credit_settlement_pending",
        )
        self.worker._release_media_credit_reservation(task=task, job_body=job_body, reason="settlement_write_failed")
        self.repository.update_task_status(task_id=task["task_id"], company_id=self.company_id, status="failed")
        self.repository.update_queue_job(job_id=queue["job_id"], company_id=self.company_id, status="failed")
        return self.repository.get_media_asset_job(company_id=self.company_id, media_job_id=media["media_job_id"]) or {}

    def test_released_failed_media_job_becomes_retryable_without_restoring_review(self) -> None:
        media = self._released_failed_media_job()
        before_ledger = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
        before_account = self.repository.get_media_credit_account(company_id=self.company_id)
        repaired = _reconcile_media_asset_job_review_readiness(
            self.repository, company_id=self.company_id, media_job=media,
        )
        self.assertEqual("needs_rework", repaired.get("status"))
        self.assertEqual("needs_rework", repaired["asset_review"]["listing_use_status"])
        self.assertTrue(all(asset["listing_use_status"] == "needs_rework" for asset in repaired["asset_manifest"]))
        second = _reconcile_media_asset_job_review_readiness(
            self.repository, company_id=self.company_id, media_job=media,
        )
        self.assertEqual(repaired, second)
        self.assertEqual(before_ledger, self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100))
        self.assertEqual(before_account, self.repository.get_media_credit_account(company_id=self.company_id))
        self.assertEqual(1, len(self.repository.list_queue_jobs_for_task(company_id=self.company_id, task_id=media["task_id"])))

    @contextmanager
    def _released_media_http(self) -> Iterator[tuple[str, str]]:
        safe_root = Path(self.temp.name)
        with _temporary_safe_process_env(
            db_path=self.repository.db_path, runtime_db_path=safe_root / "runtime.sqlite", output_root=safe_root / "output",
        ), patch.dict(os.environ, {"JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "true"}):
            settings = SaaSSettings.from_env(
                db_path=self.repository.db_path, runtime_db_path=safe_root / "runtime.sqlite",
                output_root=safe_root / "output", host="127.0.0.1", port=0,
            )
            sessions = SessionManager(secret="released-media-repair-local-http-secret")

            class TestHandler(SaaSBackendHandler):
                def log_message(self, _format: str, *args: object) -> None:
                    return

            TestHandler.repository = self.repository
            TestHandler.settings = settings
            TestHandler.sessions = sessions
            TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
            TestHandler.queue_worker = self.worker
            server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_address[1]}", sessions.create_token(
                    user_id=self.user_id, company_id=self.company_id, email=self.email,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

    def test_released_retry_child_can_be_read_repaired_and_explicitly_retried_again(self) -> None:
        media = self._released_failed_media_job()
        with self._released_media_http() as (base, token):
            def get_media(media_id: str) -> dict[str, Any]:
                request = urllib.request.Request(
                    f"{base}/media-asset-jobs/{media_id}", headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.assertEqual(200, response.status)
                    return json.loads(response.read())["media_asset_job"]

            repaired = get_media(media["media_job_id"])
            self.assertEqual("needs_rework", repaired["status"])
            review_status, _ = _post_local(base, f"/media-asset-jobs/{media['media_job_id']}/review", {
                "decision": "approve_for_listing_draft",
                "confirmations": {"fact_consistency_confirmed": True, "commercial_rights_confirmed": True, "platform_rules_checked": True},
            }, token)
            self.assertEqual(422, review_status)
            request_body = {"reason": "explicit merchant retry", "run_mode": "queued"}
            status, response = _post_local(base, f"/media-asset-jobs/{media['media_job_id']}/retry", request_body, token)
            self.assertEqual(202, status, response)
            child = response["media_asset_job"]
            self.assertEqual(2, child["asset_version"]["version"])
            self.assertEqual("queued", child["status"])
            self.assertFalse(child["live_provider_called"])
            replay_status, replay = _post_local(base, f"/media-asset-jobs/{media['media_job_id']}/retry", request_body, token)
            self.assertEqual(202, replay_status, replay)
            self.assertEqual(child["media_job_id"], replay["media_asset_job"]["media_job_id"])
            queue = self.repository.get_queue_job(company_id=self.company_id, job_id=child["queue_job_id"])
            task = self.repository.get_task(company_id=self.company_id, task_id=child["task_id"])
            self.repository.update_media_asset_job(
                company_id=self.company_id, media_job_id=child["media_job_id"], status="provider_returned",
                provider_output=self._canonical_provider_output(inputs=queue["job"]["inputs"]),
            )
            self.worker._release_media_credit_reservation(task=task, job_body=queue["job"], reason="settlement_write_failed")
            self.repository.update_task_status(company_id=self.company_id, task_id=child["task_id"], status="failed")
            self.repository.update_queue_job(company_id=self.company_id, job_id=child["queue_job_id"], status="failed")
            reserve_id = queue["job"]["media_credits"]["reservation"]["ledger_entry"]["ledger_id"]
            for wrong_field in ("parent_media_job_id", "version"):
                with self.subTest(rework_association=wrong_field), closing(sqlite3.connect(self.repository.db_path)) as conn, conn:
                    original_json = conn.execute("select ledger_json from media_credit_ledger where ledger_id = ?", (reserve_id,)).fetchone()[0]
                    bad_payload = json.loads(original_json)
                    bad_payload["details"][wrong_field] = "unrelated"
                    conn.execute("update media_credit_ledger set ledger_json = ? where ledger_id = ?", (json.dumps(bad_payload), reserve_id))
                    conn.commit()
                    try:
                        self.assertEqual("provider_returned", get_media(child["media_job_id"])["status"])
                    finally:
                        conn.execute("update media_credit_ledger set ledger_json = ? where ledger_id = ?", (original_json, reserve_id))
            before = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            recovered_child = get_media(child["media_job_id"])
            self.assertEqual("needs_rework", recovered_child["status"])
            self.assertEqual(recovered_child, get_media(child["media_job_id"]))
            self.assertEqual(before, self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100))
            status, retried = _post_local(base, f"/media-asset-jobs/{child['media_job_id']}/retry", request_body, token)
            self.assertEqual(202, status, retried)
            self.assertEqual(3, retried["media_asset_job"]["asset_version"]["version"])
            self.assertFalse(retried["media_asset_job"]["live_provider_called"])

    def test_released_repair_rejects_active_or_mismatched_authority(self) -> None:
        cases = (
            "queue_queued", "queue_preparing", "queue_dispatch_uncertain", "task_queued", "task_running",
            "queue_media", "queue_reservation", "queue_key", "queue_provider", "queue_task", "task_store",
            "reserve_reference", "terminal_reference", "settled_terminal", "unreleased_reserve", "missing_terminal",
        )
        for case in cases:
            with self.subTest(case=case):
                media = self._released_failed_media_job()
                credits = media["job"]["job_spec"]["media_credits"]
                reservation_id = credits["reservation"]["ledger_entry"]["ledger_id"]
                queue = self.repository.get_queue_job(company_id=self.company_id, job_id=media["queue_job_id"])
                with closing(sqlite3.connect(self.repository.db_path)) as conn, conn:
                    if case.startswith("queue_") and case[6:] in {"queued", "preparing", "dispatch_uncertain"}:
                        conn.execute("update queue_jobs set status = ? where job_id = ?", (case[6:], media["queue_job_id"]))
                    elif case in {"task_queued", "task_running"}:
                        conn.execute("update tasks set status = ? where task_id = ?", (case[5:], media["task_id"]))
                    elif case in {"queue_media", "queue_reservation", "queue_key", "queue_provider"}:
                        queued = queue["job"]
                        if case == "queue_reservation":
                            queued["media_credits"]["reservation"]["ledger_entry"]["ledger_id"] = "unrelated-reservation"
                        else:
                            key = {"queue_media": "media_job_id", "queue_key": "idempotency_key", "queue_provider": "provider_job_key"}[case]
                            queued[key] = "unrelated"
                        conn.execute("update queue_jobs set job_json = ? where job_id = ?", (json.dumps(queued), media["queue_job_id"]))
                    elif case == "queue_task":
                        conn.execute("update queue_jobs set task_id = 'unrelated-task' where job_id = ?", (media["queue_job_id"],))
                    elif case == "task_store":
                        conn.execute("update tasks set store_id = 'unrelated-store' where task_id = ?", (media["task_id"],))
                    elif case == "reserve_reference":
                        conn.execute("update media_credit_ledger set reference_id = 'unrelated' where ledger_id = ?", (reservation_id,))
                    elif case == "terminal_reference":
                        conn.execute("update media_credit_ledger set reference_id = 'unrelated' where reservation_id = ?", (reservation_id,))
                    elif case == "settled_terminal":
                        conn.execute("update media_credit_ledger set operation_type = 'settle' where reservation_id = ?", (reservation_id,))
                    elif case == "unreleased_reserve":
                        conn.execute("update media_credit_ledger set status = 'reserved' where ledger_id = ?", (reservation_id,))
                    elif case == "missing_terminal":
                        conn.execute("delete from media_credit_ledger where reservation_id = ?", (reservation_id,))
                ledger = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
                # Direct repository interface must enforce the same boundary even
                # when the API's early terminal filter is not involved.
                repaired = self.repository.reconcile_released_media_asset_job(
                    company_id=self.company_id, media_job_id=media["media_job_id"],
                )
                self.assertEqual(media, repaired)
                self.assertEqual(ledger, self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100))

    def test_released_running_job_recovers_but_stale_reads_cannot_overwrite_new_states(self) -> None:
        media = self._released_failed_media_job(status="running")
        repaired = _reconcile_media_asset_job_review_readiness(self.repository, company_id=self.company_id, media_job=media)
        self.assertEqual("needs_rework", repaired["status"])
        for status in ("queued", "waiting_review", "approved_for_listing", "validation_failed"):
            with self.subTest(status=status):
                current = self.repository.update_media_asset_job(company_id=self.company_id, media_job_id=media["media_job_id"], status=status)
                self.assertEqual(current, _reconcile_media_asset_job_review_readiness(self.repository, company_id=self.company_id, media_job=media))
        self.assertIsNone(self.repository.reconcile_released_media_asset_job(company_id="unrelated-company", media_job_id=media["media_job_id"]))

    def test_released_repair_does_not_overwrite_a_queue_retry_committed_while_waiting_for_lock(self) -> None:
        media = self._released_failed_media_job()
        # Delay the read-repair at the real SQLite writer lock, not at a mocked
        # permission/ledger method. The competing task transition commits first.
        lock_requested, allow_lock, done = threading.Event(), threading.Event(), threading.Event()
        results: list[Any] = []
        errors: list[BaseException] = []
        real_connect = sqlite3.connect

        def observed_connection(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = real_connect(*args, **kwargs)

            def before_statement(statement: str) -> None:
                if statement.strip().lower() == "begin immediate":
                    lock_requested.set()
                    allow_lock.wait(10)

            connection.set_trace_callback(before_statement)
            return connection

        def repair() -> None:
            try:
                results.append(_reconcile_media_asset_job_review_readiness(self.repository, company_id=self.company_id, media_job=media))
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        with closing(sqlite3.connect(self.repository.db_path)) as conn, conn:
            # Observe only the real DB driver's lock request; all queries and
            # domain decisions remain real. No timing threshold is the oracle.
            with patch("jiejing_saas.repository.sqlite3.connect", side_effect=observed_connection):
                thread = threading.Thread(target=repair)
                thread.start()
                try:
                    self.assertTrue(lock_requested.wait(5))
                    conn.execute("begin immediate")
                    conn.execute("update tasks set status = 'queued' where task_id = ?", (media["task_id"],))
                    self.assertFalse(done.is_set())
                finally:
                    conn.commit()
                    allow_lock.set()
                    thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual([media], results)
        # The real retry API also creates another queue while leaving the old
        # failed queue untouched. That new queue alone must prevent recovery.
        self.repository.retry_queue_job(company_id=self.company_id, job_id=media["queue_job_id"], user_id=self.user_id)
        self.repository.update_task_status(company_id=self.company_id, task_id=media["task_id"], status="failed")
        self.assertEqual(media, _reconcile_media_asset_job_review_readiness(self.repository, company_id=self.company_id, media_job=media))

    def test_queue_setup_failure_at_every_stage_releases_once_and_never_leaves_claimable_work(self) -> None:
        failure_methods = (
            "create_task",
            "create_media_asset_job",
            "create_queue_job",
            "update_media_asset_job",
            "activate_prepared_queue_job",
        )
        for failure_method in failure_methods:
            with self.subTest(failure_method=failure_method):
                inputs = self._canonical_inputs()
                _task_stub, job_body = self._reservation(inputs=inputs)
                store = self.repository.create_store(
                    company_id=self.company_id,
                    user_id=self.user_id,
                    payload={"platform": "ebay", "store_name": f"setup-{failure_method}", "marketplace": "EBAY_US"},
                )
                credit_state = {
                    **job_body["media_credits"],
                    "enforcement_enabled": True,
                }
                creation_state: dict[str, Any] = {}
                with patch.object(self.repository, failure_method, side_effect=RuntimeError("injected setup failure")):
                    with self.assertRaisesRegex(RuntimeError, "injected setup failure"):
                        _create_provider_job_queue_records(
                            self.repository,
                            company_id=self.company_id,
                            store_id=store["store_id"],
                            user_id=self.user_id,
                            title="Injected queue setup failure",
                            provider_job_key="media.asset_generation",
                            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
                            contract_version="test-contract",
                            safe_inputs=inputs,
                            media_idempotency_key=job_body["idempotency_key"],
                            media_request_fingerprint=f"fingerprint-{failure_method}",
                            media_credit_state=credit_state,
                            is_media_provider_job=True,
                            secret_ref="",
                            run_mode="queued",
                            creation_state=creation_state,
                        )
                compensation = _compensate_provider_queue_creation_failure(
                    self.repository,
                    company_id=self.company_id,
                    user_id=self.user_id,
                    creation_state=creation_state,
                    media_credit_state=credit_state,
                    media_idempotency_key=job_body["idempotency_key"],
                )
                second_compensation = _compensate_provider_queue_creation_failure(
                    self.repository,
                    company_id=self.company_id,
                    user_id=self.user_id,
                    creation_state=creation_state,
                    media_credit_state=credit_state,
                    media_idempotency_key=job_body["idempotency_key"],
                )
                reservation_id = str(credit_state["reservation"]["ledger_entry"]["ledger_id"])
                terminal = self.repository.get_media_credit_terminal_for_reservation(
                    company_id=self.company_id,
                    reservation_id=reservation_id,
                )
                account = self.repository.get_media_credit_account(company_id=self.company_id)
                self.assertTrue(compensation.get("reservation_released"))
                self.assertTrue(second_compensation.get("reservation_released"))
                self.assertFalse(compensation.get("manual_reconcile_required"))
                self.assertEqual("release", terminal.get("operation_type"))
                self.assertEqual(0, account.get("reserved_points"))
                queue_job = creation_state.get("queue_job") if isinstance(creation_state.get("queue_job"), dict) else {}
                if queue_job.get("job_id"):
                    persisted_queue = self.repository.get_queue_job(
                        job_id=queue_job["job_id"],
                        company_id=self.company_id,
                    )
                    self.assertEqual("failed", persisted_queue.get("status"))
                    self.assertIsNone(
                        self.repository.claim_next_queue_job(
                            company_id=self.company_id,
                            job_id=queue_job["job_id"],
                        )
                    )

    def test_queue_dispatch_evidence_never_resurrects_a_fast_completed_worker_job(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "fast-dispatch-worker", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Fast dispatch worker state",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        prepared = self.repository.create_queue_job(
            company_id=self.company_id,
            task_id=task["task_id"],
            max_attempts=1,
            initial_status="preparing",
            publish=False,
            job_data={
                "kind": "provider_job",
                "queue_setup_protocol": "media_queue_saga_v1",
                "setup_committed": False,
            },
        )

        def publish_after_fast_completion(_record: dict[str, Any]) -> dict[str, Any]:
            claimed = self.repository.claim_next_queue_job(
                company_id=self.company_id,
                job_id=prepared["job_id"],
            )
            self.assertIsNotNone(claimed)
            self.repository.update_queue_job(
                job_id=prepared["job_id"],
                company_id=self.company_id,
                status="completed",
                details={"event": "fast_worker_completed"},
            )
            return {
                "status": "published",
                "required": True,
                "message_id": "test-fast-worker-message",
                "secret_exposed": False,
            }

        with patch(
            "jiejing_saas.redis_queue_runtime.publish_redis_queue_job_if_configured",
            side_effect=publish_after_fast_completion,
        ):
            activated = self.repository.activate_prepared_queue_job(
                job_id=prepared["job_id"],
                company_id=self.company_id,
            )

        persisted = self.repository.get_queue_job(
            job_id=prepared["job_id"],
            company_id=self.company_id,
        )
        self.assertEqual("completed", activated.get("status"))
        self.assertEqual("completed", persisted.get("status"))
        updates = persisted.get("job", {}).get("updates", [])
        self.assertTrue(any(item.get("queue_dispatch", {}).get("message_id") == "test-fast-worker-message" for item in updates))

    def test_direct_queue_publish_evidence_never_resurrects_a_fast_completed_job(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "direct-fast-dispatch", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Direct fast dispatch",
            input_data={"provider_job_key": "public_search.market_research"},
        )

        def publish_after_fast_completion(record: dict[str, Any]) -> dict[str, Any]:
            claimed = self.repository.claim_next_queue_job(
                company_id=self.company_id,
                job_id=str(record["job_id"]),
            )
            self.assertIsNotNone(claimed)
            self.repository.update_queue_job(
                job_id=str(record["job_id"]),
                company_id=self.company_id,
                status="completed",
                details={"event": "direct_fast_worker_completed"},
            )
            return {
                "status": "published",
                "required": True,
                "message_id": "test-direct-fast-worker-message",
                "secret_exposed": False,
            }

        with patch(
            "jiejing_saas.redis_queue_runtime.publish_redis_queue_job_if_configured",
            side_effect=publish_after_fast_completion,
        ):
            created = self.repository.create_queue_job(
                company_id=self.company_id,
                task_id=task["task_id"],
                max_attempts=1,
                job_data={"kind": "provider_job", "provider_job_key": "public_search.market_research"},
            )

        persisted = self.repository.get_queue_job(job_id=created["job_id"], company_id=self.company_id)
        self.assertEqual("completed", created.get("status"))
        self.assertEqual("completed", persisted.get("status"))
        updates = persisted.get("job", {}).get("updates", [])
        self.assertTrue(
            any(
                item.get("queue_dispatch", {}).get("message_id") == "test-direct-fast-worker-message"
                for item in updates
            )
        )

    def test_direct_queue_publish_timeout_is_quarantined_instead_of_failed(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "direct-dispatch-timeout", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Direct dispatch timeout",
            input_data={"provider_job_key": "public_search.market_research"},
        )
        published_record: dict[str, Any] = {}

        def timeout_after_unknown_publish(record: dict[str, Any]) -> dict[str, Any]:
            published_record.update(record)
            return {
                "status": "failed",
                "required": True,
                "error_type": "TimeoutError",
                "message": "publish result is unknown",
                "secret_exposed": False,
            }

        with patch(
            "jiejing_saas.redis_queue_runtime.publish_redis_queue_job_if_configured",
            side_effect=timeout_after_unknown_publish,
        ):
            with self.assertRaisesRegex(RuntimeError, "Redis queue dispatch failed"):
                self.repository.create_queue_job(
                    company_id=self.company_id,
                    task_id=task["task_id"],
                    max_attempts=1,
                    job_data={"kind": "provider_job", "provider_job_key": "public_search.market_research"},
                )

        persisted = self.repository.get_queue_job(
            job_id=str(published_record["job_id"]),
            company_id=self.company_id,
        )
        self.assertEqual("dispatch_uncertain", persisted.get("status"))
        self.assertIsNone(
            self.repository.claim_next_queue_job(
                company_id=self.company_id,
                job_id=str(published_record["job_id"]),
            )
        )

    def test_setup_compensation_never_releases_points_or_rewrites_a_running_queue(self) -> None:
        inputs = self._canonical_inputs()
        _task_stub, job_body = self._reservation(inputs=inputs)
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "running-compensation-gate", "marketplace": "EBAY_US"},
        )
        credit_state = {**job_body["media_credits"], "enforcement_enabled": True}
        creation_state: dict[str, Any] = {}
        task, media_job, queue_job = _create_provider_job_queue_records(
            self.repository,
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            title="Running compensation gate",
            provider_job_key="media.asset_generation",
            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
            contract_version="test-contract",
            safe_inputs=inputs,
            media_idempotency_key=job_body["idempotency_key"],
            media_request_fingerprint="running-compensation-fingerprint",
            media_credit_state=credit_state,
            is_media_provider_job=True,
            secret_ref="",
            run_mode="queued",
            creation_state=creation_state,
        )
        claimed = self.repository.claim_next_queue_job(
            company_id=self.company_id,
            job_id=queue_job["job_id"],
        )
        self.assertEqual("running", claimed.get("status"))

        compensation = _compensate_provider_queue_creation_failure(
            self.repository,
            company_id=self.company_id,
            user_id=self.user_id,
            creation_state=creation_state,
            media_credit_state=credit_state,
            media_idempotency_key=job_body["idempotency_key"],
        )

        reservation_id = str(credit_state["reservation"]["ledger_entry"]["ledger_id"])
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        persisted_queue = self.repository.get_queue_job(job_id=queue_job["job_id"], company_id=self.company_id)
        persisted_media = self.repository.get_media_asset_job(
            company_id=self.company_id,
            media_job_id=media_job["media_job_id"],
        )
        persisted_task = self.repository.get_task(company_id=self.company_id, task_id=task["task_id"])
        self.assertEqual("running", persisted_queue.get("status"))
        self.assertEqual("queued", persisted_media.get("status"))
        self.assertEqual("queued", persisted_task.get("status"))
        self.assertFalse(compensation.get("queue_disabled"))
        self.assertFalse(compensation.get("reservation_released"))
        self.assertTrue(compensation.get("manual_reconcile_required"))
        self.assertIsNone(
            self.repository.get_media_credit_terminal_for_reservation(
                company_id=self.company_id,
                reservation_id=reservation_id,
            )
        )
        self.assertEqual(CONTROLLED_POINTS, account.get("reserved_points"))

    def test_redis_publish_timeout_keeps_queue_nonclaimable_and_points_reserved_for_reconcile(self) -> None:
        inputs = self._canonical_inputs()
        _task_stub, job_body = self._reservation(inputs=inputs)
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "redis-timeout-reconcile", "marketplace": "EBAY_US"},
        )
        credit_state = {**job_body["media_credits"], "enforcement_enabled": True}
        creation_state: dict[str, Any] = {}
        uncertain_dispatch = {
            "status": "failed",
            "required": True,
            "error_type": "TimeoutError",
            "message": "publish result is unknown",
            "secret_exposed": False,
        }
        with patch(
            "jiejing_saas.redis_queue_runtime.publish_redis_queue_job_if_configured",
            return_value=uncertain_dispatch,
        ):
            with self.assertRaisesRegex(RuntimeError, "Redis queue dispatch failed"):
                _create_provider_job_queue_records(
                    self.repository,
                    company_id=self.company_id,
                    store_id=store["store_id"],
                    user_id=self.user_id,
                    title="Redis timeout reconcile",
                    provider_job_key="media.asset_generation",
                    contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
                    contract_version="test-contract",
                    safe_inputs=inputs,
                    media_idempotency_key=job_body["idempotency_key"],
                    media_request_fingerprint="redis-timeout-reconcile-fingerprint",
                    media_credit_state=credit_state,
                    is_media_provider_job=True,
                    secret_ref="",
                    run_mode="queued",
                    creation_state=creation_state,
                )

        compensation = _compensate_provider_queue_creation_failure(
            self.repository,
            company_id=self.company_id,
            user_id=self.user_id,
            creation_state=creation_state,
            media_credit_state=credit_state,
            media_idempotency_key=job_body["idempotency_key"],
        )
        queue_job = creation_state["queue_job"]
        persisted_queue = self.repository.get_queue_job(
            job_id=queue_job["job_id"],
            company_id=self.company_id,
        )
        reservation_id = str(credit_state["reservation"]["ledger_entry"]["ledger_id"])
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual("dispatch_uncertain", persisted_queue.get("status"))
        self.assertIsNone(
            self.repository.claim_next_queue_job(
                company_id=self.company_id,
                job_id=queue_job["job_id"],
            )
        )
        self.assertFalse(compensation.get("reservation_released"))
        self.assertTrue(compensation.get("manual_reconcile_required"))
        self.assertIsNone(
            self.repository.get_media_credit_terminal_for_reservation(
                company_id=self.company_id,
                reservation_id=reservation_id,
            )
        )
        self.assertEqual(CONTROLLED_POINTS, account.get("reserved_points"))

    def test_media_retry_setup_failure_uses_prepared_saga_and_releases_reservation(self) -> None:
        inputs = self._canonical_inputs()
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=CONTROLLED_POINTS,
            idempotency_key="retry-saga-grant-v1",
            reference_type="test_fixture",
            reference_id="retry-saga-grant",
            details={"credit_source": "purchased", "source_reference_id": "retry-saga-grant"},
        )
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "retry-saga", "marketplace": "EBAY_US"},
        )
        original_task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Retry saga original",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        original = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=original_task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key="retry-saga-original-v1",
            job_spec={
                "provider_job_key": "media.asset_generation",
                "contract_version": "test-contract",
                "inputs": inputs,
                "media_credits": None,
            },
            status="needs_rework",
        )
        safe_root = Path(self.temp.name)
        with _temporary_safe_process_env(
            db_path=safe_root / "retry-http.sqlite",
            runtime_db_path=safe_root / "retry-runtime.sqlite",
            output_root=safe_root / "retry-output",
        ):
            settings = SaaSSettings.from_env(
                db_path=safe_root / "retry-http.sqlite",
                runtime_db_path=safe_root / "retry-runtime.sqlite",
                output_root=safe_root / "retry-output",
                host="127.0.0.1",
                port=0,
            )
        sessions = SessionManager(secret="retry-saga-local-http-secret")

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

        TestHandler.repository = self.repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)
        TestHandler.queue_worker = self.worker
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = sessions.create_token(user_id=self.user_id, company_id=self.company_id, email=self.email)
        try:
            with patch.dict(
                os.environ,
                {
                    "JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "true",
                    "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false",
                    "JIEJING_QUEUE_PROVIDER": "local_worker",
                },
                clear=False,
            ), patch.object(
                self.repository,
                "activate_prepared_queue_job",
                side_effect=RuntimeError("injected retry activation failure"),
            ):
                status, response = _post_local(
                    f"http://127.0.0.1:{server.server_address[1]}",
                    f"/media-asset-jobs/{original['media_job_id']}/retry",
                    {"reason": "merchant requested a corrected image", "run_mode": "queued"},
                    token,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        retry_key = f"media-rework:{original['media_job_id']}:v2"
        child = self.repository.get_media_asset_job_by_idempotency(
            company_id=self.company_id,
            idempotency_key=retry_key,
        )
        child_queue = self.repository.get_queue_job(
            job_id=str(child.get("queue_job_id") or ""),
            company_id=self.company_id,
        ) if child and child.get("queue_job_id") else None
        reserve_entries = [
            entry
            for entry in self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
            if entry.get("operation_type") == "reserve" and entry.get("reference_id") == retry_key
        ]
        self.assertEqual(503, status, response)
        self.assertEqual("media_queue_setup_failed", response.get("failure_code"))
        self.assertIsNotNone(child)
        self.assertEqual("needs_rework", child.get("status"))
        self.assertIsNotNone(child_queue)
        self.assertEqual("failed", child_queue.get("status"))
        self.assertIsNone(
            self.repository.claim_next_queue_job(
                company_id=self.company_id,
                job_id=child_queue["job_id"],
            )
        )
        self.assertEqual(1, len(reserve_entries))
        terminal = self.repository.get_media_credit_terminal_for_reservation(
            company_id=self.company_id,
            reservation_id=str(reserve_entries[0]["ledger_id"]),
        )
        self.assertEqual("release", terminal.get("operation_type"))
        retry_reservation = self.repository.reserve_media_rework(
            company_id=self.company_id,
            parent_media_job_id=original["media_job_id"],
            version=2,
            idempotency_key=retry_key,
        )
        self.assertTrue(
            retry_reservation.get("acquired"),
            "a fail-closed retry must not leave a created rework lease pointing at the failed child",
        )
        self.repository.release_media_rework_reservation(
            company_id=self.company_id,
            parent_media_job_id=original["media_job_id"],
            version=2,
        )
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        self.assertEqual(0, account.get("reserved_points"))

    def test_preparing_queue_is_not_claimable_and_terminal_release_blocks_provider(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "prepared-queue-gate", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Prepared queue gate",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        prepared = self.repository.create_queue_job(
            company_id=self.company_id,
            task_id=task["task_id"],
            max_attempts=1,
            initial_status="preparing",
            publish=False,
            job_data={"kind": "provider_job", "setup_committed": False},
        )
        self.assertIsNone(
            self.repository.claim_next_queue_job(company_id=self.company_id, job_id=prepared["job_id"])
        )

        inputs = self._canonical_inputs()
        _task_stub, job_body = self._reservation(inputs=inputs)
        credit_state = {**job_body["media_credits"], "enforcement_enabled": True}
        creation_state: dict[str, Any] = {}
        task_record, _media_record, queue_record = _create_provider_job_queue_records(
            self.repository,
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            title="Terminal race gate",
            provider_job_key="media.asset_generation",
            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
            contract_version="test-contract",
            safe_inputs=inputs,
            media_idempotency_key=job_body["idempotency_key"],
            media_request_fingerprint="terminal-race-fingerprint",
            media_credit_state=credit_state,
            is_media_provider_job=True,
            secret_ref="",
            run_mode="queued",
            creation_state=creation_state,
        )
        reservation = credit_state["reservation"]["ledger_entry"]
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="release",
            points=int(reservation["points"]),
            idempotency_key=f"{reservation['ledger_id']}:terminal:v2",
            reference_type="media_job",
            reference_id=job_body["idempotency_key"],
            reservation_id=str(reservation["ledger_id"]),
            details={"reason": "injected_activation_race"},
        )
        claimed = self.repository.claim_next_queue_job(
            company_id=self.company_id,
            job_id=queue_record["job_id"],
        )
        self.assertIsNotNone(claimed)
        with patch.object(self.worker.provider_job_runner, "run") as provider_run:
            result = self.worker.run_claimed_job(claimed)
        provider_run.assert_not_called()
        self.assertEqual("failed", result.get("status"))
        self.assertEqual("failed", self.repository.get_task(company_id=self.company_id, task_id=task_record["task_id"]).get("status"))

    def test_missing_authoritative_reservation_blocks_provider_call(self) -> None:
        inputs = self._canonical_inputs()
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "missing-reservation-authority", "marketplace": "EBAY_US"},
        )
        credit_state = {
            "quote": {
                "estimated_points": CONTROLLED_POINTS,
                "points_per_image": 80,
                "image_count": 4,
                "generation_tier": "standard",
                "video_requested": False,
                "chargeable": True,
            },
            "enforcement_enabled": True,
            "reservation": {
                "ledger_entry": {
                    "ledger_id": "mcredit_nonexistent_authority",
                    "operation_type": "reserve",
                    "status": "reserved",
                    "points": CONTROLLED_POINTS,
                }
            },
        }
        creation_state: dict[str, Any] = {}
        task, _media_job, queue_job = _create_provider_job_queue_records(
            self.repository,
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            title="Missing reservation authority gate",
            provider_job_key="media.asset_generation",
            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
            contract_version="test-contract",
            safe_inputs=inputs,
            media_idempotency_key="missing-reservation-authority-probe-v1",
            media_request_fingerprint="missing-reservation-authority-fingerprint",
            media_credit_state=credit_state,
            is_media_provider_job=True,
            secret_ref="",
            run_mode="queued",
            creation_state=creation_state,
        )
        claimed = self.repository.claim_next_queue_job(
            company_id=self.company_id,
            job_id=queue_job["job_id"],
        )
        self.assertIsNotNone(claimed)
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=1)
        with patch.object(self.worker.provider_job_runner, "run", return_value=provider_output) as provider_run:
            result = self.worker.run_claimed_job(claimed)
        provider_run.assert_not_called()
        self.assertEqual("failed", result.get("status"))
        self.assertEqual(
            "failed",
            self.repository.get_task(company_id=self.company_id, task_id=task["task_id"]).get("status"),
        )

    def test_live_media_requires_credit_enforcement_before_provider_call(self) -> None:
        inputs = self._canonical_inputs()
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "credit-enforcement-gate", "marketplace": "EBAY_US"},
        )
        credit_state = {
            "quote": {
                "estimated_points": CONTROLLED_POINTS,
                "points_per_image": 80,
                "image_count": 4,
                "generation_tier": "standard",
                "video_requested": False,
                "chargeable": True,
            },
            "enforcement_enabled": False,
            "reservation": None,
        }
        creation_state: dict[str, Any] = {}
        task, _media_job, queue_job = _create_provider_job_queue_records(
            self.repository,
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            title="Credit enforcement gate",
            provider_job_key="media.asset_generation",
            contract={"provider_family": "media", "queue": "media", "max_attempts": 1},
            contract_version="test-contract",
            safe_inputs=inputs,
            media_idempotency_key="credit-enforcement-required-v1",
            media_request_fingerprint="credit-enforcement-required-fingerprint",
            media_credit_state=credit_state,
            is_media_provider_job=True,
            secret_ref="",
            run_mode="queued",
            creation_state=creation_state,
        )
        claimed = self.repository.claim_next_queue_job(
            company_id=self.company_id,
            job_id=queue_job["job_id"],
        )
        self.assertIsNotNone(claimed)
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=1)
        with patch.object(self.worker.provider_job_runner, "run", return_value=provider_output) as provider_run:
            result = self.worker.run_claimed_job(claimed)
        provider_run.assert_not_called()
        self.assertEqual("failed", result.get("status"))
        self.assertIn("media credit enforcement", str(result.get("error") or "").lower())
        self.assertEqual(
            "failed",
            self.repository.get_task(company_id=self.company_id, task_id=task["task_id"]).get("status"),
        )

    def test_reservation_authority_binds_tenant_points_reference_status_and_bucket(self) -> None:
        _task, job_body = self._reservation(inputs=self._canonical_inputs())
        reservation_id = self._reservation_id(job_body)
        reference_id = str(job_body["idempotency_key"])
        expected = {
            "company_id": self.company_id,
            "reservation_id": reservation_id,
            "expected_points": CONTROLLED_POINTS,
            "expected_reference_id": reference_id,
            "allowed_reference_types": ("media_job", "media_rework"),
        }
        authority = self.repository.get_media_credit_reservation_authority(**expected)
        self.assertTrue(authority.get("valid_for_provider"))
        self.assertTrue(authority.get("allocations"))

        mismatches = (
            ({**expected, "expected_points": CONTROLLED_POINTS - 1}, "reservation_points_mismatch"),
            ({**expected, "expected_reference_id": "another-media-job"}, "reservation_reference_mismatch"),
            ({**expected, "allowed_reference_types": ("billing_refund",)}, "reservation_reference_type_mismatch"),
        )
        for call, reason in mismatches:
            with self.subTest(reason=reason):
                blocked = self.repository.get_media_credit_reservation_authority(**call)
                self.assertFalse(blocked.get("valid_for_provider"))
                self.assertIn(reason, blocked.get("blocked_by", []))

        other = self.repository.create_user_with_company(
            email=f"authority-other-{id(self)}@example.test",
            password="local-test-password",
            company_name="Reservation authority other tenant",
        )
        tenant_blocked = self.repository.get_media_credit_reservation_authority(
            **{**expected, "company_id": other["company"]["company_id"]}
        )
        self.assertFalse(tenant_blocked.get("valid_for_provider"))
        self.assertIn("reservation_not_found", tenant_blocked.get("blocked_by", []))

        bucket_id = str(authority["allocations"][0]["bucket_id"])
        with self.repository._connect() as conn:
            conn.execute(
                "update media_credit_buckets set status = 'revoking' where company_id = ? and bucket_id = ?",
                (self.company_id, bucket_id),
            )
        bucket_blocked = self.repository.get_media_credit_reservation_authority(**expected)
        self.assertFalse(bucket_blocked.get("valid_for_provider"))
        self.assertIn("reservation_bucket_not_active", bucket_blocked.get("blocked_by", []))

        _terminal_task, terminal_job_body = self._reservation(inputs=self._canonical_inputs())
        terminal_reservation_id = self._reservation_id(terminal_job_body)
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="release",
            points=CONTROLLED_POINTS,
            idempotency_key=f"{terminal_reservation_id}:authority-terminal:v1",
            reference_type="media_job",
            reference_id=str(terminal_job_body["idempotency_key"]),
            reservation_id=terminal_reservation_id,
            details={"reason": "authority_status_contract"},
        )
        terminal_blocked = self.repository.get_media_credit_reservation_authority(
            company_id=self.company_id,
            reservation_id=terminal_reservation_id,
            expected_points=CONTROLLED_POINTS,
            expected_reference_id=str(terminal_job_body["idempotency_key"]),
            allowed_reference_types=("media_job", "media_rework"),
        )
        self.assertFalse(terminal_blocked.get("valid_for_provider"))
        self.assertIn("reservation_not_active", terminal_blocked.get("blocked_by", []))

    def test_duplicate_setup_loser_does_not_create_or_disable_the_winner_queue(self) -> None:
        inputs = self._canonical_inputs()
        _task_stub, job_body = self._reservation(inputs=inputs)
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "duplicate-setup-gate", "marketplace": "EBAY_US"},
        )
        credit_state = {**job_body["media_credits"], "enforcement_enabled": True}
        common = {
            "company_id": self.company_id,
            "store_id": store["store_id"],
            "user_id": self.user_id,
            "title": "Duplicate setup gate",
            "provider_job_key": "media.asset_generation",
            "contract": {"provider_family": "media", "queue": "media", "max_attempts": 1},
            "contract_version": "test-contract",
            "safe_inputs": inputs,
            "media_idempotency_key": job_body["idempotency_key"],
            "media_request_fingerprint": "duplicate-setup-fingerprint",
            "media_credit_state": credit_state,
            "is_media_provider_job": True,
            "secret_ref": "",
            "run_mode": "queued",
        }
        winner_state: dict[str, Any] = {}
        _winner_task, winner_media, winner_queue = _create_provider_job_queue_records(
            self.repository,
            **common,
            creation_state=winner_state,
        )
        loser_state: dict[str, Any] = {}
        with self.assertRaisesRegex(RuntimeError, "canonical media queue already exists"):
            _create_provider_job_queue_records(
                self.repository,
                **common,
                creation_state=loser_state,
            )
        self.assertNotIn("queue_job", loser_state)
        self.assertEqual(winner_media["media_job_id"], loser_state["canonical_media_asset_job"]["media_job_id"])
        persisted_winner = self.repository.get_queue_job(
            job_id=winner_queue["job_id"],
            company_id=self.company_id,
        )
        self.assertEqual("queued", persisted_winner.get("status"))
        reservation_id = str(credit_state["reservation"]["ledger_entry"]["ledger_id"])
        self.assertIsNone(
            self.repository.get_media_credit_terminal_for_reservation(
                company_id=self.company_id,
                reservation_id=reservation_id,
            )
        )

    def test_media_job_cannot_enter_review_when_credit_settlement_did_not_finish(self) -> None:
        inputs = self._canonical_inputs()
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "settlement-review-gate", "marketplace": "EBAY_US"},
        )
        task = self.repository.create_task(
            company_id=self.company_id,
            store_id=store["store_id"],
            user_id=self.user_id,
            task_type="provider_job",
            title="Settlement review gate",
            input_data={"provider_job_key": "media.asset_generation"},
        )
        media_job = self.repository.create_media_asset_job(
            company_id=self.company_id,
            store_id=store["store_id"],
            task_id=task["task_id"],
            user_id=self.user_id,
            provider_job_key="media.asset_generation",
            idempotency_key="settlement-review-gate-v1",
            job_spec={"inputs": inputs},
            status="running",
        )
        queue_job = self.repository.create_queue_job(
            company_id=self.company_id,
            task_id=task["task_id"],
            max_attempts=1,
            job_data={
                "kind": "provider_job",
                "provider_job_key": "media.asset_generation",
                "media_job_id": media_job["media_job_id"],
            },
        )
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        provider_returned = self.worker._complete_media_asset_job(
            task=task,
            job=queue_job,
            job_body=queue_job["job"],
            provider_output=provider_output,
            current=media_job,
            review_ready=False,
            settlement_final=False,
        )
        settlement_failed = self.worker._complete_media_asset_job(
            task=task,
            job=queue_job,
            job_body=queue_job["job"],
            provider_output=provider_output,
            current=provider_returned,
            review_ready=False,
            settlement_final=True,
        )
        self.assertEqual("provider_returned", provider_returned.get("status"))
        self.assertEqual("needs_rework", settlement_failed.get("status"))
        self.assertNotEqual("waiting_review", settlement_failed.get("status"))

    def test_media_job_completion_persistence_failure_is_not_swallowed(self) -> None:
        inputs = self._canonical_inputs()
        provider_output = self._canonical_provider_output(inputs=inputs, returned_images=1)
        task = {"company_id": self.company_id, "user_id": self.user_id}
        job = {"job_id": "job-persistence-failure"}
        job_body = {
            "provider_job_key": "media.asset_generation",
            "media_job_id": "media-job-persistence-failure",
        }
        with patch.object(self.repository, "update_media_asset_job", side_effect=RuntimeError("persistence unavailable")):
            with self.assertRaisesRegex(RuntimeError, "persistence unavailable"):
                self.worker._complete_media_asset_job(
                    task=task,
                    job=job,
                    job_body=job_body,
                    provider_output=provider_output,
                    current=None,
                    review_ready=False,
                    settlement_final=False,
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

    def test_partial_live_provider_settles_only_actual_assets_and_keeps_listing_blocked(self) -> None:
        inputs = self._canonical_inputs()
        task, job_body = self._reservation(inputs=inputs)
        provider_output = self._canonical_provider_output(
            inputs=inputs,
            returned_images=2,
            provider_status="partial_live_media_provider",
        )
        provider_output["missing_inputs"] = ["video_provider_no_asset_returned"]
        provider_output["usage"] = {
            "media_points": CONTROLLED_POINTS,
            "note": "provider reported the full requested batch despite returning only two assets",
        }
        packet = provider_output["output_packet"]
        self.assertEqual("manifest_ready", packet["asset_manifest_validation"]["status"])
        self.assertEqual("waiting_for_human_asset_review", packet["asset_review"]["status"])
        self.assertEqual(
            {"needs_review"},
            {str(item.get("status")) for item in packet["asset_review"]["review_gates"]},
        )
        self.assertTrue(
            all(
                asset.get("listing_use_status") == "not_ready_for_listing_until_review"
                for asset in packet["asset_manifest"]
            )
        )

        result = self.worker._settle_media_credit_reservation(
            task=task,
            job_body=job_body,
            provider_output=provider_output,
            live_provider_called=True,
        )
        account = self.repository.get_media_credit_account(company_id=self.company_id)
        terminal = self._terminal_entries(self._reservation_id(job_body))
        self.assertEqual("settled", result.get("status"))
        self.assertEqual(160, result.get("points"), "two returned images at 80 points must settle 160")
        self.assertEqual("successful_asset_count", result.get("points_source"))
        self.assertEqual(160, account.get("available_points"))
        self.assertEqual(0, account.get("reserved_points"))
        self.assertEqual(["settle"], [item.get("operation_type") for item in terminal])

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

    def test_conflicting_provider_callbacks_keep_the_first_terminal_outcome(self) -> None:
        inputs = self._canonical_inputs()
        success_output = self._canonical_provider_output(inputs=inputs, returned_images=2)
        blocked_output = self._canonical_provider_output(
            inputs=inputs,
            provider_status="blocked_provider_quota",
            returned_images=0,
            live_provider_called=False,
        )
        blocked_output["missing_inputs"] = ["media_provider_quota_blocked"]
        scenarios = (
            (
                "settle_then_blocked",
                success_output,
                True,
                blocked_output,
                False,
                "settled",
                "settle",
                160,
                "successful_asset_count",
            ),
            (
                "release_then_success",
                blocked_output,
                False,
                success_output,
                True,
                "released",
                "release",
                320,
                "full_reservation_release",
            ),
        )

        for (
            scenario,
            first_output,
            first_live,
            conflicting_output,
            conflicting_live,
            expected_status,
            expected_operation,
            expected_points,
            expected_points_source,
        ) in scenarios:
            with self.subTest(scenario=scenario):
                task, job_body = self._reservation(inputs=inputs)
                reservation_id = self._reservation_id(job_body)
                first = self.worker._settle_media_credit_reservation(
                    task=task,
                    job_body=job_body,
                    provider_output=first_output,
                    live_provider_called=first_live,
                )
                first_account = self.repository.get_media_credit_account(company_id=self.company_id)
                callback_error: Exception | None = None
                conflicting: dict[str, Any] = {}
                try:
                    candidate = self.worker._settle_media_credit_reservation(
                        task=task,
                        job_body=job_body,
                        provider_output=conflicting_output,
                        live_provider_called=conflicting_live,
                    )
                    conflicting = candidate if isinstance(candidate, dict) else {}
                except Exception as exc:  # pragma: no cover - missing behavior stays FAIL, never ERROR
                    callback_error = exc

                replay_account = self.repository.get_media_credit_account(company_id=self.company_id)
                terminal = self._terminal_entries(reservation_id)
                self.assertEqual(first_account, replay_account)
                self.assertEqual([expected_operation], [item.get("operation_type") for item in terminal])
                self.assertIsNone(
                    callback_error,
                    f"contradictory callback must resolve to the first terminal result: {type(callback_error).__name__ if callback_error else ''}",
                )
                self.assertEqual(expected_status, first.get("status"))
                self.assertEqual(expected_status, conflicting.get("status"))
                self.assertEqual(expected_points, first.get("points"))
                self.assertEqual(expected_points, conflicting.get("points"))
                self.assertEqual(expected_points_source, first.get("points_source"))
                self.assertEqual(expected_points_source, conflicting.get("points_source"))

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

    def test_source_allowlist_rejects_unknown_bucket_without_falling_back(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="source-allowlist-plan-v1",
            reference_type="billing_order",
            reference_id="source-allowlist-plan",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "source-allowlist-plan",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="source-allowlist-pack-v1",
            reference_type="billing_order",
            reference_id="source-allowlist-pack",
            details={"credit_source": "purchased", "source_reference_id": "source-allowlist-pack"},
        )
        before_ledger = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
        try:
            self.repository.reserve_media_credit_source(
                company_id=self.company_id,
                user_id=self.user_id,
                source_type="operator_bonus",
                source_reference_id="operator-selected-source",
                points=80,
                idempotency_key="unknown-source-must-not-reserve-v1",
                reference_type="media_job",
                reference_id="unknown-source-media-job",
            )
        except ValueError as exc:
            self.assertIn("unsupported media credit source", str(exc))
        else:
            self.fail("an unallowlisted source type must never reserve media points")
        after_ledger = self.repository.list_media_credit_ledger(company_id=self.company_id, limit=100)
        plan = self._bucket_evidence(source_reference_id="source-allowlist-plan") or {}
        purchased = self._bucket_evidence(source_reference_id="source-allowlist-pack") or {}
        self.assertEqual(before_ledger, after_ledger)
        self.assertEqual(0, plan.get("reserved_points"))
        self.assertEqual(0, purchased.get("reserved_points"))

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

    def test_revoked_controlled_acceptance_points_cannot_be_consumed_or_fall_back(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="revoked-control-plan-v1",
            reference_type="billing_order",
            reference_id="revoked-control-plan",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "revoked-control-plan",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=500,
            idempotency_key="revoked-control-pack-v1",
            reference_type="billing_order",
            reference_id="revoked-control-pack",
            details={"credit_source": "purchased", "source_reference_id": "revoked-control-pack"},
        )
        self._grant_raw_controlled_source(source_ref="revoked-acceptance-source")
        try:
            revoked = self.repository.revoke_media_credit_source(
                company_id=self.company_id,
                user_id=self.user_id,
                source_type=CONTROLLED_SOURCE,
                source_reference_id="revoked-acceptance-source",
                idempotency_key="revoke-controlled-acceptance-source-v1",
                reason="controlled acceptance window revoked",
            )
        except Exception as exc:
            self.fail(f"controlled acceptance source revocation is missing: {type(exc).__name__}: {exc}")
        self.assertEqual(CONTROLLED_POINTS, revoked.get("points_revoked"))
        self.assertFalse(revoked.get("duplicate_request"))
        try:
            self.repository.reserve_media_credit_source(
                company_id=self.company_id,
                user_id=self.user_id,
                source_type=CONTROLLED_SOURCE,
                source_reference_id="revoked-acceptance-source",
                points=80,
                idempotency_key="revoked-controlled-reserve-v1",
                reference_type="media_job",
                reference_id="revoked-controlled-media-job",
            )
        except ValueError as exc:
            self.assertNotIn("unsupported media credit source", str(exc))
        else:
            self.fail("revoked controlled acceptance points must be impossible to reserve")
        plan = self._bucket_evidence(source_reference_id="revoked-control-plan") or {}
        purchased = self._bucket_evidence(source_reference_id="revoked-control-pack") or {}
        controlled = self._bucket_evidence(source_reference_id="revoked-acceptance-source") or {}
        self.assertEqual("revoked", controlled.get("status"))
        self.assertEqual(0, controlled.get("remaining_points"))
        self.assertEqual(0, controlled.get("reserved_points"))
        self.assertEqual(0, plan.get("reserved_points"))
        self.assertEqual(0, purchased.get("reserved_points"))

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
        self.assertEqual(
            f"{CONTROLLED_SOURCE_REFERENCE_PREFIX}:{self.company_id}",
            first.get("source_reference_id"),
            "the service, not the operator, must derive one deterministic source reference per company",
        )
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

    def test_authenticated_live_media_is_blocked_when_credit_enforcement_is_disabled(self) -> None:
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "disabled-credit-enforcement", "marketplace": "EBAY_US"},
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
        sessions = SessionManager(secret="disabled-media-credit-enforcement-local-secret")

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
                    "JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "false",
                    "JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_ENABLED": "false",
                    "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true",
                },
                clear=False,
            ), patch("jiejing_saas.provider_job_runner.MediaGenerationAdapter.generate") as generate:
                status, body = _post_local(
                    base_url,
                    f"/stores/{store['store_id']}/provider-jobs/queue",
                    {
                        "provider_job_key": "media.asset_generation",
                        "idempotency_key": "disabled-credit-enforcement-http-v1",
                        "inputs": MediaSettlementContractTest._canonical_inputs(),
                        "run_mode": "local_worker_now",
                    },
                    token,
                )
            self.assertEqual(0, generate.call_count)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(HTTPStatus.SERVICE_UNAVAILABLE, status, body)
        self.assertEqual("media_credit_enforcement_required", body.get("failure_code"))
        self.assertFalse(body.get("provider_call_triggered"))
        self.assertFalse(body.get("triggers_real_charge"))
        self.assertEqual([], self.repository.list_media_asset_jobs(company_id=self.company_id, store_id=store["store_id"]))

    def test_authenticated_queue_with_expired_controlled_bucket_does_not_fall_back(self) -> None:
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="expired-http-plan-v1",
            reference_type="billing_order",
            reference_id="expired-http-plan",
            details={
                "credit_source": "plan_included",
                "source_reference_id": "expired-http-plan",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.repository.apply_media_credit_operation(
            company_id=self.company_id,
            user_id=self.user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="expired-http-pack-v1",
            reference_type="billing_order",
            reference_id="expired-http-pack",
            details={"credit_source": "purchased", "source_reference_id": "expired-http-pack"},
        )
        self._grant_raw_controlled_source(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            source_ref="expired-http-controlled",
        )
        store = self.repository.create_store(
            company_id=self.company_id,
            user_id=self.user_id,
            payload={"platform": "ebay", "store_name": "expired-controlled-http-store", "marketplace": "EBAY_US"},
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
        sessions = SessionManager(secret="expired-controlled-media-queue-local-secret")

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
            ):
                status, body = _post_local(
                    base_url,
                    f"/stores/{store['store_id']}/provider-jobs/queue",
                    {
                        "provider_job_key": "media.asset_generation",
                        "idempotency_key": "expired-controlled-http-media-v1",
                        "inputs": MediaSettlementContractTest._canonical_inputs(),
                        "run_mode": "queued",
                    },
                    token,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        expired = self._bucket_evidence(source_reference_id="expired-http-controlled") or {}
        plan = self._bucket_evidence(source_reference_id="expired-http-plan") or {}
        purchased = self._bucket_evidence(source_reference_id="expired-http-pack") or {}
        self.assertEqual(402, status, body)
        self.assertFalse(body.get("triggers_real_charge"))
        self.assertEqual(0, expired.get("reserved_points"))
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
                "/controlled-media-acceptance",
                "/api/controlled-media-acceptance",
                "/media-credits/controlled-acceptance",
                "/billing/media-points/controlled-acceptance",
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
