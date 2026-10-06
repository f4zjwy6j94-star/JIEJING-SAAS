#!/usr/bin/env python3
"""HTTP preflight for the project-scoped Listing AI endpoint."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-listing-draft-generation-api-test"
PORT = 8857
BASE = f"http://127.0.0.1:{PORT}"


def request(path: str, *, method: str = "GET", token: str = "", body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    except urllib.error.URLError:
        return 0, {}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "saas.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    for path in (db, runtime_db):
        if path.exists():
            path.unlink()
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(db),
            "--runtime-db",
            str(runtime_db),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            status, _ = request("/health")
            if status == 200:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("local server did not become healthy")
        _, registered = request(
            "/auth/register",
            method="POST",
            body={
                "email": "listing-generation-api@local.invalid",
                "password": "listing-generation-api-password",
                "company_name": "Listing Generation API",
            },
        )
        token = str(registered.get("token") or "")
        _, store_payload = request(
            "/stores",
            method="POST",
            token=token,
            body={"platform": "ebay", "store_name": "Listing API Store", "marketplace": "EBAY_US"},
        )
        store_id = store_payload["store"]["store_id"]
        secret_shape = "ghp_" + "S" * 30
        sensitive_packet = {
            "contract_version": "merchant_product_fact_packet_v1",
            "merchant_confirmed_facts": {
                "product_name": "Foldable Tablet Stand",
                "condition": "NEW",
                "material": f"Aluminum alloy {secret_shape}",
                "merchant_owned_product_confirmed": True,
            },
        }
        status, sensitive_facts = request(
            f"/stores/{store_id}/product-facts",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-sensitive-facts"},
                "merchant_product_fact_packet": sensitive_packet,
            },
        )
        if status != 422 or sensitive_facts.get("failure_code") != "listing_product_fact_sensitive_text":
            raise AssertionError(f"sensitive product facts were not rejected safely: {status} {sensitive_facts}")
        status, sensitive_generate = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-sensitive-generate"},
                "merchant_product_fact_packet": sensitive_packet,
                "current_draft_fields": {},
            },
        )
        if status != 422 or sensitive_generate.get("failure_code") != "listing_product_fact_sensitive_text":
            raise AssertionError(f"sensitive Listing packet was not blocked safely: {status} {sensitive_generate}")
        for sensitive_response in (sensitive_facts, sensitive_generate):
            if sensitive_response.get("model_called") is not False or sensitive_response.get("usage_consumed") is not False:
                raise AssertionError(f"sensitive packet claimed model usage: {sensitive_response}")
            if sensitive_response.get("report", "sentinel") is not None:
                raise AssertionError(f"sensitive packet claimed a persisted report: {sensitive_response}")
            if secret_shape.casefold() in json.dumps(sensitive_response, ensure_ascii=False).casefold():
                raise AssertionError("sensitive packet response echoed credential-shaped text")
        status, payload = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-blocked"},
                "merchant_product_fact_packet": {
                    "contract_version": "merchant_product_fact_packet_v1",
                    "merchant_confirmed_facts": {"product_name": "Unverified HTTP Product"},
                },
                "current_draft_fields": {},
                "api_key": "must-never-be-accepted-by-listing-endpoint",
            },
        )
        if status != 200 or payload.get("status") != "blocked":
            raise AssertionError(f"incomplete Listing HTTP preflight did not block safely: {status} {payload}")
        if payload.get("model_called") is not False or payload.get("usage_consumed") is not False:
            raise AssertionError(f"blocked Listing preflight claimed model usage: {payload}")
        if not {"condition", "material"}.issubset(set(payload.get("missing_fields") or [])):
            raise AssertionError(f"blocked Listing preflight did not name missing facts: {payload}")
        status, merchant_block = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-merchant-copy-blocked"},
                "merchant_product_fact_packet": {
                    "contract_version": "merchant_product_fact_packet_v1",
                    "merchant_confirmed_facts": {
                        "product_name": "Foldable Tablet Stand",
                        "condition": "NEW",
                        "material": "Aluminum alloy",
                    },
                },
                "current_draft_fields": {
                    "title": "商家手改的中文标题",
                    "description": "Merchant description",
                    "selling_points": ["Foldable", "Aluminum alloy", "Compact storage"],
                    "merchant_edited_fields": ["title", "description", "selling_points"],
                },
            },
        )
        if status != 200 or merchant_block.get("failure_code") != "listing_merchant_copy_marketplace_language":
            raise AssertionError(f"merchant copy was not blocked before model resolution: {status} {merchant_block}")
        if merchant_block.get("model_called") is not False or merchant_block.get("usage_consumed") is not False:
            raise AssertionError(f"merchant copy preflight consumed model usage: {merchant_block}")
        status, non_english_merchant_block = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-spanish-copy-blocked"},
                "merchant_product_fact_packet": {
                    "merchant_confirmed_facts": {
                        "product_name": "Foldable Tablet Stand",
                        "condition": "NEW",
                        "material": "Aluminum alloy",
                    },
                },
                "current_draft_fields": {
                    "title": "Soporte plegable para tableta",
                    "description": "Merchant description",
                    "selling_points": ["Foldable", "Aluminum alloy", "Compact storage"],
                    "merchant_edited_fields": ["title", "description", "selling_points"],
                },
            },
        )
        if status != 200 or non_english_merchant_block.get("failure_code") != "listing_merchant_copy_marketplace_language":
            raise AssertionError(f"non-English merchant copy reached model resolution: {status} {non_english_merchant_block}")
        if non_english_merchant_block.get("model_called") is not False:
            raise AssertionError(f"non-English merchant preflight called the model: {non_english_merchant_block}")
        status, ungrounded_merchant_block = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-ungrounded-merchant-copy"},
                "merchant_product_fact_packet": {
                    "merchant_confirmed_facts": {
                        "product_name": "Foldable Tablet Stand",
                        "condition": "NEW",
                        "material": "Aluminum alloy",
                    },
                },
                "current_draft_fields": {
                    "title": "Titanium Foldable Tablet Stand",
                    "description": "A compact aluminum alloy desk stand.",
                    "selling_points": ["Foldable profile", "Aluminum alloy body", "Compact storage"],
                    "merchant_edited_fields": ["title", "description", "selling_points"],
                },
            },
        )
        if status != 200 or ungrounded_merchant_block.get("failure_code") != "listing_merchant_copy_ungrounded_material":
            raise AssertionError(f"merchant grounding preflight did not block before quota: {status} {ungrounded_merchant_block}")
        if ungrounded_merchant_block.get("model_called") is not False or ungrounded_merchant_block.get("usage_consumed") is not False:
            raise AssertionError(f"merchant grounding preflight consumed model usage: {ungrounded_merchant_block}")
        _, reports = request("/reports?limit=100", token=token)
        _, tasks = request("/tasks?limit=100", token=token)
        if reports.get("reports"):
            raise AssertionError("blocked Listing HTTP preflight created a report")
        if tasks.get("tasks"):
            raise AssertionError("blocked Listing HTTP preflight created a task")
        with sqlite3.connect(db) as connection:
            reservation_count = connection.execute("select count(*) from platform_model_trial_reservations").fetchone()[0]
        if reservation_count != 0:
            raise AssertionError("blocked Listing HTTP preflight consumed a platform trial reservation")
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        if "must-never-be-accepted" in serialized:
            raise AssertionError("Listing HTTP response echoed a frontend credential")
        fact_body = {
            "listing_project_identity": {"key": "listing-project-http-tablet-save"},
            "merchant_product_fact_packet": {
                "source": "backend_product_vision_extraction",
                "source_mode": "merchant_images_supplied",
                "vision_contract_version": "jiejing_ai_ceo_product_vision_intake_v1",
                "field_evidence": {"material": {"image_indexes": [0], "confidence": 0.94}},
                "fact_conflicts": [{"field": "material", "values": ["Aluminum", "Plastic"], "reason": "image conflict"}],
                "source_records": [{"type": "merchant_product_image", "asset_id": "asset-tablet-image", "rights_status": "merchant_confirmed"}],
                "merchant_confirmed_facts": {
                    "product_name": "Foldable Tablet Stand",
                    "condition": "NEW",
                    "material": "Aluminum alloy",
                },
                "saved_at": "2026-09-01T00:00:00Z",
            },
        }
        def save_fact(body: dict[str, Any], target_store: str = store_id, auth: str = token):
            return request(f"/stores/{target_store}/product-facts", method="POST", token=auth, body=body)
        with ThreadPoolExecutor(max_workers=5) as pool:
            saved = list(pool.map(lambda _: save_fact(fact_body), range(5)))
        assert all(status in (200, 201) for status, _ in saved), saved
        assert len({item["task"]["task_id"] for _, item in saved}) == 1, "concurrent save duplicated tasks"
        assert len({item["report"]["report_id"] for _, item in saved}) == 1, "concurrent save duplicated reports"
        assert sum(item.get("idempotent_replay") is False for _, item in saved) == 1, saved
        first = saved[0][1]
        saved_packet = first["merchant_product_fact_packet"]
        assert saved_packet["source"] == "backend_product_vision_extraction"
        assert saved_packet["source_mode"] == "merchant_images_supplied"
        assert saved_packet["vision_contract_version"] == "jiejing_ai_ceo_product_vision_intake_v1"
        assert saved_packet["buyer_copy_requires_validated_listing_generation"] is True
        assert saved_packet["field_evidence"]["material"]["image_indexes"] == [0]
        assert saved_packet["fact_conflicts"][0]["field"] == "material"
        assert saved_packet["source_records"][0]["asset_id"] == "asset-tablet-image"
        assert saved_packet["source_records"][0]["rights_status"] == "pending_merchant_confirmation"
        assert saved_packet["source_confirmed_facts"] == {}
        fact_body["merchant_product_fact_packet"]["saved_at"] = "2026-09-05T00:00:00Z"
        _, replay = save_fact(fact_body)
        assert replay["task"]["task_id"] == first["task"]["task_id"], "save timestamp created a duplicate"
        assert replay["report"]["report_id"] == first["report"]["report_id"]
        assert replay["task"]["status"] == "completed"
        fact_body["merchant_product_fact_packet"]["merchant_confirmed_facts"]["material"] = "ABS plastic"
        _, revised = save_fact(fact_body)
        assert revised["task"]["task_id"] != first["task"]["task_id"], "changed facts failed to create a new version"
        assert revised["report"]["report_id"] != first["report"]["report_id"]
        fact_body["listing_project_identity"]["key"] = "listing-project-http-tablet-other"
        _, another_project = save_fact(fact_body)
        assert another_project["task"]["task_id"] != revised["task"]["task_id"], "project boundary collapsed"
        _, extra_store = request("/stores", method="POST", token=token, body={"platform": "ebay", "store_name": "Second Store", "marketplace": "EBAY_US"})
        _, another_store = save_fact(fact_body, extra_store["store"]["store_id"])
        assert another_store["task"]["task_id"] != another_project["task"]["task_id"], "store boundary collapsed"
        _, other_account = request("/auth/register", method="POST", body={"email": "listing-facts-other@local.invalid", "password": "listing-facts-other-password", "company_name": "Other Tenant"})
        forbidden_status, _ = save_fact(fact_body, store_id, other_account["token"])
        assert forbidden_status == 404, "another tenant accessed product facts"
        with sqlite3.connect(db) as connection:
            checkpoint_counts = [connection.execute(f"select count(*) from {table}").fetchone()[0] for table in ("tasks", "reports")]
        assert checkpoint_counts == [4, 4], checkpoint_counts
        api_source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
        for contract in (
            "except ListingDraftGenerationError as exc:",
            '"failure_code": exc.failure_code',
            '"usage_consumed": exc.usage_consumed',
            '"model_usage": exc.model_usage',
            '"report": None',
        ):
            if contract not in api_source:
                raise AssertionError(f"Listing quality failure HTTP contract is missing: {contract}")
        print("PASS jiejing_listing_draft_generation_api")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
