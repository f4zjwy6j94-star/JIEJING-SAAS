#!/usr/bin/env python3
"""Regression test for account-scoped AI CEO chat history sync."""

from __future__ import annotations

import json
import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter, placeholder_count
OUT = ROOT / "output" / "jiejing-ai-ceo-cross-device-history" / "test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"
ARCHIVE_HTTP_BOOTSTRAP = r'''
import runpy, sys, time
from jiejing_saas import api_server as api
class ArchiveFixtureModel:
    name = "archive_fixture_model"
    model = "archive-fixture"
    endpoint = ""
    def generate_text(self, **kwargs):
        time.sleep(0.15)
        answer = "毛利是销售收入减去商品的直接成本；净利还要扣除物流、平台费用、营销和其他经营成本。先明确口径，再用同一时间范围比较，避免把收入增长误认为利润增长。"
        callback = kwargs.get("on_text_delta")
        if callable(callback): callback(answer)
        return {"text": answer, "finish_reason": "stop", "model": self.model, "model_mode": "live_unit",
                "_usage": {"input_tokens": 21, "output_tokens": 53, "total_tokens": 74}}
def resolved(self, **kwargs):
    return {"status": "resolved", "mode": "account_byok", "provider_key": "archive_fixture",
            "secret_ref": "ref_archive_fixture", "secret_ref_scope": "account", "model": "archive-fixture",
            "merchant_pays_provider_directly": True, "jiejing_pays_provider_usage": False,
            "model_client": ArchiveFixtureModel(), "frontend_gets_model_api_key": False, "secret_exposed": False}
api.SaaSBackendHandler._resolve_model_client_for_store = resolved
api.SaaSBackendHandler._require_quota = lambda self, *args, **kwargs: True
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


class ChatHistoryRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-history-retention-", ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")

    def turn(self, index):
        return {
            "assistant_id": f"retained-turn-{index:03d}", "user_text": f"Question {index}",
            "assistant_text": f"Answer {index}", "status": "model_answered",
            "created_at": f"2026-09-05T00:{index // 60:02d}:{index % 60:02d}Z",
            "listing_project_identity": {"key": f"history-project-{index}",
                                         "source_report_id": "", "candidate_id": ""},
        }

    def sync(self, turns, **scope):
        return self.repository.sync_ai_ceo_chat_history(
            company_id=scope.get("company_id", "company-a"), user_id=scope.get("user_id", "user-a"), turns=turns,
        )

    def archive_claim(self, index=0, *, user_id="user-a"):
        return self.repository.claim_ai_ceo_chat_request(
            company_id="company-a", store_id="store-a", user_id=user_id,
            idempotency_key=f"archive-request-{index:03d}", payload_fingerprint="a" * 64,
            archive_context={"contract_version": "server_finalized_chat_archive_v1", "user_text": f"Question {index}"},
        )

    def archive_finalize(self, claim, *, answer="A finalized answer", status="completed", response_status=201):
        return self.repository.finalize_ai_ceo_chat_request(
            company_id="company-a", store_id="store-a", request_task_id=claim["request_task"]["task_id"],
            terminal_status=status, response_status=response_status,
            response_payload={"ai_ceo_chat": {"status": "model_answered" if status == "completed" else "model_call_failed", "answer": answer}},
        )

    def test_request_claim_and_replay_cannot_cross_users_in_one_company_store(self):
        claim = self.archive_claim()
        self.archive_finalize(claim)
        other_user = self.archive_claim(user_id="user-b")
        self.assertEqual(other_user["claim_state"], "conflict")
        self.assertNotIn("replay", other_user)
        self.assertNotIn("A finalized answer", json.dumps(other_user))
        self.assertNotIn(claim["request_task"]["task_id"], json.dumps(other_user))

    def test_expired_request_archives_unknown_outcome_and_rejects_late_success(self):
        with patch("jiejing_saas.repository.now_iso", return_value="2020-01-01T00:00:00+00:00"):
            claim = self.archive_claim()
        replay = self.archive_claim()
        self.assertEqual(replay["claim_state"], "replay")
        turns = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["status"], "request_reconciliation_required")
        late = self.archive_finalize(claim, answer="Late success must not replace the unknown terminal state")
        self.assertFalse(late["_idempotent_finalize_applied"])
        self.assertEqual(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a"), turns)

    def test_archive_failure_rolls_back_terminal_request_and_same_result_can_retry(self):
        claim = self.archive_claim()
        with self.repository._connect() as connection:
            connection.execute("create trigger reject_archive before insert on ai_ceo_chat_turns begin select raise(abort, 'fixture archive failure'); end")
        with self.assertRaises(sqlite3.IntegrityError):
            self.archive_finalize(claim)
        self.assertEqual(self.repository.get_task(company_id="company-a", task_id=claim["request_task"]["task_id"])["status"], "running")
        self.assertEqual(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a"), [])
        with self.repository._connect() as connection:
            connection.execute("drop trigger reject_archive")
        result = self.archive_finalize(claim)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")), 1)

    def test_concurrent_finalizers_and_browser_sync_keep_one_authoritative_turn(self):
        claim = self.archive_claim()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda answer: self.archive_finalize(claim, answer=answer), ("First complete answer", "Second complete answer is longer")))
        self.assertEqual(sum(bool(item["_idempotent_finalize_applied"]) for item in results), 1)
        winner = next(item for item in results if item["_idempotent_finalize_applied"])
        payload = winner["output"]["response_payload"]
        metadata = payload["ai_ceo_chat_history_turn"]
        turns = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant_text"], payload["ai_ceo_chat"]["answer"])
        self.assertEqual(turns[0]["assistant_id"], metadata["assistant_id"])
        self.sync([turns[0]])
        self.assertEqual(len(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")), 1)
        replay = self.archive_claim()
        self.assertEqual(replay["replay"]["response_payload"]["ai_ceo_chat_history_turn"], metadata)

    def test_legacy_requests_keep_sync_contract_and_failed_archives_keep_failure_status(self):
        legacy = self.repository.claim_ai_ceo_chat_request(
            company_id="company-a", store_id="store-a", user_id="user-a",
            idempotency_key="legacy-no-archive-contract", payload_fingerprint="b" * 64,
        )
        result = self.archive_finalize(legacy)
        self.assertNotIn("ai_ceo_chat_history_turn", result["output"]["response_payload"])
        self.assertEqual(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a"), [])
        claim = self.archive_claim()
        failed = self.archive_finalize(claim, answer="Provider was unavailable; no success claimed.", status="failed", response_status=503)
        self.assertEqual(failed["status"], "failed")
        turns = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["status"], "model_call_failed")

    def test_server_archive_accepts_postgres_native_request_and_history_rows(self):
        """Exercise finalization through the real SQL adapter with native PG row types."""
        claim = self.archive_claim()
        with self.repository._connect() as connection:
            native_task = dict(connection.execute("select * from tasks where task_id = ?", (claim["request_task"]["task_id"],)).fetchone())
        for key in ("input_json", "output_json"):
            native_task[key] = json.loads(native_task[key])
        for key in ("created_at", "updated_at"):
            native_task[key] = datetime.fromisoformat(native_task[key]).astimezone(timezone(timedelta(hours=8)))
        expected_created = native_task["created_at"].astimezone(timezone.utc)
        native_history = []
        queries = []
        testcase = self

        def json_value(value):
            value = getattr(value, "obj", value)
            return json.loads(value) if isinstance(value, str) else value

        class NativeCursor:
            rowcount = 0

            def execute(self, sql, params):
                testcase.assertEqual(placeholder_count(sql), len(params))
                queries.append(sql)
                self.rows = []
                if sql.startswith("select * from tasks"):
                    self.rows = [native_task]
                elif "select * from ai_ceo_chat_turns" in sql:
                    self.rows = native_history[:]
                elif "insert into ai_ceo_chat_turns" in sql:
                    native_history[:] = [{"chat_turn_id": params[0], "company_id": params[1], "user_id": params[2],
                        "store_id": params[3], "assistant_id": params[4], "status": params[5], "route": params[6],
                        "merge_score": params[7], "created_at": datetime.fromisoformat(params[8]),
                        "updated_at": datetime.fromisoformat(params[9]), "turn_json": json_value(params[10])}]
                    self.rowcount = 1
                elif "update tasks set status" in sql:
                    self.rowcount = int(native_task["status"] == "running")
                    if self.rowcount:
                        native_task.update(status=params[0], updated_at=datetime.fromisoformat(params[1]), output_json=json_value(params[2]))
                else:
                    testcase.fail(f"unexpected finalization SQL: {sql}")

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class NativeConnection:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def cursor(self): return NativeCursor()

        with patch.object(self.repository, "database_engine", "postgres"), \
             patch.object(self.repository, "_postgres_initialized", True), \
             patch.object(self.repository, "_connect", return_value=PostgresConnectionAdapter(NativeConnection())):
            result = self.archive_finalize(claim)
            duplicate = self.archive_finalize(claim, answer="Losing finalizer cannot replace native history")
        self.assertTrue(result["_idempotent_finalize_applied"])
        self.assertFalse(duplicate["_idempotent_finalize_applied"])
        self.assertEqual(len(native_history), 1)
        self.assertEqual(native_history[0]["created_at"], expected_created)
        self.assertEqual(native_history[0]["turn_json"]["assistant_text"], "A finalized answer")
        metadata = result["output"]["response_payload"]["ai_ceo_chat_history_turn"]
        self.assertEqual(datetime.fromisoformat(metadata["created_at"]), expected_created)
        self.assertEqual(sum("for update" in sql for sql in queries), 2)

    def test_server_finalized_answer_is_authoritative_over_browser_sync(self):
        claim = self.archive_claim()
        canonical = "ceo-server-" + hashlib.sha256(claim["request_task"]["task_id"].encode()).hexdigest()[:32]
        stale = {**self.turn(0), "assistant_id": canonical, "user_text": "Question 0",
            "assistant_text": "An earlier browser incorrectly thought the outcome was unknown. " * 20,
            "created_at": "2029-01-01T00:00:00Z", "status": "request_outcome_unknown"}
        self.sync([stale])
        self.archive_finalize(claim, answer="Actual server answer")
        actual = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["assistant_text"], "Actual server answer")
        self.assertEqual(datetime.fromisoformat(actual[0]["created_at"]), datetime.fromisoformat(claim["request_task"]["created_at"]))
        self.sync([{**stale, "assistant_text": stale["assistant_text"] * 2}])
        self.assertEqual(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a"), actual)

    def test_sync_read_before_finalization_cannot_overwrite_committed_archive(self):
        claim = self.archive_claim()
        canonical = "ceo-server-" + hashlib.sha256(claim["request_task"]["task_id"].encode()).hexdigest()[:32]
        stale = {**self.turn(0), "assistant_id": canonical, "user_text": "Question 0", "assistant_text": "Short placeholder"}
        self.sync([stale])
        original_connect = self.repository._connect
        testcase = self
        raced = []

        class FrozenCursor:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row

        class RacingConnection:
            def __init__(self): self.connection = original_connect()
            def __enter__(self): self.connection.__enter__(); return self
            def __exit__(self, *args): return self.connection.__exit__(*args)
            def __getattr__(self, name): return getattr(self.connection, name)
            def execute(self, sql, params=()):
                cursor = self.connection.execute(sql, params)
                if "select * from ai_ceo_chat_turns where company_id" in sql and not raced:
                    snapshot = cursor.fetchone()
                    raced.append(True)
                    with patch.object(testcase.repository, "_connect", original_connect):
                        testcase.archive_finalize(claim, answer="Authoritative final answer")
                    return FrozenCursor(snapshot)
                return cursor

        with patch.object(self.repository, "_connect", RacingConnection):
            self.sync([{**stale, "assistant_text": "Stale uncertain browser response is longer. " * 30}])
        self.assertEqual(raced, [True])
        turns = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant_text"], "Authoritative final answer")

    def test_fifty_first_turn_does_not_delete_the_first_project_conversation(self):
        self.sync([self.turn(0)])
        self.sync([self.turn(index) for index in range(1, 31)])
        self.sync([self.turn(index) for index in range(31, 51)])
        evidence = self.repository.list_merchant_project_evidence(
            company_id="company-a", user_id="user-a", store_id="store-a",
            project_id="history-project-0", evidence_cutoff="2030-01-01T00:00:00Z",
        )
        self.assertEqual([turn["assistant_id"] for turn in evidence["chat_turns"]], ["retained-turn-000"])
        self.assertTrue(self.repository.ai_ceo_chat_history_revision(
            company_id="company-a", user_id="user-a").startswith("chatrev_51_"))

    def test_keyset_pages_retrieve_all_retained_turns_without_replay_duplicates(self):
        for start in range(0, 71, 30):
            self.sync([self.turn(index) for index in range(start, min(start + 30, 71))])
        page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(page["turns"]), 30)
        self.assertTrue(page["has_more"])
        self.assertTrue(page["next_cursor"])
        seen = [item["assistant_id"] for item in page["turns"]]
        while page["has_more"]:
            page = self.repository.page_ai_ceo_chat_history(
                company_id="company-a", user_id="user-a", cursor=page["next_cursor"],
            )
            self.assertLessEqual(len(page["turns"]), 30)
            seen = [item["assistant_id"] for item in page["turns"]] + seen
        self.assertEqual(seen, [f"retained-turn-{index:03d}" for index in range(71)])
        self.assertEqual(page["next_cursor"], "")
        capped = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=1000)
        self.assertEqual(len(capped["turns"]), 50)

    def test_existing_turn_updates_keep_creation_anchor_and_timezone_ties_stable(self):
        turns = [{**self.turn(index), "created_at": (
            "2026-09-05T08:00:00.123456+08:00" if index % 2 else "2026-09-05T00:00:00.123456Z"
        )} for index in range(6)]
        self.sync(turns)
        original = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=2)
        oldest = original[0]
        old_revision = self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a")
        self.sync([{**oldest, "created_at": "2026-09-06T00:00:00Z", "assistant_text": "A longer, completed and corrected historical answer."}])
        updated = next(item for item in self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
                       if item["assistant_id"] == oldest["assistant_id"])
        self.assertEqual(updated["created_at"], oldest["created_at"])
        self.assertNotEqual(self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a"), old_revision)
        self.sync([{**self.turn(6), "created_at": "2026-09-07T00:00:00Z"}])
        seen = [item["assistant_id"] for item in page["turns"]]
        while page["has_more"]:
            page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=2, cursor=page["next_cursor"])
            seen = [item["assistant_id"] for item in page["turns"]] + seen
        self.assertEqual(seen, [item["assistant_id"] for item in original])

    def test_revision_reads_bounded_payloads_and_detects_an_early_turn_update(self):
        for start in range(0, 91, 30):
            self.sync([self.turn(index) for index in range(start, min(start + 30, 91))])
        real_connect = self.repository._connect
        payload_row_counts = []

        class ObservedCursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def fetchall(self):
                rows = self.cursor.fetchall()
                payload_row_counts.append(len(rows))
                return rows

        class ObservedConnection:
            def __init__(self):
                self.connection = real_connect()

            def __enter__(self):
                self.connection.__enter__()
                return self

            def __exit__(self, *args):
                return self.connection.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, sql, params=()):
                cursor = self.connection.execute(sql, params)
                return ObservedCursor(cursor) if "turn_json" in sql.lower() else cursor

        with patch.object(self.repository, "_connect", side_effect=ObservedConnection):
            before = self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a")
        self.assertTrue(payload_row_counts)
        self.assertLessEqual(max(payload_row_counts), 50)
        self.assertTrue(before.startswith("chatrev_91_"))
        self.sync([{**self.turn(0), "assistant_text": "An expanded completed historical answer, updated from another device."}])
        after = self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a")
        self.assertNotEqual(after, before)

    def test_invalid_or_utc_overflow_creation_times_do_not_break_sync(self):
        before = datetime.now(timezone.utc)
        for index, created_at in enumerate((
            "not-a-date", "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00",
        )):
            with self.subTest(created_at=created_at):
                self.sync([{**self.turn(index), "created_at": created_at}])
        after = datetime.now(timezone.utc)
        retained = self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")
        self.assertEqual(len(retained), 3)
        for turn in retained:
            instant = datetime.fromisoformat(turn["created_at"])
            self.assertGreaterEqual(instant, before)
            self.assertLessEqual(instant, after)

    def test_cursor_ownership_and_missing_payload_never_disclose_or_delete_history(self):
        self.sync([self.turn(index) for index in range(4)])
        page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=2)
        for company, user in (("company-b", "user-a"), ("company-a", "user-b")):
            self.assertEqual(self.repository.page_ai_ceo_chat_history(company_id=company, user_id=user)["turns"], [])
            with self.assertRaisesRegex(ValueError, "^invalid chat history cursor$"):
                self.repository.page_ai_ceo_chat_history(company_id=company, user_id=user, cursor=page["next_cursor"])
        for cursor in ("bad", "chatpage_v1_!", "chatpage_v1_eA", "x" * 301):
            with self.assertRaisesRegex(ValueError, "^invalid chat history cursor$"):
                self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", cursor=cursor)
        self.sync([])
        self.sync([self.turn(3)])
        self.assertEqual(len(self.repository.list_ai_ceo_chat_history(company_id="company-a", user_id="user-a")), 4)

    def test_postgres_native_datetime_jsonb_keyset_and_revision_contract(self):
        """Replay native rows through the real adapter; no PostgreSQL server is used."""
        self.sync([self.turn(index) for index in range(5)])
        expected_revision = self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a")
        with self.repository._connect() as connection:
            native_rows = [dict(row) for row in connection.execute("select * from ai_ceo_chat_turns").fetchall()]
        for row in native_rows:
            row["turn_json"] = json.loads(row["turn_json"])
            for key in ("created_at", "updated_at"):
                row[key] = datetime.fromisoformat(row[key].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=8)))
        testcase = self
        queries = []

        class NativeCursor:
            def execute(self, sql, params):
                testcase.assertEqual(placeholder_count(sql), len(params))
                testcase.assertNotIn("jiejing_evidence_time", sql)
                testcase.assertNotIn("offset ", sql.lower())
                testcase.assertIn("company_id = %s and user_id = %s", sql)
                queries.append(sql)
                scoped = [row for row in native_rows if (row["company_id"], row["user_id"]) == tuple(params[:2])]
                if "count(*)" in sql:
                    self.rows = [{"turn_count": len(scoped)}]
                elif "and chat_turn_id = %s" in sql:
                    self.rows = [row for row in scoped if row["chat_turn_id"] == params[2]]
                elif "order by updated_at" in sql:
                    self.rows = sorted(scoped, key=lambda row: (row["updated_at"], row["chat_turn_id"]), reverse=True)[:50]
                else:
                    if len(params) == 6:
                        anchor = (datetime.fromisoformat(params[2]), params[4])
                        scoped = [row for row in scoped if (row["created_at"], row["chat_turn_id"]) < anchor]
                    self.rows = sorted(scoped, key=lambda row: (row["created_at"], row["chat_turn_id"]), reverse=True)[:params[-1]]

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class NativeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return NativeCursor()

        with patch.object(self.repository, "database_engine", "postgres"), \
                patch.object(self.repository, "_postgres_initialized", True), \
                patch.object(self.repository, "_connect", return_value=PostgresConnectionAdapter(NativeConnection())):
            page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=2)
            seen = [turn["assistant_id"] for turn in page["turns"]]
            while page["has_more"]:
                page = self.repository.page_ai_ceo_chat_history(company_id="company-a", user_id="user-a", limit=2, cursor=page["next_cursor"])
                seen = [turn["assistant_id"] for turn in page["turns"]] + seen
            revision = self.repository.ai_ceo_chat_history_revision(company_id="company-a", user_id="user-a")
        self.assertEqual(seen, [f"retained-turn-{index:03d}" for index in range(5)])
        self.assertEqual(revision, expected_revision)
        self.assertEqual(len(queries), 7)


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
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ChatHistoryRetentionTest))
    if not result.wasSuccessful():
        return fail("chat history retention and pagination regressions failed")
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
            "-c", ARCHIVE_HTTP_BOOTSTRAP,
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
        env={**{key: value for key, value in os.environ.items() if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "PYTHONPATH",
        }}, "JIEJING_SAAS_ENV": "test", "JIEJING_NETWORK_DISABLED": "true",
             "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "0", "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": "0",
             "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false", "JIEJING_MEDIA_PROVIDER_LIVE_ENABLED": "false",
             "JIEJING_PUBLIC_CHARGING_ALLOWED": "false", "JIEJING_DATABASE_ENGINE": "sqlite"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if not wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"backend did not become healthy: {stderr[-800:]}")

        archive_account = register(base_url, "server-archive@example.com")
        archive_store = create_store(base_url, archive_account, "Server archive fixture")
        archive_responses = []
        for index in range(31):
            response = request_json(
                f"{base_url}/stores/{archive_store}/merchant-ceo/chat", token=archive_account,
                payload={"idempotency_key": f"server-archive-fixture-{index:03d}",
                         "message": f"当前时间，第{index}次",
                         "client_now": "2026-09-05T12:00:00+08:00", "client_timezone": "Asia/Shanghai",
                         "chat_archive_contract": "server_finalized_chat_archive_v1"},
            )
            if response.get("ai_ceo_chat", {}).get("status") != "local_clock_answered":
                return fail("archive fixture must use the zero-provider local clock route")
            archive_responses.append(response)
        archive_page = request_json(f"{base_url}/ai-ceo/chat-history", token=archive_account)["ai_ceo_chat_history"]
        archive_turns = list(archive_page["turns"])
        while archive_page.get("has_more"):
            archive_page = request_json(f"{base_url}/ai-ceo/chat-history?cursor={archive_page['next_cursor']}", token=archive_account)["ai_ceo_chat_history"]
            archive_turns = archive_page["turns"] + archive_turns
        if len(archive_turns) != 31 or archive_turns[0].get("user_text") != "当前时间，第0次":
            return fail(f"31 finalized server chats without browser SYNC must remain retrievable; got {len(archive_turns)}")
        metadata = archive_responses[0].get("ai_ceo_chat_history_turn", {})
        if metadata.get("assistant_id") != archive_turns[0]["assistant_id"] or metadata.get("archived") is not True:
            return fail("terminal HTTP response must expose the exact archived turn identity")
        replay_payload = {"idempotency_key": "server-archive-fixture-000", "message": "当前时间，第0次",
            "client_now": "2026-09-05T12:00:00+08:00", "client_timezone": "Asia/Shanghai",
            "chat_archive_contract": "server_finalized_chat_archive_v1"}
        replay = request_json(f"{base_url}/stores/{archive_store}/merchant-ceo/chat", token=archive_account, payload=replay_payload)
        if replay.get("idempotent_replay") is not True or replay.get("ai_ceo_chat_history_turn") != metadata:
            return fail("same frozen request must replay the same archive identity without a new model invocation")
        for contract, key, expected_status in (("unknown_protocol", "archive-invalid-contract", 400), ("", "server-archive-fixture-000", 409)):
            conflicting = {**replay_payload, "idempotency_key": key}
            if contract: conflicting["chat_archive_contract"] = contract
            else: conflicting.pop("chat_archive_contract")
            try:
                request_json(f"{base_url}/stores/{archive_store}/merchant-ceo/chat", token=archive_account, payload=conflicting)
                return fail("invalid or changed archive protocol was accepted")
            except urllib.error.HTTPError as error:
                if error.code != expected_status: return fail("archive protocol error lost its HTTP contract")
                rejected = error.read().decode("utf-8")
                if metadata["request_task_id"] in rejected or "当前时间，第0次" in rejected:
                    return fail("idempotency conflict leaked the original request details")
        legacy_payload = {**replay_payload, "idempotency_key": "archive-legacy-clock"}
        legacy_payload.pop("chat_archive_contract")
        legacy = request_json(f"{base_url}/stores/{archive_store}/merchant-ceo/chat", token=archive_account, payload=legacy_payload)
        if "ai_ceo_chat_history_turn" in legacy:
            return fail("old clients without opt-in must retain the original browser SYNC contract")
        sync_result = request_json(f"{base_url}/ai-ceo/chat-history/sync", token=archive_account, payload={"turns": archive_turns[-30:]})
        if not sync_result["ai_ceo_chat_history"]["revision"].startswith("chatrev_31_"):
            return fail("canonical browser sync or legacy clock request duplicated the server archive")

        streaming_body = {"idempotency_key": "archive-streamed-response", "message": "解释一下毛利和净利的区别。",
            "chat_archive_contract": "server_finalized_chat_archive_v1"}
        request = urllib.request.Request(f"{base_url}/stores/{archive_store}/merchant-ceo/chat?stream=1",
            data=json.dumps(streaming_body).encode(), headers=headers(archive_account), method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            if "ndjson" not in response.headers.get("content-type", ""):
                return fail("stream archive fixture did not exercise the actual NDJSON response path")
            events = [json.loads(line) for line in response.read().decode().splitlines() if line]
        if not any(event.get("type") == "delta" for event in events):
            return fail("controlled model did not emit an actual streamed delta")
        final = next(event["payload"] for event in events if event.get("type") == "final")
        streamed_id = final.get("ai_ceo_chat_history_turn", {}).get("assistant_id")
        stream_page = request_json(f"{base_url}/ai-ceo/chat-history", token=archive_account)["ai_ceo_chat_history"]
        if not streamed_id or streamed_id not in {turn["assistant_id"] for turn in stream_page["turns"]}:
            return fail("NDJSON final must already be durably archived before delivery")
        disconnected_body = json.dumps({**streaming_body, "idempotency_key": "archive-disconnected-response",
            "message": "我关闭页面后，请解释毛利和净利的区别。"}).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall((f"POST /stores/{archive_store}/merchant-ceo/chat?stream=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Authorization: Bearer {archive_account}\r\nContent-Type: application/json\r\nContent-Length: {len(disconnected_body)}\r\nConnection: close\r\n\r\n").encode() + disconnected_body)
            received = b""
            while b'"type": "accepted"' not in received and b'"type":"accepted"' not in received:
                chunk = connection.recv(4096)
                if not chunk: return fail("disconnect fixture did not reach accepted stream stage")
                received += chunk
        deadline = time.time() + 8
        while time.time() < deadline:
            retained = request_json(f"{base_url}/ai-ceo/chat-history", token=archive_account)["ai_ceo_chat_history"]
            if any(turn["user_text"].startswith("我关闭页面后") for turn in retained["turns"]): break
            time.sleep(0.05)
        else:
            return fail("closing the response stream after acceptance lost the completed server chat")

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

        for start in range(0, 71, 30):
            uploaded = request_json(
                f"{base_url}/ai-ceo/chat-history/sync", token=account_a,
                payload={"turns": [{
                    "assistant_id": f"paged-http-{index:03d}", "store_id": store_a1 if index % 2 else store_a2,
                    "user_text": f"Archived question {index}", "assistant_text": f"Archived answer {index}",
                    "status": "model_answered", "created_at": f"2026-09-05T00:{index // 60:02d}:{index % 60:02d}Z",
                } for index in range(start, min(start + 30, 71))]},
            )["ai_ceo_chat_history"]
        if uploaded.get("has_more") is not True or not uploaded.get("next_cursor") or len(uploaded["turns"]) != 30:
            return fail("sync must preserve old fields and expose the recent page cursor")
        page = request_json(f"{base_url}/ai-ceo/chat-history", token=account_a)["ai_ceo_chat_history"]
        foreign_cursor = str(page.get("next_cursor") or "")
        seen = [item["assistant_id"] for item in page["turns"]]
        while page.get("has_more"):
            page = request_json(f"{base_url}/ai-ceo/chat-history?cursor={page['next_cursor']}", token=account_a)["ai_ceo_chat_history"]
            if len(page["turns"]) > 30:
                return fail("default history page must remain bounded to 30 turns")
            seen = [item["assistant_id"] for item in page["turns"]] + seen
        if len(seen) != 76 or len(set(seen)) != 76 or "turn-cross-device-1" not in seen:
            return fail("HTTP pagination must retain and retrieve the earliest conversation without duplicates")
        if page.get("next_cursor") != "" or not str(page["revision"]).startswith("chatrev_76_"):
            return fail("the terminal page must expose a full-account revision and no next cursor")
        request_json(f"{base_url}/ai-ceo/chat-history/sync", token=account_a, payload={})
        empty_sync = request_json(f"{base_url}/ai-ceo/chat-history", token=account_a)["ai_ceo_chat_history"]
        if not str(empty_sync["revision"]).startswith("chatrev_76_"):
            return fail("missing sync turns must not delete the account archive")
        for token, cursor in ((account_b, foreign_cursor), (account_a, "malformed-cursor")):
            try:
                request_json(f"{base_url}/ai-ceo/chat-history?cursor={cursor}", token=token)
            except urllib.error.HTTPError as error:
                if error.code != 400:
                    return fail(f"invalid or foreign history cursor should return 400, got {error.code}")
                error_text = error.read().decode("utf-8")
                if "invalid chat history cursor" not in error_text or "Archived question" in error_text:
                    return fail("cursor rejection must be generic and not disclose other account content")
            else:
                return fail("invalid or foreign history cursor was accepted")

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
