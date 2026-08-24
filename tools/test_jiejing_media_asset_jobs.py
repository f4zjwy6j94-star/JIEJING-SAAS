#!/usr/bin/env python3
"""Regression for provider-neutral media asset job records and idempotency."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.media_credits import estimate_media_points  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-media-asset-jobs" / "test"
SAAS_DB = OUT / "saas-media-asset-jobs.sqlite"
RUNTIME_DB = OUT / "runtime-media-asset-jobs.sqlite"


class FakeMediaProviderHandler(BaseHTTPRequestHandler):
    captured_payloads: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            self.__class__.captured_payloads.append(json.loads(raw_body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.__class__.captured_payloads.append({"invalid_payload": True})
        body = json.dumps(
            {
                "provider": "local-test-media-provider",
                "assets": [
                    {
                        "asset_id": "live-main-01",
                        "asset_type": "product_image",
                        "url": "https://cdn.example.test/media/live-main-01.jpg",
                        "dimensions": "1600x1600",
                        "status": "generated",
                    }
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8794
    provider_port = 8795
    provider_server = ThreadingHTTPServer(("127.0.0.1", provider_port), FakeMediaProviderHandler)
    provider_thread = Thread(target=provider_server.serve_forever, daemon=True)
    provider_thread.start()
    process_env = os.environ.copy()
    process_env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED": "1",
            "JIEJING_MEDIA_QUEUE_SETUP_STALE_AFTER_SECONDS": "30",
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "true",
            "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": "false",
            "JIEJING_IMAGE_GENERATION_ENDPOINT": f"http://127.0.0.1:{provider_port}/generate",
            "JIEJING_FAL_KEY": "unit-test-provider-credential",
            "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "false",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if wait_for_health(base_url):
            return fail("saas backend did not become healthy")
        registered = post_json(
            f"{base_url}/auth/register",
            {
                "email": "media-asset-job-owner@example.com",
                "password": "local-test-password",
                "company_name": "Media Asset Job Test Company",
            },
        )
        token = registered.get("token")
        if not token:
            return fail("registration should return token")
        repository = SaaSRepository(SAAS_DB)
        company_id = str(registered.get("company", {}).get("company_id") or "")
        user_id = str(registered.get("user", {}).get("user_id") or "")
        repository.apply_media_credit_operation(
            company_id=company_id,
            user_id=user_id,
            operation_type="grant",
            points=1000,
            idempotency_key="media-asset-job-test-credit-v1",
            reference_type="test_fixture",
            reference_id="media-asset-job-suite",
        )
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "mediaassetstore", "marketplace": "EBAY_US"},
            token=token,
        ).get("store", {})
        store_id = store.get("store_id")
        if not store_id:
            return fail("store should be created")

        source_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        source_asset = upload_media_source(
            f"{base_url}/stores/{store_id}/media-source-assets",
            source_png,
            token=token,
        ).get("media_source_asset", {})
        source_asset_id = str(source_asset.get("asset_id") or "")
        if not source_asset_id:
            return fail(f"grounded source upload should return an asset id: {source_asset}")
        legacy_signed_source_url = str(source_asset.get("source_url") or "")
        if "signature=" not in legacy_signed_source_url:
            return fail("source upload fixture should expose the legacy signed URL for persistence redaction coverage")

        hidden_note_credential = "sk-" + "unit-credential-should-not-persist-2026"
        payload = {
            "provider_job_key": "media.asset_generation",
            "title": "Provider-neutral media asset job",
            "idempotency_key": "unit-media-job-idempotency-001",
            "inputs": {
                "model_provider": "deepseek",
                "media_provider": "fal",
                "creative_job_spec": {
                    "job_type": "eBay_listing_asset_package",
                    "blocked_claims": ["unverified_certification"],
                },
                "product_facts": {
                    "product": "stainless steel tumbler",
                    "listing_project_key": "listing-project-stainless-tumbler-001",
                    "listing_draft_id": "listing-project-stainless-tumbler-001",
                    "supplier_facts": {
                        "material": "stainless steel",
                        "package_dimensions_cm": {"length": 10, "width": 10, "height": 18},
                    },
                    "allowed_claims": ["keeps drinks cold"],
                    "forbidden_claims": ["medical"],
                    "reference_images": [legacy_signed_source_url],
                    "source_asset_id": source_asset_id,
                    "source_image_sha256": source_asset.get("sha256"),
                    "target_marketplace_rules": {"platform": "ebay"},
                },
                "image_count": 2,
                "reference_image_url": legacy_signed_source_url,
                "image_sizes": ["1:1", "4:5"],
                "scene_types": ["white_background", "detail_page"],
                "video_script": "15 second product demo script",
                "live_provider_requested": True,
                "commercial_rights_confirmed": True,
                "merchant_notes": f"Supplier note {hidden_note_credential}",
                "api_key": "UNIT-MEDIA-KEY-MUST-NOT-PERSIST",
            },
            "run_mode": "local_worker_now",
        }
        # Reproduce a process exit immediately after reserve, before task/media/
        # queue persistence.  The same merchant key must recover locally and
        # continue with a new reservation attempt, without an extra provider call.
        orphan_quote = estimate_media_points(payload["inputs"])
        orphan_reservation = repository.apply_media_credit_operation(
            company_id=company_id,
            user_id=user_id,
            operation_type="reserve",
            points=int(orphan_quote["estimated_points"]),
            idempotency_key=f"{payload['idempotency_key']}:reserve:v1",
            reference_type="media_job",
            reference_id=str(payload["idempotency_key"]),
            details={"quote": orphan_quote},
        )
        orphan_reservation_id = str(orphan_reservation["ledger_entry"]["ledger_id"])
        with repository._connect() as conn:  # noqa: SLF001 - isolated crash fixture
            conn.execute(
                "update media_credit_ledger set created_at = ?, updated_at = ? where company_id = ? and ledger_id = ?",
                ("2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00", company_id, orphan_reservation_id),
            )
        queued = post_json(f"{base_url}/stores/{store_id}/provider-jobs/queue", payload, token=token)
        orphan_terminal = repository.get_media_credit_terminal_for_reservation(
            company_id=company_id,
            reservation_id=orphan_reservation_id,
        )
        active_reservation_id = str(
            queued.get("media_asset_job", {})
            .get("job", {})
            .get("job_spec", {})
            .get("media_credits", {})
            .get("reservation", {})
            .get("ledger_entry", {})
            .get("ledger_id", "")
        )
        if not orphan_terminal or orphan_terminal.get("operation_type") != "release":
            return fail(f"stale pre-persistence reservation was not safely released: {orphan_terminal}")
        if not active_reservation_id or active_reservation_id == orphan_reservation_id:
            return fail("same logical media key did not advance to a fresh reservation attempt")
        provider_payload = FakeMediaProviderHandler.captured_payloads[-1] if FakeMediaProviderHandler.captured_payloads else {}
        provider_references = provider_payload.get("image_urls") if isinstance(provider_payload.get("image_urls"), list) else []
        if len(provider_references) != 1 or not str(provider_references[0]).startswith("data:image/png;base64,"):
            return fail(f"worker must pass the private source image to FAL without a public callback URL: {provider_payload}")
        encoded_reference = str(provider_references[0]).split(",", 1)[1]
        if base64.b64decode(encoded_reference) != source_png:
            return fail("worker changed the uploaded merchant source image before the provider handoff")
        if "UNIT-MEDIA-KEY-MUST-NOT-PERSIST" in json.dumps(queued, ensure_ascii=False):
            return fail("media asset job response leaked raw media API key")
        if hidden_note_credential in json.dumps(queued, ensure_ascii=False):
            return fail("media asset job response leaked a credential hidden in an ordinary notes field")
        if re.search(r"\bfal\b", json.dumps(queued, ensure_ascii=False), flags=re.IGNORECASE):
            return fail("merchant media response must not expose the replaceable media provider")
        media_job = queued.get("media_asset_job") if isinstance(queued.get("media_asset_job"), dict) else {}
        media_job_id = media_job.get("media_job_id")
        if not media_job_id:
            return fail(f"media provider job should create a media asset job: {queued}")
        if media_job.get("status") != "waiting_review":
            return fail(f"live media asset job should wait for human review: {media_job}")
        if media_job.get("live_provider_called") is not True or media_job.get("spend_now_allowed") is not False:
            return fail("media asset job must record the live provider call without allowing platform writes")
        if media_job.get("secret_exposed") is not False:
            return fail("media asset job must keep secret_exposed=false")
        validation = media_job.get("asset_manifest_validation") if isinstance(media_job.get("asset_manifest_validation"), dict) else {}
        if validation.get("status") != "manifest_ready":
            return fail(f"media job should persist validator-ready AssetManifest: {validation}")
        review = media_job.get("asset_review") if isinstance(media_job.get("asset_review"), dict) else {}
        if review.get("listing_use_status") != "not_ready_for_listing_until_review":
            return fail("media assets must not become listing-ready before confirmation review")
        cost_guard = media_job.get("cost_guard") if isinstance(media_job.get("cost_guard"), dict) else {}
        if cost_guard.get("spend_now_allowed") is not False:
            return fail("media job cost guard must block spend")
        queue_job = queued.get("queue_job") if isinstance(queued.get("queue_job"), dict) else {}
        if queue_job.get("status") != "completed" or queue_job.get("job", {}).get("media_job_id") != media_job_id:
            return fail("queue job should be linked to the media asset job")

        fetched = fetch_json(f"{base_url}/media-asset-jobs/{media_job_id}", token=token).get("media_asset_job", {})
        persisted_media = json.dumps(fetched, ensure_ascii=False)
        if "data:image/" in persisted_media or "signature=" in persisted_media:
            return fail("media job persisted a private image body or signed provider fetch capability")
        if fetched.get("media_job_id") != media_job_id or fetched.get("status") != "waiting_review":
            return fail(f"media asset job detail endpoint should return the completed media job: {fetched}")
        fetched_facts = fetched.get("job", {}).get("job_spec", {}).get("inputs", {}).get("product_facts", {})
        if fetched_facts.get("listing_project_key") != "listing-project-stainless-tumbler-001":
            return fail(f"media asset job must preserve its Listing project identity: {fetched_facts}")
        if hidden_note_credential in json.dumps(fetched, ensure_ascii=False):
            return fail("persisted media job leaked a credential hidden in an ordinary notes field")
        if re.search(r"\bfal\b", json.dumps(fetched, ensure_ascii=False), flags=re.IGNORECASE):
            return fail("persisted media response must remain provider-neutral")
        store_list = fetch_json(f"{base_url}/stores/{store_id}/media-asset-jobs", token=token).get("media_asset_jobs", [])
        if len(store_list) != 1 or store_list[0].get("media_job_id") != media_job_id:
            return fail(f"store media job list should include exactly this media job: {store_list}")
        status_list = fetch_json(f"{base_url}/media-asset-jobs?status=waiting_review", token=token).get("media_asset_jobs", [])
        if len(status_list) != 1 or status_list[0].get("media_job_id") != media_job_id:
            return fail(f"status media job list should include exactly this media job: {status_list}")

        replay = post_json(f"{base_url}/stores/{store_id}/provider-jobs/queue", payload, token=token)
        replay_job = replay.get("media_asset_job") if isinstance(replay.get("media_asset_job"), dict) else {}
        if replay.get("idempotent_replay") is not True or replay_job.get("media_job_id") != media_job_id:
            return fail(f"same media idempotency key should return existing media job: {replay}")
        after_replay = fetch_json(f"{base_url}/stores/{store_id}/media-asset-jobs", token=token).get("media_asset_jobs", [])
        if len(after_replay) != 1:
            return fail(f"idempotent replay must not create a second media asset job: {after_replay}")

        provider_calls_before_conflict = len(FakeMediaProviderHandler.captured_payloads)
        changed_source_payload = json.loads(json.dumps(payload))
        changed_source_payload["inputs"]["product_facts"]["source_image_sha256"] = "f" * 64
        conflict_status, conflict = post_json_with_status(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            changed_source_payload,
            token=token,
        )
        if conflict_status != 409 or conflict.get("idempotency_conflict") is not True:
            return fail(f"a client-supplied key must not replay another source image: {conflict_status}, {conflict}")
        if len(FakeMediaProviderHandler.captured_payloads) != provider_calls_before_conflict:
            return fail("an idempotency/source conflict must be rejected before another provider call")

        credits_before_preflight_blocks = repository.get_media_credit_account(company_id=company_id).get("available_points")
        integrity_payload = json.loads(json.dumps(changed_source_payload))
        integrity_payload["idempotency_key"] = "unit-media-source-integrity-conflict-001"
        integrity_status, integrity_block = post_json_with_status(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            integrity_payload,
            token=token,
        )
        if integrity_status != 409 or integrity_block.get("source_integrity_conflict") is not True:
            return fail(f"a changed source digest must fail before reserve or provider execution: {integrity_status}, {integrity_block}")

        missing_claims_payload = json.loads(json.dumps(payload))
        missing_claims_payload["idempotency_key"] = "unit-media-missing-allowed-claims-001"
        missing_claims_payload["inputs"]["product_facts"]["allowed_claims"] = []
        claims_status, claims_block = post_json_with_status(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            missing_claims_payload,
            token=token,
        )
        if claims_status != 422 or "allowed_claims" not in claims_block.get("missing_inputs", []):
            return fail(f"missing allowed claims must fail before reserve or provider execution: {claims_status}, {claims_block}")
        credits_after_preflight_blocks = repository.get_media_credit_account(company_id=company_id).get("available_points")
        if credits_after_preflight_blocks != credits_before_preflight_blocks:
            return fail("source integrity or product-fact preflight failures must not reserve media points")
        if len(FakeMediaProviderHandler.captured_payloads) != provider_calls_before_conflict:
            return fail("source integrity or product-fact preflight failures must not call the provider")

        video_payload = json.loads(json.dumps(payload))
        video_payload["idempotency_key"] = "unit-media-job-unpriced-video-001"
        video_payload["inputs"]["video_generation_requested"] = True
        video_payload["inputs"]["video_duration_seconds"] = 10
        provider_calls_before_video = len(FakeMediaProviderHandler.captured_payloads)
        video_status, video_block = post_json_with_status(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            video_payload,
            token=token,
        )
        if video_status != 409 or video_block.get("media_quote", {}).get("chargeable") is not False:
            return fail(f"the frontend video flag must be blocked before an unpriced provider call: {video_status}, {video_block}")
        if len(FakeMediaProviderHandler.captured_payloads) != provider_calls_before_video:
            return fail("an unpriced video request must not reach the provider")

        no_credit_user = post_json(
            f"{base_url}/auth/register",
            {
                "email": "media-run-mode-reservation@example.com",
                "password": "local-test-password",
                "company_name": "Media Run Mode Reservation Test",
            },
        )
        no_credit_token = str(no_credit_user.get("token") or "")
        no_credit_store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "runmodegate", "marketplace": "EBAY_US"},
            token=no_credit_token,
        ).get("store", {})
        run_mode_payload = {
            "provider_job_key": "media.asset_generation",
            "idempotency_key": "unit-media-run-mode-reservation-001",
            "inputs": {
                "image_count": 1,
                "generation_tier": "standard",
                "creative_job_spec": {"blocked_claims": ["unverified_certification"]},
                "product_facts": {
                    "product": "unbranded cable organizer",
                    "supplier_facts": {"material": "silicone"},
                    "allowed_claims": ["merchant-confirmed silicone cable organizer"],
                    "forbidden_claims": ["medical"],
                    "reference_images": ["https://merchant-source.example.test/cable-organizer.png"],
                    "target_marketplace_rules": {"platform": "ebay", "marketplace": "EBAY_US"},
                },
                "commercial_rights_confirmed": True,
            },
            "run_mode": "live_provider_now",
        }
        run_mode_status, run_mode_block = post_json_with_status(
            f"{base_url}/stores/{no_credit_store.get('store_id')}/provider-jobs/queue",
            run_mode_payload,
            token=no_credit_token,
        )
        if run_mode_status != 402 or run_mode_block.get("triggers_real_charge") is not False:
            return fail(f"run_mode=live_provider_now must reserve points before queueing: {run_mode_status}, {run_mode_block}")

        rework_review = post_json(
            f"{base_url}/media-asset-jobs/{media_job_id}/review",
            {"decision": "needs_rework", "note": "Product color does not match the merchant reference."},
            token=token,
        ).get("media_asset_job", {})
        if rework_review.get("status") != "needs_rework":
            return fail(f"merchant should be able to mark a media version for rework: {rework_review}")
        if any(item.get("listing_use_status") != "needs_rework" for item in rework_review.get("asset_manifest", [])):
            return fail("rejected media assets must not remain eligible for Listing draft writeback")

        retry_payload = {
            "reason": "Correct product color and preserve the previous version.",
            "run_mode": "local_worker_now",
        }
        with ThreadPoolExecutor(max_workers=12) as executor:
            concurrent_retries = list(
                executor.map(
                    lambda _index: post_json_with_status(
                        f"{base_url}/media-asset-jobs/{media_job_id}/retry",
                        retry_payload,
                        token=token,
                    ),
                    range(12),
                )
            )
        unexpected_retry_statuses = [status for status, _body in concurrent_retries if status not in {200, 202}]
        if unexpected_retry_statuses:
            return fail(f"concurrent media retries must not fail or duplicate provider submission: {concurrent_retries}")
        concurrent_media_ids = {
            str(body.get("media_asset_job", {}).get("media_job_id") or "")
            for _status, body in concurrent_retries
            if isinstance(body, dict)
        }
        concurrent_media_ids.discard("")
        if len(concurrent_media_ids) != 1:
            return fail(f"concurrent media retries must resolve to one immutable version: {concurrent_media_ids}")
        retried = next(
            body
            for _status, body in concurrent_retries
            if str(body.get("media_asset_job", {}).get("media_job_id") or "")
        )
        concurrent_media_job_id = str(retried.get("media_asset_job", {}).get("media_job_id") or "")
        for _attempt in range(80):
            current_retry_job = fetch_json(
                f"{base_url}/media-asset-jobs/{concurrent_media_job_id}",
                token=token,
            ).get("media_asset_job", {})
            if current_retry_job.get("status") == "waiting_review":
                retried = {"media_asset_job": current_retry_job}
                break
            time.sleep(0.05)
        concurrent_versions = fetch_json(f"{base_url}/stores/{store_id}/media-asset-jobs", token=token).get("media_asset_jobs", [])
        if len(concurrent_versions) != 2:
            return fail(f"concurrent retry must create exactly one new media version: {concurrent_versions}")
        media_v2 = retried.get("media_asset_job") if isinstance(retried.get("media_asset_job"), dict) else {}
        media_v2_id = str(media_v2.get("media_job_id") or "")
        version = media_v2.get("asset_version") if isinstance(media_v2.get("asset_version"), dict) else {}
        if not media_v2_id or media_v2_id == media_job_id or media_v2.get("status") != "waiting_review":
            return fail(f"media rework should create and complete a separate reviewable version: {retried}")
        if version.get("version") != 2 or version.get("parent_media_job_id") != media_job_id:
            return fail(f"media rework must preserve immutable parent/version lineage: {version}")
        if version.get("root_media_job_id") != media_job_id:
            return fail(f"media rework should keep the original job as the version root: {version}")
        manifest_v2 = media_v2.get("asset_manifest") if isinstance(media_v2.get("asset_manifest"), list) else []
        if not manifest_v2 or any(item.get("asset_version") != 2 for item in manifest_v2):
            return fail(f"every v2 asset must carry its generated version: {manifest_v2}")
        cost_v2 = media_v2.get("cost_guard") if isinstance(media_v2.get("cost_guard"), dict) else {}
        if cost_v2.get("actual_cost_cents") is not None or cost_v2.get("merchant_charge_created") is not False:
            return fail(f"unknown provider usage must not be presented as an actual merchant charge: {cost_v2}")
        replay_v2 = post_json(f"{base_url}/media-asset-jobs/{media_job_id}/retry", retry_payload, token=token)
        if replay_v2.get("idempotent_replay") is not True or replay_v2.get("media_asset_job", {}).get("media_job_id") != media_v2_id:
            return fail(f"repeated v1 retry must return the same v2 instead of spending twice: {replay_v2}")
        replay_v2_with_changed_client_key = post_json(
            f"{base_url}/media-asset-jobs/{media_job_id}/retry",
            {**retry_payload, "idempotency_key": "attacker-controlled-new-key"},
            token=token,
        )
        if (
            replay_v2_with_changed_client_key.get("idempotent_replay") is not True
            or replay_v2_with_changed_client_key.get("media_asset_job", {}).get("media_job_id") != media_v2_id
        ):
            return fail(
                "changing a client-supplied retry key must not create another billable media version: "
                f"{replay_v2_with_changed_client_key}"
            )

        stale_status, stale_review = post_json_with_status(
            f"{base_url}/media-asset-jobs/{media_job_id}/review",
            {
                "decision": "approve_for_listing_draft",
                "fact_consistency_confirmed": True,
                "commercial_rights_confirmed": True,
                "platform_rules_checked": True,
            },
            token=token,
        )
        if stale_status != 422:
            return fail(f"a needs-rework version must never be approved through a stale review request: {stale_status}, {stale_review}")

        approved_v2 = post_json(
            f"{base_url}/media-asset-jobs/{media_v2_id}/review",
            {
                "decision": "approve_for_listing_draft",
                "fact_consistency_confirmed": True,
                "commercial_rights_confirmed": True,
                "platform_rules_checked": True,
            },
            token=token,
        ).get("media_asset_job", {})
        if approved_v2.get("status") != "approved_for_listing":
            return fail(f"v2 should become eligible only after all merchant confirmations: {approved_v2}")
        for item in approved_v2.get("asset_manifest", []):
            if item.get("fact_review_status") != "confirmed_by_merchant" or item.get("commercial_use_status") != "confirmed_by_merchant":
                return fail(f"approved asset should preserve fact and commercial-rights review evidence: {item}")
            if item.get("listing_use_status") != "approved_for_listing_draft":
                return fail(f"approved asset should be limited to Listing draft writeback: {item}")

        audit = fetch_json(f"{base_url}/audit-logs?limit=100", token=token).get("audit_logs", [])
        actions = {item.get("action_type") for item in audit}
        if "media.asset_job.created" not in actions or "media.asset_job.status_updated" not in actions:
            return fail(f"media asset job lifecycle should be audited: {actions}")

        needs_rework_again = post_json(
            f"{base_url}/media-asset-jobs/{media_v2_id}/review",
            {"decision": "needs_rework", "note": "Adversarial quota retry check."},
            token=token,
        ).get("media_asset_job", {})
        if needs_rework_again.get("status") != "needs_rework":
            return fail(f"approved media should be reviewable again before a new version: {needs_rework_again}")

        concept_payload = json.loads(json.dumps(payload))
        concept_payload["idempotency_key"] = "unit-media-job-concept-only-001"
        concept_payload["inputs"]["product_facts"]["reference_images"] = []
        concept_payload["inputs"]["creative_job_spec"]["output_safety_mode"] = "concept_reference_only"
        concept_job = post_json(f"{base_url}/stores/{store_id}/provider-jobs/queue", concept_payload, token=token).get("media_asset_job", {})
        concept_status, concept_review = post_json_with_status(
            f"{base_url}/media-asset-jobs/{concept_job.get('media_job_id')}/review",
            {
                "decision": "approve_for_listing_draft",
                "fact_consistency_confirmed": True,
                "commercial_rights_confirmed": True,
                "platform_rules_checked": True,
            },
            token=token,
        )
        if concept_status != 422 or "real product source image" not in str(concept_review.get("error") or ""):
            return fail(f"concept-only media review must fail closed before Listing writeback: {concept_status}, {concept_review}")

        provider_calls_before_missing_source = len(FakeMediaProviderHandler.captured_payloads)
        missing_source_payload = json.loads(json.dumps(payload))
        missing_source_payload["idempotency_key"] = "unit-media-job-missing-private-source-001"
        missing_source_payload["inputs"].pop("reference_image_url", None)
        missing_source_payload["inputs"]["product_facts"]["reference_images"] = []
        missing_source_payload["inputs"]["product_facts"]["source_asset_id"] = "media_src_aaaaaaaaaaaaaaaa"
        missing_source_status, missing_source = post_json_with_status(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            missing_source_payload,
            token=token,
        )
        if missing_source_status != 422 or "private_media_source_asset_not_found" not in missing_source.get("missing_inputs", []):
            return fail(f"missing private source must fail closed before queueing: {missing_source_status}, {missing_source}")
        if len(FakeMediaProviderHandler.captured_payloads) != provider_calls_before_missing_source:
            return fail("missing private source must not call or spend external media provider quota")

        media_account = repository.get_media_credit_account(company_id=company_id)
        available_points = int(media_account.get("available_points") or 0)
        if available_points:
            repository.apply_media_credit_operation(
                company_id=company_id,
                user_id=user_id,
                operation_type="reserve",
                points=available_points,
                idempotency_key="media-credit-exhaustion-fixture-v1",
                reference_type="test_fixture",
                reference_id="media-credit-exhaustion",
            )
        quota_status, quota_body = post_json_expect_error(
            f"{base_url}/media-asset-jobs/{media_v2_id}/retry",
            {"reason": "Attempt one more billable version after quota exhaustion."},
            token=token,
        )
        if quota_status != 402 or "素材点不足" not in str(quota_body.get("error") or ""):
            return fail(f"media rework must enforce media points before queueing: {quota_status}, {quota_body}")

        print("PASS jiejing_media_asset_jobs")
        print(f"media_job_id={media_job_id}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        provider_server.shutdown()
        provider_server.server_close()


def wait_for_health(base_url: str) -> int:
    for _ in range(60):
        try:
            health = fetch_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return 0
        except Exception:
            time.sleep(0.1)
    return 1


def fetch_json(url: str, token: str | None = None) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_media_source(url: str, content: bytes, *, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=content,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/png",
            "X-Jiejing-File-Name": "merchant-source.png",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_expect_error(url: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, post_json(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def post_json_with_status(url: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, post_json(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}
    except Exception as exc:
        return 599, {"error": exc.__class__.__name__}


if __name__ == "__main__":
    raise SystemExit(main())
