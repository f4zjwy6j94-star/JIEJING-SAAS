#!/usr/bin/env python3
"""Smoke test for AI CEO command persistence through SaaS backend memory/audit."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-ceo-command" / "test"
SAAS_DB = OUT / "saas-ceo-command.sqlite"
RUNTIME_DB = OUT / "runtime-ceo-command.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return False
        except Exception:
            time.sleep(0.2)
    return True


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token=token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_headers(token=token), method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _headers(*, token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    port = 8798
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
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"saas backend did not become healthy: {stderr[-800:]}")

        auth = post_json(
            f"{base_url}/auth/register",
            {"email": "ceo-command@example.com", "password": "password123", "company_name": "CEO Command Co"},
        )
        token = str(auth.get("token") or "")
        if not token:
            return fail("registration should return a bearer token")

        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "CEO Command Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=token,
        ).get("store", {})
        store_id = str(store.get("store_id") or "")
        if not store_id:
            return fail("store creation should return a store_id")

        raw_secret = "unit-test-model-key-command-000000"
        created = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/commands",
            {
                "command": {
                    "id": "ceo-command-test",
                    "text": f"Build a listing and asset brief, api_key={raw_secret}",
                    "title": "Listing and asset brief",
                    "summary": "Route to Listing, media workshop, and confirmation center.",
                    "intent": "listing",
                    "status": "ready",
                    "status_label": "accepted",
                    "packet_id": "packet_test_6of6",
                    "source_label": "official_api",
                    "high_risk": True,
                    "routes": [
                        {"view": "product", "key": "listing", "label": "Listing", "note": "Draft eBay fields", "status": "ready"},
                        {"view": "media", "key": "assets", "label": "Media", "note": "Build asset brief", "status": "ready"},
                        {"view": "confirm", "key": "approval", "label": "Decision", "note": "Hold real writes", "status": "required"},
                    ],
                }
            },
            token=token,
        )
        serialized = json.dumps(created, ensure_ascii=False)
        if raw_secret in serialized or "sk-testsecretvalue" in serialized:
            return fail("AI CEO command response must redact raw model/API-key-like values")
        if created.get("command", {}).get("text", "").find("[redacted]") == -1:
            return fail("AI CEO command text should carry a redaction marker")
        if created.get("source_record", {}).get("source_type") != "merchant_ceo_command":
            return fail("AI CEO command should expose a merchant_ceo_command source record")
        if created.get("real_platform_writes_enabled") is not False:
            return fail("AI CEO command persistence must not enable platform writes")

        latest = fetch_json(f"{base_url}/stores/{store_id}/merchant-ceo/commands/latest", token=token)
        if latest.get("command", {}).get("id") != "ceo-command-test":
            return fail("latest AI CEO command endpoint should return the stored command")
        if raw_secret in json.dumps(latest, ensure_ascii=False):
            return fail("latest AI CEO command endpoint must not expose raw secret-like text")

        memory = fetch_json(f"{base_url}/merchant-memory?store_id={store_id}&memory_type=merchant_ceo_command&limit=5", token=token)
        memories = memory.get("merchant_memory", [])
        if len(memories) != 1:
            return fail("merchant memory should contain exactly one AI CEO command record")
        if memories[0].get("source_type") != "merchant_ceo_command":
            return fail("AI CEO command memory should use merchant_ceo_command source_type")

        transient = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/commands",
            {
                "command": {
                    "id": "ceo-command-transient-chat",
                    "text": "怎么写英文标题更自然",
                    "title": "普通咨询",
                    "summary": "Normal AI CEO consultation without long-term merchant memory.",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "direct_answer",
                    "routes": [],
                }
            },
            token=token,
        )
        if transient.get("memory_policy") != "transient_no_long_term_memory" or transient.get("merchant_memory_written") is not False:
            return fail(f"ordinary consultation should not write long-term merchant memory: {transient}")
        latest_transient = fetch_json(f"{base_url}/stores/{store_id}/merchant-ceo/commands/latest", token=token)
        if latest_transient.get("command", {}).get("id") != "ceo-command-transient-chat":
            return fail("latest AI CEO command endpoint should use the dedicated latest-command table")
        memory_after_transient = fetch_json(f"{base_url}/merchant-memory?store_id={store_id}&memory_type=merchant_ceo_command&limit=5", token=token)
        if len(memory_after_transient.get("merchant_memory", [])) != 1:
            return fail("ordinary consultation should not add merchant_ceo_command memory rows")

        rule = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/commands",
            {
                "command": {
                    "id": "ceo-command-rule-memory",
                    "text": "记住这个规则：利润低于 20% 不要发布",
                    "title": "利润底线规则",
                    "summary": "Explicit merchant rule memory.",
                    "intent": "rule",
                    "status": "ready",
                    "status_label": "remember_rule",
                    "routes": [],
                }
            },
            token=token,
        )
        if rule.get("memory_policy") != "merchant_rule" or rule.get("merchant_memory_written") is not True:
            return fail(f"explicit merchant rule should write merchant_rule memory: {rule}")
        rule_memory = fetch_json(f"{base_url}/merchant-memory?store_id={store_id}&memory_type=merchant_rule&limit=5", token=token)
        if len(rule_memory.get("merchant_memory", [])) != 1:
            return fail("explicit merchant rule should be stored under merchant_rule memory type")

        audit = fetch_json(f"{base_url}/audit-logs?limit=20", token=token)
        actions = {item.get("action_type") for item in audit.get("audit_logs", [])}
        if "merchant_ceo.command.recorded" not in actions:
            return fail("AI CEO command should write an audit event")

        print("PASS jiejing_saas_ceo_command_persistence")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
