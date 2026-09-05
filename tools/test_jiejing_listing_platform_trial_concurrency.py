#!/usr/bin/env python3
"""Only one concurrent Listing request may consume the last platform trial slot."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402

OUT = ROOT / "output" / "jiejing-listing-platform-trial-concurrency" / "test"
SAAS_DB = OUT / "saas-listing-platform-trial-concurrency.sqlite"
RUNTIME_DB = OUT / "runtime-listing-platform-trial-concurrency.sqlite"


class BlockingListingModelHandler(BaseHTTPRequestHandler):
    """Hold the first model call open while the competing HTTP request runs."""

    calls: list[dict[str, Any]] = []
    calls_lock = threading.Lock()
    first_call_entered = threading.Event()
    release_first_call = threading.Event()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    @classmethod
    def reset(cls) -> None:
        with cls.calls_lock:
            cls.calls.clear()
        cls.first_call_entered.clear()
        cls.release_first_call.clear()

    @classmethod
    def call_count(cls) -> int:
        with cls.calls_lock:
            return len(cls.calls)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        with self.calls_lock:
            self.calls.append(
                {
                    "path": self.path,
                    # The provider needs authentication, but the test deliberately
                    # does not retain or print its value.
                    "authorization_present": bool(self.headers.get("authorization")),
                    "body": body,
                }
            )
            call_number = len(self.calls)

        if call_number == 1:
            self.first_call_entered.set()
            self.release_first_call.wait(timeout=25)

        listing = {
            "title": "Foldable Aluminum Alloy Tablet Stand for Desk Use",
            "selling_points": [
                "Foldable profile for compact storage",
                "Aluminum alloy construction",
                "Silicone contact pads",
                "Measures 15 x 12 x 8 cm",
                "Net weight is approximately 220 g",
            ],
            "description": (
                "A foldable aluminum alloy tablet stand with silicone contact pads. "
                "It measures 15 x 12 x 8 cm and weighs approximately 220 g."
            ),
            "category_suggestion": "Tablet and eBook Reader Stands",
            "keywords": ["tablet stand", "foldable stand", "desk stand"],
            "item_specifics": {
                "Type": "Tablet Stand",
                "Material": "Aluminum alloy with silicone pads",
            },
        }
        payload = {
            "choices": [
                {
                    "message": {"content": json.dumps(listing, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 90, "total_tokens": 210},
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def headers(*, token: str | None = None) -> dict[str, str]:
    result = {"content-type": "application/json", "accept": "application/json"}
    if token:
        result["authorization"] = f"Bearer {token}"
    return result


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers(token=token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_with_status(
    url: str,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    timeout: float = 35,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers(token=token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    status, response = post_json_with_status(url, payload, token=token)
    if status >= 400:
        raise RuntimeError(f"unexpected HTTP {status}: {response}")
    return response


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return True
        except Exception:
            time.sleep(0.2)
    return False


def listing_payload(project_key: str) -> dict[str, Any]:
    return {
        "listing_project_identity": {"key": project_key},
        "merchant_product_fact_packet": {
            "contract_version": "merchant_product_fact_packet_v1",
            "merchant_confirmed_facts": {
                "product_name": "Foldable Aluminum Alloy Tablet Stand",
                "condition": "NEW",
                "material": "Aluminum alloy with silicone pads",
                "product_dimensions_cm": "15 x 12 x 8",
                "net_weight_g": "220",
                "package_weight_g": "280",
                "package_length_cm": "18",
                "package_width_cm": "14",
                "package_height_cm": "5",
                "selling_price": "16.99",
                "currency": "USD",
                "quantity": "30",
            },
        },
        "current_draft_fields": {},
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    BlockingListingModelHandler.reset()

    model_server = ThreadingHTTPServer(("127.0.0.1", 0), BlockingListingModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()

    saas_port = free_port()
    platform_key = "unit-listing-concurrency-platform-key-not-returned"
    env = os.environ.copy()
    env["JIEJING_BILLING_PROVIDER"] = "stripe_test_mock"
    env["JIEJING_QUOTA_ENFORCEMENT_ENABLED"] = "1"
    env["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "1"
    env["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(OUT / "local-model-secrets.json")
    env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED"] = "1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER"] = "deepseek"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY"] = platform_key
    env["JIEJING_AI_CEO_PLATFORM_MODEL"] = "deepseek-v4-pro"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL"] = (
        f"http://127.0.0.1:{model_server.server_address[1]}/v1"
    )
    env["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = "1"

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
            str(saas_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    first_future = None
    try:
        base_url = f"http://127.0.0.1:{saas_port}"
        if not wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"saas backend did not become healthy: {stderr[-800:]}")

        auth = post_json(
            f"{base_url}/auth/register",
            {
                "email": "listing-platform-trial-concurrency@example.com",
                "password": "password123",
                "company_name": "Listing Platform Trial Concurrency Co",
            },
        )
        token = str(auth.get("token") or "")
        store = post_json(
            f"{base_url}/stores",
            {
                "platform": "ebay",
                "store_name": "Concurrent Listing Trial Store",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
            },
            token=token,
        ).get("store", {})
        store_id = str(store.get("store_id") or "")
        if not token or not store_id:
            return fail("registration and store creation must return usable identifiers")

        settings_before = fetch_json(f"{base_url}/stores/{store_id}/model/settings", token=token)
        quota_before = settings_before.get("model_settings", {}).get("platform_trial_quota", {})
        if (
            quota_before.get("monthly_limit") != 1
            or quota_before.get("used") != 0
            or quota_before.get("remaining") != 1
            or quota_before.get("allowed") is not True
        ):
            return fail(f"platform trial must begin with one available slot: {quota_before}")

        listing_url = f"{base_url}/stores/{store_id}/listing-drafts/generate"
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="listing-trial-race") as executor:
            first_future = executor.submit(
                post_json_with_status,
                listing_url,
                listing_payload("listing-platform-trial-concurrency-first"),
                token=token,
            )
            if not BlockingListingModelHandler.first_call_entered.wait(timeout=15):
                BlockingListingModelHandler.release_first_call.set()
                first_status, first_response = first_future.result(timeout=10)
                return fail(
                    "first Listing request never entered the fake provider: "
                    f"HTTP {first_status} {first_response}"
                )

            second_future = executor.submit(
                post_json_with_status,
                listing_url,
                listing_payload("listing-platform-trial-concurrency-second"),
                token=token,
            )
            try:
                second_status, second_response = second_future.result(timeout=15)
            except FutureTimeoutError:
                BlockingListingModelHandler.release_first_call.set()
                return fail("competing Listing request did not resolve while the first provider call was blocked")
            finally:
                BlockingListingModelHandler.release_first_call.set()

            first_status, first_response = first_future.result(timeout=20)

        if first_status != 201 or first_response.get("status") != "completed" or not first_response.get("report"):
            return fail(f"the reserved Listing request should complete with HTTP 201: {first_status} {first_response}")
        if second_status != 402:
            return fail(f"the competing Listing request should be rejected with HTTP 402: {second_status} {second_response}")
        if "platform_default_model_trial_exhausted" not in set(second_response.get("blocked_by") or []):
            return fail(f"the competing request should expose the trial exhaustion blocker: {second_response}")
        if (
            second_response.get("model_called") is not False
            or second_response.get("usage_consumed") is not False
            or second_response.get("report") is not None
        ):
            return fail(f"the rejected request must prove that no model usage or report occurred: {second_response}")
        if BlockingListingModelHandler.call_count() != 1:
            return fail(
                "exactly one concurrent request may enter the fake provider, got "
                f"{BlockingListingModelHandler.call_count()}"
            )

        tasks = fetch_json(f"{base_url}/tasks?store_id={store_id}&limit=30", token=token).get("tasks", [])
        listing_tasks = [item for item in tasks if item.get("task_type") == "listing_draft_generation"]
        reports = fetch_json(f"{base_url}/reports?limit=100", token=token).get("reports", [])
        listing_reports = [item for item in reports if item.get("report_type") == "listing.package"]
        settings_after = fetch_json(f"{base_url}/stores/{store_id}/model/settings", token=token)
        quota_after = settings_after.get("model_settings", {}).get("platform_trial_quota", {})
        if len(listing_tasks) != 1 or len(listing_reports) != 1:
            return fail(f"the rejected request must not create a task or report: {listing_tasks} {listing_reports}")
        if quota_after.get("used") != 1 or quota_after.get("remaining") != 0 or quota_after.get("allowed") is not False:
            return fail(f"the single reservation should exhaust exactly one trial slot: {quota_after}")

        billing_usage = fetch_json(f"{base_url}/billing/usage", token=token).get("billing_usage", {})
        quota_by_unit = {
            str(item.get("unit") or ""): item
            for item in billing_usage.get("quota_status") or []
            if isinstance(item, dict)
        }
        provider_quota = quota_by_unit.get("provider_job") or {}
        listing_quota = quota_by_unit.get("model_report_assist") or {}
        if provider_quota.get("used") != 1 or listing_quota.get("used") != 1:
            return fail(
                "merchant-visible Listing usage must share the enforced provider pool: "
                f"{provider_quota} {listing_quota}"
            )

        # Fill the remaining starter provider pool with local, secret-free task
        # records.  The next Listing request must hit the subscription 402
        # before either trial reservation or provider entry.
        company_id = str((auth.get("company") or {}).get("company_id") or "")
        user_id = str((auth.get("user") or {}).get("user_id") or "")
        provider_limit = int(provider_quota.get("limit") or 0)
        provider_used = int(provider_quota.get("used") or 0)
        repository = SaaSRepository(SAAS_DB)
        for index in range(max(0, provider_limit - provider_used)):
            repository.create_task(
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                task_type="provider_job",
                title=f"Subscription quota fixture {index + 1}",
                input_data={"fixture": "provider_quota", "secret_exposed": False},
            )
        subscription_status, subscription_response = post_json_with_status(
            listing_url,
            listing_payload("listing-subscription-quota-block"),
            token=token,
        )
        if subscription_status != 402:
            return fail(
                "subscription exhaustion should reject Listing generation with HTTP 402: "
                f"{subscription_status} {subscription_response}"
            )
        if (
            subscription_response.get("model_called") is not False
            or subscription_response.get("usage_consumed") is not False
            or subscription_response.get("report") is not None
            or "本次未调用模型" not in str(subscription_response.get("merchant_message") or "")
        ):
            return fail(f"subscription 402 must expose the safe Listing failure contract: {subscription_response}")
        if BlockingListingModelHandler.call_count() != 1:
            return fail("subscription quota rejection must not enter the fake provider")

        public_evidence = json.dumps(
            {
                "first_response": first_response,
                "second_response": second_response,
                "settings_before": settings_before,
                "settings_after": settings_after,
                "tasks": tasks,
                "reports": reports,
                "billing_usage": billing_usage,
                "subscription_response": subscription_response,
            },
            ensure_ascii=False,
        )
        if platform_key in public_evidence:
            return fail("platform provider secret leaked into an authenticated merchant response")
        if first_response.get("secret_exposed") is not False or second_response.get("secret_exposed") is not False:
            return fail("Listing responses must retain the explicit no-secret-exposure boundary")

        print("PASS jiejing_listing_platform_trial_concurrency")
        return 0
    finally:
        BlockingListingModelHandler.release_first_call.set()
        model_server.shutdown()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
