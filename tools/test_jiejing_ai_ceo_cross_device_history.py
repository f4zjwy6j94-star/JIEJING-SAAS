#!/usr/bin/env python3
"""Regression test for account-scoped AI CEO chat history sync."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-ai-ceo-cross-device-history" / "test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def headers(token: str | None = None) -> dict[str, str]:
    result = {"accept": "application/json", "content-type": "application/json"}
    if token:
        result["authorization"] = f"Bearer {token}"
    return result


def request_json(url: str, *, token: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers(token),
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            request_json(f"{base_url}/health")
            return True
        except Exception:
            time.sleep(0.2)
    return False


def register(base_url: str, email: str) -> str:
    payload = request_json(
        f"{base_url}/auth/register",
        payload={"email": email, "password": "password123", "company_name": f"History {email}"},
    )
    return str(payload.get("token") or "")


def create_store(base_url: str, token: str, name: str) -> str:
    payload = request_json(
        f"{base_url}/stores",
        token=token,
        payload={"platform": "ebay", "store_name": name, "marketplace": "EBAY_US", "stage": "store_opened"},
    )
    return str(payload.get("store", {}).get("store_id") or "")


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    for marker in (
        "const submittedAt = new Date(submittedAtMs).toISOString();",
        "created_at: submittedAt",
        "saasAiCeoThreadTurnByAssistantId",
    ):
        if marker not in app_js:
            return fail(f"frontend late-response ordering contract missing: {marker}")
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
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
        if not wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"backend did not become healthy: {stderr[-800:]}")

        account_a = register(base_url, "history-a@example.com")
        account_b = register(base_url, "history-b@example.com")
        if not account_a or not account_b:
            return fail("registration should return tokens")
        store_a1 = create_store(base_url, account_a, "History A One")
        store_a2 = create_store(base_url, account_a, "History A Two")
        if not store_a1 or not store_a2:
            return fail("account A should own two stores")

        raw_secret = "unit-test-history-secret-should-never-persist"
        synced = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-1",
                        "store_id": store_a1,
                        "listing_project_identity": {
                            "key": "listing-project-same-name-a",
                            "source_report_id": "report-same-name-a",
                            "candidate_id": "candidate-same-name-a",
                        },
                        "user_text": f"帮我选品 api_key={raw_secret}",
                        "assistant_text": "建议先研究便携式硅胶折叠水瓶。",
                        "status": "model_answered",
                        "route": "ebay_workflow",
                        "route_label": "eBay 工作流",
                        "created_at": "2026-07-11T01:00:00+00:00",
                        "source_records": [{"title": "Public source", "url": "https://example.com/product"}],
                    },
                    {
                        "assistant_id": "turn-cross-device-2",
                        "store_id": store_a2,
                        "listing_project_identity": {
                            "key": "listing-project-same-name-b",
                            "source_report_id": "report-same-name-b",
                            "candidate_id": "candidate-same-name-b",
                        },
                        "user_text": "再补充：不要带电。",
                        "assistant_text": "已把不带电作为筛选条件。",
                        "status": "model_answered",
                        "route": "general_chat",
                        "created_at": "2026-07-11T01:01:00+00:00",
                    },
                ]
            },
        )
        history = synced.get("ai_ceo_chat_history", {})
        if history.get("scope") != "account" or history.get("cross_store") is not True:
            return fail(f"history must be account scoped and cross-store: {history}")
        if len(history.get("turns", [])) != 2:
            return fail(f"sync should return two turns: {history}")
        if raw_secret in json.dumps(synced, ensure_ascii=False):
            return fail("chat history response must redact secret-like text")
        identities_by_turn = {
            item.get("assistant_id"): item.get("listing_project_identity")
            for item in history.get("turns", [])
        }
        if identities_by_turn.get("turn-cross-device-1") != {
            "key": "listing-project-same-name-a",
            "source_report_id": "report-same-name-a",
            "candidate_id": "candidate-same-name-a",
        }:
            return fail(f"project A chat identity was not retained exactly: {identities_by_turn}")
        if identities_by_turn.get("turn-cross-device-2") != {
            "key": "listing-project-same-name-b",
            "source_report_id": "report-same-name-b",
            "candidate_id": "candidate-same-name-b",
        }:
            return fail(f"same-name project B chat identity was mixed or lost: {identities_by_turn}")

        tablet_read = request_json(f"{base_url}/ai-ceo/chat-history?limit=30", token=account_a)
        tablet_history = tablet_read.get("ai_ceo_chat_history", {})
        tablet_turns = tablet_history.get("turns", [])
        tablet_revision = str(tablet_history.get("revision") or "")
        if not tablet_revision.startswith("chatrev_2_"):
            return fail(f"cross-device history should expose an account revision: {tablet_history}")
        if [turn.get("assistant_id") for turn in tablet_turns] != ["turn-cross-device-1", "turn-cross-device-2"]:
            return fail(f"same account should read ordered history across stores: {tablet_turns}")
        if tablet_turns[0].get("store_id") != store_a1 or tablet_turns[1].get("store_id") != store_a2:
            return fail("store context should be retained without scoping the account conversation")

        repeated = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={"turns": [tablet_turns[0]]},
        )
        if len(repeated.get("ai_ceo_chat_history", {}).get("turns", [])) != 2:
            return fail("replaying one device history must not duplicate a turn")

        desktop_update = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "base_revision": tablet_revision,
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-3",
                        "store_id": store_a1,
                        "user_text": "电脑端补充：重量小于 200 克。",
                        "assistant_text": "已加入重量限制。",
                        "status": "model_answered",
                        "route": "ebay_workflow",
                        "created_at": "2026-07-11T01:02:00+00:00",
                    }
                ],
            },
        )
        if desktop_update.get("ai_ceo_chat_history", {}).get("conflict_merged") is not False:
            return fail("up-to-date device sync should not be marked as a conflict")

        stale_tablet_update = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "base_revision": tablet_revision,
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-4",
                        "store_id": store_a2,
                        "user_text": "平板端补充：不要玻璃材质。",
                        "assistant_text": "已保留电脑端记录，并加入非玻璃限制。",
                        "status": "model_answered",
                        "route": "ebay_workflow",
                        "created_at": "2026-07-11T01:03:00+00:00",
                    }
                ],
            },
        )
        stale_history = stale_tablet_update.get("ai_ceo_chat_history", {})
        if stale_history.get("conflict_merged") is not True or len(stale_history.get("turns", [])) != 4:
            return fail(f"stale tablet revision should merge instead of overwriting desktop history: {stale_history}")

        poorer_same_turn = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "base_revision": stale_history.get("revision"),
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-1",
                        "store_id": store_a1,
                        "user_text": "帮我选品",
                        "assistant_text": "处理中",
                        "status": "streaming",
                        "route": "ebay_workflow",
                        "created_at": "2026-07-11T01:00:00+00:00",
                    }
                ],
            },
        )
        retained = poorer_same_turn.get("ai_ceo_chat_history", {}).get("turns", [])[0]
        if retained.get("assistant_text") != "建议先研究便携式硅胶折叠水瓶。":
            return fail(f"poorer stale copy must not overwrite the completed server turn: {retained}")

        initial_legacy_turn = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-legacy-enrich",
                        "store_id": store_a1,
                        "user_text": "继续当前商品",
                        "assistant_text": "完整回答应当保留，后续只能补项目身份，不能覆盖正文。",
                        "status": "model_answered",
                        "route": "ebay_workflow",
                        "created_at": "2026-07-11T01:04:00+00:00",
                    }
                ]
            },
        )
        enriched = request_json(
            f"{base_url}/ai-ceo/chat-history/sync",
            token=account_a,
            payload={
                "base_revision": initial_legacy_turn.get("ai_ceo_chat_history", {}).get("revision"),
                "turns": [
                    {
                        "assistant_id": "turn-cross-device-legacy-enrich",
                        "store_id": store_a1,
                        "listing_project_identity": {
                            "key": "listing-project-same-name-a",
                            "source_report_id": "report-same-name-a",
                            "candidate_id": "candidate-same-name-a",
                        },
                        "user_text": "继续当前商品",
                        "assistant_text": "短回复",
                        "status": "model_answered",
                        "route": "ebay_workflow",
                        "created_at": "2026-07-11T01:04:00+00:00",
                    }
                ],
            },
        )
        enriched_turn = next(
            item
            for item in enriched.get("ai_ceo_chat_history", {}).get("turns", [])
            if item.get("assistant_id") == "turn-cross-device-legacy-enrich"
        )
        if enriched_turn.get("assistant_text") != "完整回答应当保留，后续只能补项目身份，不能覆盖正文。":
            return fail("identity enrichment overwrote a better historical answer")
        if enriched_turn.get("listing_project_identity", {}).get("candidate_id") != "candidate-same-name-a":
            return fail("historical turn did not accept a non-conflicting exact project identity")

        isolated = request_json(f"{base_url}/ai-ceo/chat-history?limit=30", token=account_b)
        if isolated.get("ai_ceo_chat_history", {}).get("turns"):
            return fail("another account must not see account A chat history")

        try:
            request_json(f"{base_url}/ai-ceo/chat-history?limit=30")
        except urllib.error.HTTPError as error:
            if error.code != 401:
                return fail(f"unauthenticated history should return 401, got {error.code}")
        else:
            return fail("unauthenticated history must be rejected")

        print("PASS jiejing_ai_ceo_cross_device_history")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
