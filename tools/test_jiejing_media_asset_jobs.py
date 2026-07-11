#!/usr/bin/env python3
"""Regression for provider-neutral media asset job records and idempotency."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-media-asset-jobs" / "test"
SAAS_DB = OUT / "saas-media-asset-jobs.sqlite"
RUNTIME_DB = OUT / "runtime-media-asset-jobs.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8794
    process_env = os.environ.copy()
    process_env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
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
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "mediaassetstore", "marketplace": "EBAY_US"},
            token=token,
        ).get("store", {})
        store_id = store.get("store_id")
        if not store_id:
            return fail("store should be created")

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
                    "reference_images": ["merchant_upload://reference-1"],
                    "target_marketplace_rules": {"platform": "ebay"},
                },
                "image_count": 2,
                "image_sizes": ["1:1", "4:5"],
                "scene_types": ["white_background", "detail_page"],
                "video_script": "15 second product demo script",
                "merchant_notes": f"Supplier note {hidden_note_credential}",
                "api_key": "UNIT-MEDIA-KEY-MUST-NOT-PERSIST",
            },
            "run_mode": "local_worker_now",
        }
        queued = post_json(f"{base_url}/stores/{store_id}/provider-jobs/queue", payload, token=token)
        if "UNIT-MEDIA-KEY-MUST-NOT-PERSIST" in json.dumps(queued, ensure_ascii=False):
            return fail("media asset job response leaked raw media API key")
        if hidden_note_credential in json.dumps(queued, ensure_ascii=False):
            return fail("media asset job response leaked a credential hidden in an ordinary notes field")
        media_job = queued.get("media_asset_job") if isinstance(queued.get("media_asset_job"), dict) else {}
        media_job_id = media_job.get("media_job_id")
        if not media_job_id:
            return fail(f"media provider job should create a media asset job: {queued}")
        if media_job.get("status") != "waiting_review":
            return fail(f"media asset job should wait for human asset review after dry-run: {media_job}")
        if media_job.get("live_provider_called") is not False or media_job.get("spend_now_allowed") is not False:
            return fail("media asset job must not call providers or allow spend")
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
        if fetched.get("media_job_id") != media_job_id or fetched.get("status") != "waiting_review":
            return fail(f"media asset job detail endpoint should return the completed media job: {fetched}")
        fetched_facts = fetched.get("job", {}).get("job_spec", {}).get("inputs", {}).get("product_facts", {})
        if fetched_facts.get("listing_project_key") != "listing-project-stainless-tumbler-001":
            return fail(f"media asset job must preserve its Listing project identity: {fetched_facts}")
        if hidden_note_credential in json.dumps(fetched, ensure_ascii=False):
            return fail("persisted media job leaked a credential hidden in an ordinary notes field")
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
        repository = SaaSRepository(SAAS_DB)
        company_id = str(registered.get("company", {}).get("company_id") or "")
        user_id = str(registered.get("user", {}).get("user_id") or "")
        current_provider_jobs = sum(
            1 for task in repository.list_tasks(company_id=company_id) if task.get("task_type") == "provider_job"
        )
        for index in range(current_provider_jobs, 300):
            repository.create_task(
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                task_type="provider_job",
                title=f"adversarial quota fixture {index}",
                input_data={"fixture": True, "index": index},
            )
        quota_status, quota_body = post_json_expect_error(
            f"{base_url}/media-asset-jobs/{media_v2_id}/retry",
            {"reason": "Attempt one more billable version after quota exhaustion."},
            token=token,
        )
        if quota_status != 402 or quota_body.get("error") != "quota exhausted":
            return fail(f"media rework must enforce provider-job quota: {quota_status}, {quota_body}")

        print("PASS jiejing_media_asset_jobs")
        print(f"media_job_id={media_job_id}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


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
