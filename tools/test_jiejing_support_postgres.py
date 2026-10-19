#!/usr/bin/env python3
"""Opt-in real, owned loopback PostgreSQL support regression. No existing DSN.

Requires existing PostgreSQL binaries and psycopg; never installs dependencies,
uses real accounts, connects to production or sends a message over the network.
The 006 migration is executed explicitly only inside these owned test databases;
its inclusion in the release manifest does not authorize production DDL.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Barrier, Event, Lock, current_thread
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "jiejing_saas/migrations/006_support_conversations_postgres.sql"
MIGRATION_ID = "20261012_006_support_conversations_postgres"
TABLES = ("support_messages_v1", "support_sync_v1", "support_drafts_v1", "support_send_intents_v1")
RUN: Path
ADMIN_DSN: str
psycopg = None


class SupportPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = "support_test_" + uuid.uuid4().hex[:16]
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("create database {}").format(psycopg.sql.Identifier(self.database)))
        self.dsn = ADMIN_DSN.rsplit("/", 1)[0] + "/" + self.database
        from jiejing_saas.infrastructure_drivers import run_postgres_migration
        self.migrate = lambda: run_postgres_migration(database_url=self.dsn, migration_path=MIGRATION)
        self.assertEqual(run_postgres_migration(database_url=self.dsn)["status"], "ok")
        self.assertTrue(MIGRATION.is_file(), "reviewed 006 support migration is missing")
        self.assertEqual(self.migrate()["status"], "ok")
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.ebay_message_adapter import MessageScope
        from jiejing_saas.support_conversations import SupportConversations
        self.repo = SaaSRepository(RUN / "unused.sqlite", database_engine="postgres", database_url=self.dsn)
        account = self.repo.create_user_with_company(email="support@example.test", password="local-synthetic-only",
                                                     company_name="Synthetic PG Support")
        self.company = account["company"]["company_id"]
        self.user = account["user"]["user_id"]
        store = self.repo.create_store(company_id=self.company, user_id=self.user, payload={"platform": "ebay"})
        self.scope = MessageScope(self.company, store["store_id"], "synthetic-seller")
        self.service = SupportConversations(self.repo, self.scope)
        self.incoming = {"status": "ok", "scope": self.scope.as_dict(), "conversation_id": "conv-pg",
                         "truncated": False, "messages": [{"messageId": "m-pg", "messageBody": "What colour?",
                         "senderUsername": "synthetic-buyer", "recipientUsername": "synthetic-seller",
                         "createdDate": "2026-10-12T00:00:00Z"}]}
        self.calls = []
        self.calls_lock = Lock()

    def tearDown(self):
        from jiejing_saas.postgres_repository_runtime import close_postgres_pools
        close_postgres_pools()

    def independent(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.support_conversations import SupportConversations
        repo = SaaSRepository(RUN / "unused.sqlite", database_engine="postgres", database_url=self.dsn)
        return SupportConversations(repo, self.scope)

    def draft(self):
        self.service.ingest(self.incoming)
        return self.service.create_draft("conv-pg", "m-pg", body="The supplied photo shows blue.",
                                         actor_id=self.user, fact_refs=["product.photo.colour"])

    def approve(self, draft_id):
        item = self.service.prepare_confirmation(draft_id)
        confirmation = self.repo.create_confirmation(company_id=self.company, store_id=self.scope.store_id,
            task_id=None, runtime_run_id="support-pg-synthetic", item=item,
            action_type="buyer_message_send", title=item["title"])
        return self.repo.decide_confirmation(company_id=self.company,
            confirmation_id=confirmation["confirmation_id"], decision="approve", decided_by=self.user, note="Synthetic only",
    expected_access_epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company),
)

    def adapter(self, *, barrier=None, prepared=None, unknown=False):
        from jiejing_saas.ebay_message_adapter import EbayMessageAdapter, MESSAGE_SCOPE
        def token(scope):
            if prepared is not None:
                prepared.set()
            if barrier is not None:
                barrier.wait(timeout=10)
            return {"ok": True, "binding": scope.as_dict(), "scopes": [MESSAGE_SCOPE], "access_token": "synthetic"}
        def transport(request, timeout):
            with self.calls_lock:
                self.calls.append("synthetic-message-attempt")
            if unknown:
                raise TimeoutError("synthetic unknown outcome")
            return 201, {}, json.dumps({"messageId": "synthetic-sent", "createdDate": "2026-10-12T01:00:00Z",
                "messageBody": json.loads(request.data)["messageText"],
                "senderUserName": "synthetic-seller", "recipientUserName": "synthetic-buyer"}).encode()
        return EbayMessageAdapter(self.scope, token_provider=token, transport=transport, send_enabled=True)

    def execute(self, service, draft, confirmation, **kwargs):
        return service.execute(draft["draft_id"], confirmation_id=confirmation["confirmation_id"],
                               actor_id=kwargs.pop("actor_id", self.user), adapter=self.adapter(**kwargs))

    def count_intents(self):
        with psycopg.connect(self.dsn) as conn:
            return conn.execute("select count(*) from support_send_intents_v1").fetchone()[0]

    def application(self):
        from types import SimpleNamespace
        from test_jiejing_support_connection_boundary import SupportConnectionBoundaryTests
        from jiejing_saas.support_application import SupportApplication, SupportActorContext
        from jiejing_saas.ebay_message_adapter import MessageScope
        from jiejing_saas.support_conversations import SupportConversations
        fixture = SimpleNamespace(repo=self.repo, company=self.company, user=self.user, store=self.scope.store_id)
        SupportConnectionBoundaryTests.fixture(fixture)
        self.binding_fixture = fixture
        self.scope = MessageScope(self.company, self.scope.store_id, hashlib.sha256(b"synthetic-seller").hexdigest(),
                                  owner_binding_kind="sha256_casefold_ebay_username")
        self.service = SupportConversations(self.repo, self.scope)
        self.incoming["scope"] = self.scope.as_dict()
        self.service.ingest(self.incoming)
        return SupportApplication(self.repo, enabled=True), SupportActorContext(self.user, self.company, self.scope.store_id)

    def test_application_cache_draft_edit_preview_uses_real_postgres(self):
        app, context = self.application()
        with patch.object(self.repo, "initialize", side_effect=AssertionError("application must never initialize")):
            self.assertEqual(app.capability(context)["status"], "local_cache_available")
            self.assertEqual(app.list_conversations(context)["conversations"][0]["conversation_id"], "conv-pg")
            self.assertEqual(app.get_conversation(context, "conv-pg")["messages"][0]["body"], "What colour?")
            draft = app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue."})
            edited = app.edit_draft(context, draft["draft_id"], {"expected_revision": 1, "body": "The photo shows blue."})
            self.assertEqual(edited["revision"], 2)
            preview = app.preview_confirmation(context, draft["draft_id"])
            self.assertEqual(preview["message_body"], "The photo shows blue.")
            self.assertFalse(preview["confirmation_created"])
            self.assertFalse(preview["send_enabled"])
        self.assertEqual(self.count_intents(), 0)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
        rendered = json.dumps([draft, edited, preview, app.get_conversation(context, "conv-pg")])
        for forbidden in (self.binding_fixture.ref, self.binding_fixture.connection_id, self.scope.owner_id):
            self.assertNotIn(forbidden, rendered)

    def test_application_get_and_preview_are_database_enforced_read_only(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        app, context = self.application()
        draft = app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue."})
        statements = []
        original = PostgresConnectionAdapter.execute
        def observed(conn, sql, params=()):
            statements.append(sql.strip().lower())
            return original(conn, sql, params)
        with patch.object(PostgresConnectionAdapter, "execute", observed), \
             patch.object(self.repo, "initialize", side_effect=AssertionError("no GET migrations")):
            self.assertEqual(app.capability(context)["status"], "local_cache_available")
            self.assertTrue(app.list_conversations(context)["conversations"])
            self.assertTrue(app.get_conversation(context, "conv-pg")["messages"])
            self.assertEqual(app.preview_confirmation(context, draft["draft_id"])["status"], "preview_only")
        self.assertTrue(statements)
        self.assertEqual(sum("set transaction isolation level repeatable read, read only" == sql for sql in statements), 4)
        self.assertTrue(all(sql.startswith(("select", "set transaction", "set local search_path")) for sql in statements))
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with app._session(context) as (service, _):
                with service._connection() as conn:
                    conn.execute("delete from support_messages_v1")
        self.assertEqual(len(app.get_conversation(context, "conv-pg")["messages"]), 1)

    def test_application_physical_schema_drift_blocks_even_with_migration_ledger(self):
        app, context = self.application()
        variants = [
            ("alter table support_messages_v1 rename to support_messages_hidden",
             "alter table support_messages_hidden rename to support_messages_v1"),
            ("alter table support_sync_v1 alter column sync_generation set default 9",
             "alter table support_sync_v1 alter column sync_generation set default 0"),
            ("alter table support_sync_v1 alter column current_message_ids_text set default '{}'",
             "alter table support_sync_v1 alter column current_message_ids_text set default '[]'"),
            ("alter table support_drafts_v1 alter column record_text type varchar",
             "alter table support_drafts_v1 alter column record_text type text"),
            ("alter table support_messages_v1 alter column message_text drop not null",
             "alter table support_messages_v1 alter column message_text set not null"),
            ("alter table support_drafts_v1 drop constraint support_drafts_v1_pkey",
             "alter table support_drafts_v1 add primary key (company_id,store_id,owner_id,draft_id,revision)"),
            ("drop index idx_support_sync_scope_order",
             "create index idx_support_sync_scope_order on support_sync_v1(company_id,store_id,owner_id,attempted_at desc,conversation_id)"),
            ("alter table support_sync_v1 add unexpected text",
             "alter table support_sync_v1 drop column unexpected"),
        ]
        for change, restore in variants:
            with self.subTest(change=change):
                with psycopg.connect(self.dsn) as conn:
                    conn.execute(change)
                try:
                    with patch.object(self.repo, "initialize", side_effect=AssertionError("no automatic schema repair")):
                        self.assertEqual(app.capability(context)["blocked_by"], ["support_schema_not_ready"])
                        self.assertEqual(app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})["blocked_by"], ["support_schema_not_ready"])
                    with psycopg.connect(self.dsn) as conn:
                        self.assertEqual(conn.execute("select count(*) from schema_migrations where migration_id=%s", (MIGRATION_ID,)).fetchone()[0], 1)
                finally:
                    with psycopg.connect(self.dsn) as conn:
                        conn.execute(restore)
                self.assertEqual(app.capability(context)["status"], "local_cache_available")

    def test_application_wrong_index_order_and_deferred_unique_fail_closed(self):
        app, context = self.application()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("drop index idx_support_sync_scope_order")
            conn.execute("create index idx_support_sync_scope_order on support_sync_v1(company_id,store_id,owner_id,attempted_at,conversation_id)")
        self.assertEqual(app.capability(context)["blocked_by"], ["support_schema_not_ready"])
        with psycopg.connect(self.dsn) as conn:
            conn.execute("drop index idx_support_sync_scope_order")
            conn.execute("create index idx_support_sync_scope_order on support_sync_v1(company_id,store_id,owner_id,attempted_at desc,conversation_id)")
            constraint = conn.execute("select conname from pg_constraint where conrelid='support_send_intents_v1'::regclass and contype='u' order by conname limit 1").fetchone()[0]
            columns = conn.execute("select array_agg(att.attname order by k.ordinality) from pg_constraint c cross join lateral unnest(c.conkey) with ordinality k(attnum,ordinality) join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum where c.conrelid='support_send_intents_v1'::regclass and c.conname=%s", (constraint,)).fetchone()[0]
            conn.execute(psycopg.sql.SQL("alter table support_send_intents_v1 drop constraint {}").format(psycopg.sql.Identifier(constraint)))
            conn.execute(psycopg.sql.SQL("alter table support_send_intents_v1 add unique ({}) deferrable initially immediate").format(psycopg.sql.SQL(",").join(map(psycopg.sql.Identifier, columns))))
        self.assertEqual(app.capability(context)["blocked_by"], ["support_schema_not_ready"])

    def test_application_nested_service_cannot_commit_before_outer_rollback(self):
        from jiejing_saas.support_conversations import SupportConversations
        app, context = self.application()
        original = SupportConversations._insert_draft
        def interrupted(service, conn, record):
            original(service, conn, record)
            # All previous nested reads exited; this must still belong to the
            # same uncommitted outer application transaction.
            raise RuntimeError("synthetic-outer-rollback")
        with patch.object(SupportConversations, "_insert_draft", interrupted):
            with self.assertRaisesRegex(RuntimeError, "synthetic-outer-rollback"):
                app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from support_drafts_v1").fetchone()[0], 0)
        self.assertEqual(app.capability(context)["status"], "local_cache_available")

    def test_application_rechecks_actor_store_and_connection_every_request(self):
        from dataclasses import replace
        app, context = self.application()
        draft = app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
        for wrong in (replace(context, company_id="other-company"), replace(context, store_id="other-store"), replace(context, actor_id="other-user")):
            with self.assertRaises(PermissionError):
                app.get_conversation(wrong, "conv-pg")
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
        for action in (lambda: app.get_conversation(context, "conv-pg"),
                       lambda: app.edit_draft(context, draft["draft_id"], {"expected_revision": 1, "body": "bad"}),
                       lambda: app.preview_confirmation(context, draft["draft_id"])):
            with self.assertRaisesRegex(PermissionError, "support_actor_not_authorized"):
                action()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update team_members set role='owner' where company_id=%s and user_id=%s", (self.company, self.user))
            conn.execute("update platform_connections set status='revoked' where connection_id=%s", (self.binding_fixture.connection_id,))
        self.assertEqual(app.get_conversation(context, "conv-pg")["blocked_by"], ["support_connection_unavailable"])
        self.assertEqual(self.service.get_draft(draft["draft_id"])["revision"], 1)
        self.assertEqual(self.count_intents(), 0)

    def test_application_concurrent_edits_preserve_one_revision(self):
        app, context = self.application()
        draft = app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
        barrier = Barrier(2)
        def edit(body):
            barrier.wait(timeout=10)
            return app.edit_draft(context, draft["draft_id"], {"expected_revision": 1, "body": body})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(edit, body) for body in ("First", "Second")]
            success, errors = [], []
            for future in futures:
                try:
                    success.append(future.result(timeout=15))
                except ValueError as error:
                    errors.append(str(error))
        self.assertEqual(len(success), 1)
        self.assertEqual(errors, ["draft_revision_conflict"])
        self.assertEqual(len(self.service.draft_history(draft["draft_id"])), 2)
        self.assertEqual(app.preview_confirmation(context, draft["draft_id"])["message_body"], success[0]["body"])

    def test_application_prior_role_revocation_blocks_write_after_real_lock(self):
        app, context = self.application()
        with psycopg.connect(self.dsn) as conn, ThreadPoolExecutor(max_workers=1) as pool:
            conn.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
            create = pool.submit(app.create_draft, context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
            try:
                self.wait_for_lock("team_members")
            finally:
                conn.commit()
            with self.assertRaisesRegex(PermissionError, "support_actor_not_authorized"):
                create.result(timeout=15)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from support_drafts_v1").fetchone()[0], 0)

    def test_application_write_holds_actor_lock_until_outer_commit(self):
        from jiejing_saas.support_conversations import SupportConversations
        app, context = self.application()
        inserted, release = Event(), Event()
        original = SupportConversations._insert_draft
        def paused(service, conn, record):
            original(service, conn, record)
            inserted.set()
            if not release.wait(15):
                raise TimeoutError("synthetic application commit barrier")
        def revoke():
            with psycopg.connect(self.dsn) as conn:
                conn.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(SupportConversations, "_insert_draft", paused):
            create = pool.submit(app.create_draft, context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
            self.assertTrue(inserted.wait(5))
            future = pool.submit(revoke)
            try:
                self.wait_for_lock("team_members")
                with psycopg.connect(self.dsn) as conn:
                    self.assertEqual(conn.execute("select count(*) from support_drafts_v1").fetchone()[0], 0)
            finally:
                release.set()
            self.assertEqual(create.result(timeout=15)["revision"], 1)
            future.result(timeout=15)
        with self.assertRaisesRegex(PermissionError, "support_actor_not_authorized"):
            app.capability(context)

    def test_application_connection_revocation_waits_then_blocks_late_cache_write(self):
        app, context = self.application()
        with psycopg.connect(self.dsn) as conn, ThreadPoolExecutor(max_workers=1) as pool:
            conn.execute("update platform_connections set status='revoked' where connection_id=%s", (self.binding_fixture.connection_id,))
            create = pool.submit(app.create_draft, context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Blue"})
            try:
                self.wait_for_lock("platform_connections")
            finally:
                conn.commit()
            self.assertEqual(create.result(timeout=15)["blocked_by"], ["support_connection_unavailable"])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from support_drafts_v1").fetchone()[0], 0)

    def test_application_borrowed_sync_preserves_persistent_generation_guards(self):
        app, context = self.application()
        with app._session(context, write=True) as (service, _):
            older = service.begin_sync("conv-pg")
        with app._session(context, write=True) as (service, _):
            newer = service.begin_sync("conv-pg")
            service.ingest(self.incoming_revision("current"), expected_generation=newer)
        for generation in (older, newer):
            with self.assertRaisesRegex(ValueError, "support_sync_superseded"):
                with app._session(context, write=True) as (service, _):
                    service.ingest(self.incoming_revision("late"), expected_generation=generation)
        # These fixture timestamps are equal: the existing deterministic tie
        # breaker is message ID, not insertion order.
        self.assertEqual([message["message_id"] for message in app.get_conversation(context, "conv-pg")["messages"]], ["current", "m-pg"])
        with self.assertRaisesRegex(ValueError, "source_message_not_in_current_snapshot"):
            app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Old"})
        self.assertEqual(app.create_draft(context, {"conversation_id": "conv-pg", "source_message_id": "current", "body": "Current"})["revision"], 1)

    def test_application_authenticated_loopback_http_uses_real_postgres(self):
        import http.client
        import threading
        from jiejing_saas.api_server import SaaSBackendHandler, JiejingSafeThreadingHTTPServer
        from jiejing_saas.config import SaaSSettings
        from jiejing_saas.security import SessionManager
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        app, context = self.application()
        sessions = SessionManager(secret="synthetic-owned-pg-http-only", ttl_seconds=600)
        token = sessions.create_token(user_id=self.user, company_id=self.company, email="support@example.test",
            access_epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company))
        self.repo.ensure_user_session(sessions.verify_token(token))
        repo = self.repo
        with patch.dict(os.environ, {"JIEJING_SAAS_ENV": "test", "JIEJING_SAFE_ACCESS_LOG_ENABLED": "false"}):
            settings = SaaSSettings.from_env(db_path=RUN/"unused.sqlite", runtime_db_path=RUN/"unused-runtime.sqlite",
                output_root=RUN/"http-output", host="127.0.0.1", port=0)
            settings.support_cache_workspace_enabled = True
            class Handler(SaaSBackendHandler):
                repository = repo
                support_application = app
            Handler.settings, Handler.sessions = settings, sessions
            server = JiejingSafeThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(suffix, *, body=None, authorized=True):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                try:
                    headers = {"Content-Type": "application/json"}
                    if authorized:
                        headers["Authorization"] = "Bearer " + token
                    conn.request("GET" if body is None else "POST", f"/stores/{context.store_id}/support" + suffix,
                                 body=None if body is None else json.dumps(body).encode(), headers=headers)
                    response = conn.getresponse()
                    return response.status, json.loads(response.read().decode())
                finally:
                    conn.close()
            statements = []
            original = PostgresConnectionAdapter.execute
            def observe(conn, sql, params=()):
                statements.append(sql.strip().lower())
                return original(conn, sql, params)
            try:
                with patch.object(PostgresConnectionAdapter, "execute", observe):
                    self.assertEqual(request("/capability", authorized=False)[0], 401)
                    status, capability = request("/capability")
                    self.assertEqual(status, 200)
                    self.assertEqual(capability["support"]["status"], "local_cache_available")
                    status, detail = request("/conversations/conv-pg")
                    self.assertEqual(status, 200)
                    self.assertEqual(detail["support"]["messages"][0]["body"], "What colour?")
                    status, created = request("/drafts", body={"conversation_id": "conv-pg", "source_message_id": "m-pg", "body": "Photo shows blue."})
                    self.assertEqual(status, 201, created)
                    draft_id = created["support"]["draft_id"]
                    self.assertEqual(request(f"/drafts/{draft_id}/edit", body={"expected_revision": 1, "body": "Checked blue."})[0], 200)
                    self.assertEqual(request(f"/drafts/{draft_id}/edit", body={"expected_revision": 1, "body": "Stale"})[0], 409)
                    status, preview = request(f"/drafts/{draft_id}/confirmation-preview", body={})
                    self.assertEqual(status, 200)
                    self.assertEqual(preview["support"]["message_body"], "Checked blue.")
                    self.assertFalse(preview["support"]["confirmation_created"])
                    self.assertFalse(preview["support"]["send_enabled"])
                    with psycopg.connect(self.dsn) as conn:
                        conn.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
                    self.assertEqual(request("/conversations/conv-pg")[0], 403)
                self.assertTrue(statements)
                self.assertFalse(any(sql.startswith(("create", "alter", "drop")) and "support_" in sql for sql in statements))
                self.assertEqual(self.count_intents(), 0)
                with psycopg.connect(self.dsn) as conn:
                    self.assertEqual(conn.execute("select count(*) from confirmations").fetchone()[0], 0)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def wait_for_lock(self, relation):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with psycopg.connect(self.dsn) as conn:
                rows = conn.execute("""select pid from pg_stat_activity
                    where datname = current_database() and pid <> pg_backend_pid()
                    and wait_event_type = 'Lock' and cardinality(pg_blocking_pids(pid)) > 0
                    and query like %s""", ("%" + relation + "%",)).fetchall()
            if rows:
                return
            time.sleep(0.02)
        self.fail("expected real PostgreSQL blocking lock was not observed: " + relation)

    def test_migration_repeat_and_exact_schema(self):
        result = self.migrate()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["applied_migration_ids"], [])
        self.assertEqual(result["skipped_migration_ids"], [MIGRATION_ID])
        # Independently derive the expected column contract from the existing
        # SQLite schema, but query the actual PG catalogs for the result.
        import sqlite3
        from jiejing_saas.support_conversations import SupportConversations
        with sqlite3.connect(":memory:") as local, psycopg.connect(self.dsn) as conn:
            for statement in SupportConversations.schema_statements():
                local.execute(statement)
            for table in TABLES:
                expected = {row[1]: ("int4" if row[2].lower() == "integer" else "text", bool(row[3]))
                            for row in local.execute("pragma table_info(" + table + ")")}
                actual = {name: (kind, nullable == "NO") for name, kind, nullable in conn.execute(
                    "select column_name, udt_name, is_nullable from information_schema.columns where table_schema='public' and table_name=%s", (table,))}
                self.assertEqual(actual, expected)
                self.assertEqual(conn.execute("select count(*) from pg_constraint where conrelid=%s::regclass and contype='p'", (table,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("select count(*) from pg_constraint where conrelid='support_send_intents_v1'::regclass and contype='u'").fetchone()[0], 2)
            self.assertEqual(conn.execute("""select udt_name, is_nullable, column_default
                from information_schema.columns where table_schema='public'
                and table_name='support_sync_v1' and column_name='sync_generation'""").fetchone(),
                ("int4", "NO", "0"))
        with self.assertRaisesRegex(RuntimeError, "reviewed_production_migration"):
            self.service.initialize_local_schema()

    def test_missing_primary_key_is_not_silently_accepted(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("alter table support_drafts_v1 drop constraint support_drafts_v1_pkey")
            conn.execute("delete from schema_migrations where migration_id=%s", (MIGRATION_ID,))
        self.assertNotEqual(self.migrate()["status"], "ok")
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from schema_migrations where migration_id=%s", (MIGRATION_ID,)).fetchone()[0], 0)

    def test_wrong_column_type_is_not_silently_accepted(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("alter table support_drafts_v1 alter column record_text type varchar")
            conn.execute("delete from schema_migrations where migration_id=%s", (MIGRATION_ID,))
        self.assertNotEqual(self.migrate()["status"], "ok")

    def test_wrong_generation_default_is_not_silently_accepted(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("alter table support_sync_v1 alter column sync_generation set default 9")
            conn.execute("delete from schema_migrations where migration_id=%s", (MIGRATION_ID,))
        self.assertNotEqual(self.migrate()["status"], "ok")
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from schema_migrations where migration_id=%s", (MIGRATION_ID,)).fetchone()[0], 0)

    def incoming_revision(self, message_id, *, status="ok"):
        value = json.loads(json.dumps(self.incoming))
        value["status"] = status
        value["messages"][0]["messageId"] = message_id
        value["messages"][0]["messageBody"] = "Synthetic revision " + message_id
        return value

    def test_begin_sync_preserves_history_but_clears_current_eligibility(self):
        previous = self.service.ingest(self.incoming)
        generation = self.independent().begin_sync("conv-pg")
        self.assertEqual(generation, 2)
        pending = self.service.read_snapshot("conv-pg")
        self.assertEqual(pending["sync_status"], "syncing")
        self.assertEqual(pending["last_success_at"], previous["last_success_at"])
        self.assertEqual(pending["messages"], previous["messages"])
        self.assertEqual(pending["current_message_ids"], [])
        self.assertEqual(pending["current_message_hashes"], {})
        self.assertTrue(self.service.sync_attempt_is_current("conv-pg", generation))
        with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
            self.service.create_draft("conv-pg", "m-pg", body="Unsafe old reply", actor_id=self.user, fact_refs=[])

    def test_concurrent_begin_sync_uses_unique_persistent_generations(self):
        barrier = Barrier(2)
        def begin(service):
            barrier.wait(timeout=10)
            return service.begin_sync("conv-pg")
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(begin, self.independent()) for _ in range(2)]
            generations = [future.result(timeout=15) for future in attempts]
        self.assertEqual(sorted(generations), [1, 2])
        restored = self.independent()
        self.assertFalse(restored.sync_attempt_is_current("conv-pg", 1))
        self.assertTrue(restored.sync_attempt_is_current("conv-pg", 2))
        self.assertEqual(restored.begin_sync("conv-pg"), 3)
        self.assertFalse(self.service.sync_attempt_is_current("conv-pg", 2))

    def test_new_success_cannot_be_overwritten_by_old_success_or_failure(self):
        self.service.ingest(self.incoming)
        older = self.service.begin_sync("conv-pg")
        newer = self.independent().begin_sync("conv-pg")
        current = self.independent().ingest(self.incoming_revision("new-current"), expected_generation=newer)
        self.assertEqual(current["sync_status"], "ok")
        self.assertEqual(current["current_message_ids"], ["new-current"])
        for stale in (self.incoming_revision("stale-result"), self.incoming_revision("stale-result", status="upstream_unavailable")):
            with self.assertRaisesRegex(ValueError, "^support_sync_superseded$"):
                self.independent().ingest(stale, expected_generation=older)
            self.assertEqual(self.service.read_snapshot("conv-pg"), current)
        self.assertEqual([m["messageId"] for m in current["messages"]], ["m-pg", "new-current"])
        with self.assertRaisesRegex(ValueError, "source_message_not_in_current_snapshot"):
            self.service.create_draft("conv-pg", "m-pg", body="Old reply", actor_id=self.user, fact_refs=[])
        draft = self.service.create_draft("conv-pg", "new-current", body="New checked reply", actor_id=self.user, fact_refs=[])
        self.assertEqual(draft["source_message_id"], "new-current")

    def test_new_failure_cannot_be_overwritten_by_old_success_or_failure(self):
        previous = self.service.ingest(self.incoming)
        older = self.service.begin_sync("conv-pg")
        newer = self.independent().begin_sync("conv-pg")
        current = self.independent().ingest(self.incoming_revision("new-result", status="upstream_unavailable"), expected_generation=newer)
        self.assertEqual(current["sync_status"], "upstream_unavailable")
        self.assertEqual(current["current_message_ids"], [])
        self.assertEqual(current["current_message_hashes"], {})
        self.assertEqual(current["last_success_at"], previous["last_success_at"])
        for stale in (self.incoming_revision("stale-result"), self.incoming_revision("stale-result", status="timeout")):
            with self.assertRaisesRegex(ValueError, "^support_sync_superseded$"):
                self.independent().ingest(stale, expected_generation=older)
            self.assertEqual(self.service.read_snapshot("conv-pg"), current)
        with self.assertRaisesRegex(ValueError, "complete_current_snapshot_required"):
            self.service.create_draft("conv-pg", "m-pg", body="Stale success must not enable reply", actor_id=self.user, fact_refs=[])

    def test_same_generation_can_complete_only_once_across_connections(self):
        generation = self.service.begin_sync("conv-pg")
        barrier = Barrier(2)
        def complete(service, message_id):
            barrier.wait(timeout=10)
            return service.ingest(self.incoming_revision(message_id), expected_generation=generation)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(complete, self.independent(), message_id) for message_id in ("first", "second")]
            accepted, errors = [], []
            for future in futures:
                try:
                    accepted.append(future.result(timeout=15))
                except ValueError as error:
                    errors.append(str(error))
        self.assertEqual(len(accepted), 1)
        self.assertEqual(errors, ["support_sync_superseded"])
        current = self.independent().read_snapshot("conv-pg")
        self.assertEqual(current, accepted[0])
        self.assertEqual(len(current["messages"]), 1)
        self.assertEqual(len(current["current_message_ids"]), 1)
        self.assertFalse(self.service.sync_attempt_is_current("conv-pg", generation))
        with self.assertRaisesRegex(ValueError, "^support_sync_superseded$"):
            self.service.ingest(self.incoming_revision("duplicate"), expected_generation=generation)
        self.assertEqual(self.service.read_snapshot("conv-pg"), current)

    def test_direct_ingest_invalidates_pending_network_generation(self):
        pending = self.service.begin_sync("conv-pg")
        current = self.independent().ingest(self.incoming_revision("direct-current"))
        self.assertFalse(self.service.sync_attempt_is_current("conv-pg", pending))
        with self.assertRaisesRegex(ValueError, "^support_sync_superseded$"):
            self.service.ingest(self.incoming_revision("late-network"), expected_generation=pending)
        self.assertEqual(self.independent().read_snapshot("conv-pg"), current)
        self.assertEqual(self.service.begin_sync("conv-pg"), pending + 2)

    def test_migration_ledger_checksum_drift_blocks(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update schema_migrations set checksum='synthetic-drift' where migration_id=%s", (MIGRATION_ID,))
        self.assertIn("postgres_schema_migration_checksum_drift", self.migrate()["blocked_by"])

    def test_wrong_same_name_index_and_failed_ddl_roll_back(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("drop index idx_support_sync_scope_order")
            conn.execute("create index idx_support_sync_scope_order on support_sync_v1 (sync_status)")
            conn.execute("drop index idx_support_messages_scope_order")
            conn.execute("delete from schema_migrations where migration_id=%s", (MIGRATION_ID,))
        self.assertNotEqual(self.migrate()["status"], "ok")
        with psycopg.connect(self.dsn) as conn:
            self.assertIsNone(conn.execute("select to_regclass('public.idx_support_messages_scope_order')").fetchone()[0])
            self.assertEqual(conn.execute("select count(*) from schema_migrations where migration_id=%s", (MIGRATION_ID,)).fetchone()[0], 0)

    def test_real_adapter_transaction_rollback(self):
        with self.assertRaisesRegex(RuntimeError, "rollback-marker"):
            with self.service._connection() as conn:
                conn.execute("insert into support_drafts_v1 values (?, ?, ?, ?, ?, ?)",
                             (*self.service._scope_values(), "rollback-draft", 1, "{}"))
                raise RuntimeError("rollback-marker")
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from support_drafts_v1").fetchone()[0], 0)

    def test_unique_intent_keys_reject_duplicate_scopes(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("insert into support_send_intents_v1 values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (*self.service._scope_values(), "d", "c", "conv", "m", "h", "result_unknown", "{}"))
        for draft, confirmation, conversation, message in (("d", "c2", "conv2", "m2"), ("d2", "c", "conv2", "m2"), ("d3", "c3", "conv", "m")):
            with self.assertRaises(psycopg.errors.UniqueViolation), psycopg.connect(self.dsn) as conn:
                conn.execute("insert into support_send_intents_v1 values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             (*self.service._scope_values(), draft, confirmation, conversation, message, "h", "result_unknown", "{}"))
        self.assertEqual(self.count_intents(), 1)

    def test_two_independent_connections_claim_once(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.execute, self.independent(), draft, confirmation, barrier=barrier) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(self.calls, ["synthetic-message-attempt"])
        self.assertEqual(self.count_intents(), 1)
        self.assertTrue(all(result["status"] in ("sent", "result_unknown") for result in results))

    def test_unknown_survives_new_repository_without_retry(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        first = self.execute(self.service, draft, confirmation, unknown=True)
        second = self.execute(self.independent(), draft, confirmation)
        self.assertEqual(first["status"], "result_unknown")
        self.assertEqual(second, first)
        self.assertEqual(self.calls, ["synthetic-message-attempt"])
        self.assertEqual(self.count_intents(), 1)

    def test_two_distinct_drafts_for_same_source_send_once(self):
        drafts = [self.draft(), self.draft()]
        confirmations = [self.approve(draft["draft_id"]) for draft in drafts]
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.execute, self.independent(), draft, confirmation, barrier=barrier)
                       for draft, confirmation in zip(drafts, confirmations)]
            results, failures = [], []
            for future in futures:
                try:
                    results.append(future.result(timeout=20))
                except ValueError as error:
                    failures.append(str(error))
        self.assertEqual(len(results), 1)
        self.assertEqual(failures, ["source_message_already_claimed"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.count_intents(), 1)

    def test_edit_commits_before_claim_invalidates_approved_body(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        inserted, release = Event(), Event()
        original = self.service._insert_draft
        def pause_insert(conn, record):
            original(conn, record)
            inserted.set()
            if not release.wait(10):
                raise TimeoutError("synthetic edit barrier")
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.service, "_insert_draft", pause_insert):
            edit = pool.submit(self.service.edit_draft, draft["draft_id"], expected_revision=1, body="New checked reply.", actor_id=self.user)
            self.assertTrue(inserted.wait(5))
            send = pool.submit(self.execute, self.independent(), draft, confirmation)
            try:
                self.wait_for_lock("support_drafts_v1")
            finally:
                release.set()
            self.assertEqual(edit.result(timeout=15)["revision"], 2)
            with self.assertRaisesRegex(ValueError, "confirmation_binding_stale"):
                send.result(timeout=15)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.count_intents(), 0)

    def pause_claim(self, entered, release):
        original = self.repo._insert_audit
        def audit(conn, **kwargs):
            result = original(conn, **kwargs)
            if kwargs.get("action_type") == "support.reply.claimed":
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("synthetic claim barrier")
            return result
        return patch.object(self.repo, "_insert_audit", audit)

    def test_claim_first_blocks_edit_and_makes_draft_immutable(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        claimed, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=2) as pool, self.pause_claim(claimed, release):
            send = pool.submit(self.execute, self.service, draft, confirmation)
            self.assertTrue(claimed.wait(5))
            edit = pool.submit(self.independent().edit_draft, draft["draft_id"], expected_revision=1, body="Late edit", actor_id=self.user)
            try:
                self.wait_for_lock("support_drafts_v1")
            finally:
                release.set()
            self.assertEqual(send.result(timeout=15)["status"], "sent")
            with self.assertRaisesRegex(ValueError, "attempted_draft_is_immutable"):
                edit.result(timeout=15)
        self.assertEqual(len(self.calls), 1)

    def test_role_revocation_first_blocks_claim_and_send(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        with psycopg.connect(self.dsn) as revoke, ThreadPoolExecutor(max_workers=1) as pool:
            revoke.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
            send = pool.submit(self.execute, self.independent(), draft, confirmation)
            try:
                self.wait_for_lock("team_members")
            finally:
                revoke.commit()
            with self.assertRaisesRegex(PermissionError, "support_executor_not_authorized"):
                send.result(timeout=15)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.count_intents(), 0)

    def independent_executor(self):
        account = self.repo.create_user_with_company(email="executor@example.test", password="local-synthetic-only",
                                                     company_name="Synthetic Secondary")
        user_id = account["user"]["user_id"]
        with psycopg.connect(self.dsn) as conn:
            conn.execute("insert into team_members (company_id,user_id,role,created_at) values (%s,%s,'operator',now())", (self.company, user_id))
        return user_id

    def revoked_actor_case(self, *, approver, delete):
        executor = self.independent_executor()
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        target = self.user if approver else executor
        with psycopg.connect(self.dsn) as revoke, ThreadPoolExecutor(max_workers=1) as pool:
            statement = ("delete from team_members where company_id=%s and user_id=%s" if delete else
                         "update team_members set role='viewer' where company_id=%s and user_id=%s")
            revoke.execute(statement, (self.company, target))
            send = pool.submit(self.execute, self.independent(), draft, confirmation, actor_id=executor)
            try:
                self.wait_for_lock("team_members")
            finally:
                revoke.commit()
            expected = "confirmation_approver_not_authorized" if approver else "support_executor_not_authorized"
            with self.assertRaisesRegex(PermissionError, expected):
                send.result(timeout=15)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.count_intents(), 0)

    def test_distinct_approver_downgrade_blocks_with_executor_still_valid(self):
        self.revoked_actor_case(approver=True, delete=False)

    def test_distinct_approver_removal_blocks_with_executor_still_valid(self):
        self.revoked_actor_case(approver=True, delete=True)

    def test_distinct_executor_removal_blocks_with_approver_still_valid(self):
        self.revoked_actor_case(approver=False, delete=True)

    def test_account_disable_commits_before_reply_claim_blocks_send(self):
        executor = self.independent_executor()
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        with psycopg.connect(self.dsn) as revoke, ThreadPoolExecutor(max_workers=1) as pool:
            revoke.execute("update users set status='disabled' where user_id=%s", (self.user,))
            send = pool.submit(self.execute, self.independent(), draft, confirmation, actor_id=executor)
            try:
                self.wait_for_lock("users")
            finally:
                revoke.commit()
            with self.assertRaisesRegex(PermissionError, "confirmation_approver_not_authorized"):
                send.result(timeout=15)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.count_intents(), 0)

    def test_account_disable_serializes_new_browser_session(self):
        with psycopg.connect(self.dsn) as revoke, ThreadPoolExecutor(max_workers=1) as pool:
            revoke.execute("update users set status='disabled' where user_id=%s", (self.user,))
            issue = pool.submit(self.repo.create_browser_refresh_session,
                user_id=self.user, company_id=self.company, device_class="desktop", ttl_seconds=3600)
            try:
                self.wait_for_lock("users")
            finally:
                revoke.commit()
            with self.assertRaisesRegex(ValueError, "session_refresh_invalid"):
                issue.result(timeout=15)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from user_refresh_sessions").fetchone()[0], 0)

    def test_account_disable_and_refresh_do_not_deadlock_or_revive(self):
        issued = self.repo.create_browser_refresh_session(user_id=self.user, company_id=self.company,
            device_class="desktop", ttl_seconds=3600)
        refresh = issued["refresh_token"]
        barrier = Barrier(2)
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        original = PostgresConnectionAdapter.execute
        operations = []
        def observe(conn, sql, params=()):
            operations.append(sql.lower())
            return original(conn, sql, params)
        def disable():
            barrier.wait(timeout=5)
            self.repo.set_user_access_status(user_id=self.user, status="disabled")
        def rotate():
            barrier.wait(timeout=5)
            try:
                return self.repo.rotate_browser_refresh_session(refresh_token=refresh)
            except ValueError as error:
                self.assertEqual(str(error), "session_refresh_invalid")
                return None
        with patch.object(PostgresConnectionAdapter, "execute", observe), ThreadPoolExecutor(max_workers=2) as pool:
            revoke = pool.submit(disable)
            renewal = pool.submit(rotate)
            revoke.result(timeout=15)
            rotated = renewal.result(timeout=15)
        self.repo.set_user_access_status(user_id=self.user, status="active")
        for token in (refresh, rotated["refresh_token"] if rotated else refresh):
            with self.assertRaisesRegex(ValueError, "session_refresh_invalid"):
                self.repo.browser_refresh_session_identity(refresh_token=token)
        self.assertTrue(any("users" in sql and "for update" in sql for sql in operations))

    def access_identity(self, *, user=None, company=None, family="", versioned=True):
        from jiejing_saas.security import SessionManager
        user, company = user or self.user, company or self.company
        manager = SessionManager(secret="synthetic-pg-session-only")
        token = manager.create_token(user_id=user, company_id=company, email="owned@example.test",
            refresh_session_id=family,
            access_epochs=self.repo.access_session_epochs(user_id=user, company_id=company) if versioned else None)
        return manager.verify_token(token)

    def test_epoch_migration_preserves_legacy_then_revokes_never_seen_identity_after_upgrade(self):
        from jiejing_saas.infrastructure_drivers import run_postgres_migration
        from jiejing_saas.repository import SaaSRepository
        legacy = self.access_identity(versioned=False)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("drop table access_revocation_epochs")
            conn.execute("delete from schema_migrations where migration_id=%s", ("20261014_007_access_revocation_epochs_postgres",))
        migrated = run_postgres_migration(database_url=self.dsn)
        self.assertEqual(migrated["status"], "ok", migrated)
        self.assertEqual(migrated["applied_migration_ids"], ["20261014_007_access_revocation_epochs_postgres"])
        self.assertTrue(self.repo.ensure_user_session(legacy)["active"])
        unseen = self.access_identity()
        self.repo.set_user_access_status(user_id=self.user, status="disabled")
        self.repo.set_user_access_status(user_id=self.user, status="active")
        restarted = SaaSRepository(RUN / "unused.sqlite", database_engine="postgres", database_url=self.dsn)
        self.assertFalse(restarted.ensure_user_session(legacy)["active"])
        self.assertFalse(restarted.ensure_user_session(unseen)["active"])
        self.assertTrue(restarted.ensure_user_session(self.access_identity())["active"])
        self.assertEqual(run_postgres_migration(database_url=self.dsn)["applied_migration_ids"], [])

    def test_epoch_migration_rejects_preexisting_wrong_schema_without_stamping(self):
        from jiejing_saas.infrastructure_drivers import run_postgres_migration
        with psycopg.connect(self.dsn) as conn:
            conn.execute("drop table access_revocation_epochs")
            conn.execute("delete from schema_migrations where migration_id=%s", ("20261014_007_access_revocation_epochs_postgres",))
            conn.execute("create table access_revocation_epochs(user_id text, company_id text, generation text)")
        result = run_postgres_migration(database_url=self.dsn)
        self.assertNotEqual(result["status"], "ok")
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from schema_migrations where migration_id=%s",
                ("20261014_007_access_revocation_epochs_postgres",)).fetchone()[0], 0)

    def test_user_writes_and_company_management_do_not_deadlock(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        original = PostgresConnectionAdapter.execute
        for user_write in ("account_status_audit", "refresh_family"):
            for management in ("invite", "member_change"):
                with self.subTest(user_write=user_write, management=management):
                    case = user_write + "-" + management
                    account = self.repo.create_user_with_company(email=case + "@example.test",
                        password="local-synthetic-only", company_name="Synthetic FK lock ordering")
                    user, company = account["user"]["user_id"], account["company"]["company_id"]
                    target = None
                    if management == "member_change":
                        target = self.repo.create_user_with_company(email="target-" + case + "@example.test",
                            password="local-synthetic-only", company_name="Synthetic member home")["user"]
                        self.repo.create_team_invitation(company_id=company, invited_by=user,
                            email=target["email"], role="viewer")
                    first_ready, company_locked = Event(), Event()
                    before_write = ("insert into audit_logs" if user_write == "account_status_audit"
                                    else "insert into user_refresh_sessions")

                    def intercepted(conn, sql, params=()):
                        normalized = " ".join(sql.lower().split())
                        writer = current_thread().name.startswith("g01_fk_writer")
                        manager = current_thread().name.startswith("g01_team_manager")
                        if writer and normalized.startswith(before_write):
                            first_ready.set()
                            if not company_locked.wait(10):
                                raise AssertionError("company management did not acquire its row lock")
                        result = original(conn, sql, params)
                        # Semantic statement + thread role: changing FOR UPDATE to
                        # NO KEY UPDATE must not bypass the original interleaving.
                        if manager and normalized.startswith("select company_id from companies where company_id = ?"):
                            self.assertEqual(tuple(params), (company,))
                            company_locked.set()
                        return result

                    def write_user_state():
                        if user_write == "account_status_audit":
                            self.repo.set_user_access_status(user_id=user, status="disabled")
                        else:
                            self.repo.create_browser_refresh_session(user_id=user, company_id=company,
                                device_class="desktop", ttl_seconds=3600,
                                expected_access_epochs={"user_epoch": 0, "member_epoch": 0})
                        return "committed"

                    def manage_company():
                        try:
                            if management == "invite":
                                self.repo.create_team_invitation(company_id=company, invited_by=user,
                                    email="new-" + case + "@example.test", role="viewer")
                            else:
                                self.repo.set_team_member_access(company_id=company, user_id=target["user_id"],
                                    role="operator", actor_user_id=user)
                        except ValueError as error:
                            self.assertEqual(user_write, "account_status_audit")
                            self.assertEqual(str(error), "team management not allowed")
                            return "business_denied"
                        return "committed"

                    with patch.object(PostgresConnectionAdapter, "execute", intercepted), \
                         ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_fk_writer") as writer_pool, \
                         ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_team_manager") as manager_pool:
                        writing = writer_pool.submit(write_user_state)
                        self.assertTrue(first_ready.wait(10), "user lock/write boundary was not reached")
                        managing = manager_pool.submit(manage_company)
                        # Database errors (including 40P01/lock timeout) propagate;
                        # only the expected current-state business denial is handled.
                        written, managed = writing.result(timeout=20), managing.result(timeout=20)
                    expected = "business_denied" if user_write == "account_status_audit" else "committed"
                    self.assertTrue(company_locked.is_set())
                    self.assertEqual((written, managed), ("committed", expected))
                    self.assertEqual(self.repo.get_user(user)["status"],
                        "disabled" if user_write == "account_status_audit" else "active")
                    if management == "invite":
                        self.assertEqual(len(self.repo.list_team_invitations(company_id=company)),
                            0 if expected == "business_denied" else 1)
                    else:
                        self.assertEqual(self.repo.get_team_member(company_id=company, user_id=target["user_id"])["role"],
                            "viewer" if expected == "business_denied" else "operator")
                    if user_write == "refresh_family":
                        self.assertEqual(len(self.repo.list_browser_sessions(user_id=user, company_id=company)), 1)
                    print(json.dumps({"case": case, "writer": written, "manager": managed,
                        "forced_company_lock_interleaving": True, "database_errors": 0}), flush=True)

    def test_login_expiry_cleanup_does_not_deadlock_another_users_device_revocation(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        original = PostgresConnectionAdapter.execute
        other = self.repo.create_user_with_company(email="expiry-revoke-b@example.test",
            password="local-synthetic-only", company_name="Other expiry owner")
        user_b, company_b = other["user"]["user_id"], other["company"]["company_id"]
        expired = {}
        for user, company in ((self.user, self.company), (user_b, company_b)):
            family = self.repo.create_browser_refresh_session(user_id=user, company_id=company,
                device_class="desktop", ttl_seconds=3600)
            sid = family["session"]["session_ref"]
            identity = self.access_identity(user=user, company=company, family=sid)
            self.assertTrue(self.repo.ensure_user_session(identity)["active"])
            expired[user] = (sid, identity["jti"])
        with psycopg.connect(self.dsn) as conn:
            for user, (sid, jti) in expired.items():
                conn.execute("update user_sessions set expires_epoch=%s where jti=%s", (int(time.time()) - 10, jti))
                conn.execute("update user_refresh_token_history set expires_epoch=%s where session_id=%s",
                    (int(time.time()) - 10, sid))
                conn.execute("update user_refresh_sessions set expires_epoch=%s where session_id=%s",
                    (int(time.time()) - 10, sid))
        family_locked, access_cleanup_reached = Event(), Event()

        def intercepted(conn, sql, params=()):
            normalized = " ".join(sql.lower().split())
            result = original(conn, sql, params)
            if current_thread().name.startswith("g01_device_revoke") and normalized.startswith(
                    "select session_id from user_refresh_sessions"):
                family_locked.set()
                if not access_cleanup_reached.wait(10):
                    raise AssertionError("unrelated login did not reach expired access cleanup")
            # Both the old global DELETE and corrected user-scoped DELETE must
            # reach this event, so the regression retains the same interleaving.
            if current_thread().name.startswith("g01_expiry_login") and normalized.startswith("delete from user_sessions "):
                access_cleanup_reached.set()
            return result

        with patch.object(PostgresConnectionAdapter, "execute", intercepted), \
             ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_device_revoke") as revoke_pool, \
             ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_expiry_login") as login_pool:
            revoking = revoke_pool.submit(self.repo.revoke_browser_session, user_id=user_b,
                company_id=company_b, session_id=expired[user_b][0])
            self.assertTrue(family_locked.wait(10), "device revocation family lock was not reached")
            issuing = login_pool.submit(self.repo.create_browser_refresh_session, user_id=self.user,
                company_id=self.company, device_class="desktop", ttl_seconds=3600)
            fresh, revoked = issuing.result(timeout=20), revoking.result(timeout=20)
        self.assertTrue(revoked)
        self.assertTrue(access_cleanup_reached.is_set())
        self.assertEqual(len(self.repo.list_browser_sessions(user_id=self.user, company_id=self.company)), 1)
        with psycopg.connect(self.dsn) as conn:
            sid_a, jti_a = expired[self.user]
            self.assertEqual(conn.execute("select count(*) from user_sessions where jti=%s", (jti_a,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from user_refresh_token_history where session_id=%s",
                (sid_a,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from user_refresh_sessions where session_id=%s",
                (sid_a,)).fetchone()[0], 0)
            sid_b, jti_b = expired[user_b]
            self.assertEqual(conn.execute("select status from user_refresh_sessions where session_id=%s",
                (sid_b,)).fetchone(), ("revoked",))
            self.assertEqual(conn.execute("select status from user_refresh_token_history where session_id=%s",
                (sid_b,)).fetchone(), ("expired",))
            self.assertEqual(conn.execute("select revoked_at is not null from user_sessions where jti=%s",
                (jti_b,)).fetchone(), (True,))
            self.assertEqual(conn.execute("select status from user_refresh_sessions where session_id=%s",
                (fresh["session"]["session_ref"],)).fetchone(), ("active",))
        print(json.dumps({"case": "cross_user_expiry_vs_device_revoke", "login": "committed",
            "revoke": "committed", "other_user_expired_rows_preserved": True,
            "own_expired_rows_cleaned": True, "database_errors": 0}), flush=True)

    def test_auth_expiry_cleanup_neither_locks_nor_deletes_other_users_rows(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        original = PostgresConnectionAdapter.execute

        def snapshot(conn, sid, jti):
            return {
                "access": conn.execute("select user_id, company_id, expires_epoch, revoked_at "
                    "from user_sessions where jti=%s", (jti,)).fetchall(),
                "history": conn.execute("select session_id, generation, status, expires_epoch "
                    "from user_refresh_token_history where session_id=%s", (sid,)).fetchall(),
                "family": conn.execute("select session_id, user_id, company_id, status, expires_epoch, revoked_at "
                    "from user_refresh_sessions where session_id=%s", (sid,)).fetchall(),
            }

        for entry in ("ensure_access", "create_family"):
            for table, key in (("user_sessions", "jti"), ("user_refresh_token_history", "session_id"),
                               ("user_refresh_sessions", "session_id")):
                with self.subTest(entry=entry, held_table=table):
                    other = self.repo.create_user_with_company(email=entry + "-" + table + "@example.test",
                        password="local-synthetic-only", company_name="Isolated expiry owner")
                    user_b, company_b = other["user"]["user_id"], other["company"]["company_id"]
                    fixtures = {}
                    for user, company in ((self.user, self.company), (user_b, company_b)):
                        family = self.repo.create_browser_refresh_session(user_id=user, company_id=company,
                            device_class="desktop", ttl_seconds=3600)
                        sid = family["session"]["session_ref"]
                        identity = self.access_identity(user=user, company=company, family=sid)
                        self.assertTrue(self.repo.ensure_user_session(identity)["active"])
                        fixtures[user] = (sid, identity["jti"])
                    access = self.access_identity()
                    with psycopg.connect(self.dsn) as conn:
                        for sid, jti in fixtures.values():
                            conn.execute("update user_sessions set expires_epoch=%s where jti=%s", (int(time.time()) - 10, jti))
                            conn.execute("update user_refresh_token_history set expires_epoch=%s where session_id=%s",
                                (int(time.time()) - 10, sid))
                            conn.execute("update user_refresh_sessions set expires_epoch=%s where session_id=%s",
                                (int(time.time()) - 10, sid))
                        before = snapshot(conn, *fixtures[user_b])
                    self.assertTrue(all(len(rows) == 1 for rows in before.values()))
                    cleanup_started = Event()

                    def intercepted(conn, sql, params=()):
                        if current_thread().name.startswith("g01_unrelated_auth") and " ".join(sql.lower().split()).startswith(
                                "delete from user_sessions "):
                            cleanup_started.set()
                        return original(conn, sql, params)

                    def authenticate():
                        if entry == "ensure_access":
                            self.assertTrue(self.repo.ensure_user_session(access)["active"])
                        else:
                            self.repo.create_browser_refresh_session(user_id=self.user, company_id=self.company,
                                device_class="desktop", ttl_seconds=3600)
                        return "committed"

                    with patch.object(PostgresConnectionAdapter, "execute", intercepted), \
                         ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_unrelated_auth") as pool, \
                         psycopg.connect(self.dsn) as held:
                        target = fixtures[user_b][1 if key == "jti" else 0]
                        self.assertIsNotNone(held.execute(f"select {key} from {table} where {key}=%s for update",
                            (target,)).fetchone())
                        pending = pool.submit(authenticate)
                        try:
                            self.assertTrue(cleanup_started.wait(10), "authentication cleanup was not reached")
                            # Must finish while B's row remains locked, not only
                            # after a timeout/retry or after this fixture releases it.
                            self.assertEqual(pending.result(timeout=5), "committed")
                        finally:
                            held.rollback()
                    with psycopg.connect(self.dsn) as conn:
                        self.assertEqual(snapshot(conn, *fixtures[user_b]), before,
                            "an unrelated authentication changed another user's expired rows")
                        own = snapshot(conn, *fixtures[self.user])
                    self.assertEqual(own["access"], [])
                    self.assertEqual(len(own["history"]), 0 if entry == "create_family" else 1)
                    self.assertEqual(len(own["family"]), 0 if entry == "create_family" else 1)
                    print(json.dumps({"case": entry, "other_user_locked_table": table,
                        "completed_before_other_lock_release": True, "other_rows_unchanged": True,
                        "database_errors": 0}), flush=True)

    def test_company_management_lock_keeps_last_seat_serialized_between_distinct_owners(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        from jiejing_saas.repository import TeamSeatQuotaExceeded
        original = PostgresConnectionAdapter.execute
        other = self.repo.create_user_with_company(email="seat-second-owner@example.test",
            password="local-synthetic-only", company_name="Second seat owner")
        second_owner = other["user"]["user_id"]
        self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
            email=other["user"]["email"], role="admin")
        self.repo.set_team_member_access(company_id=self.company, user_id=second_owner,
            role="owner", actor_user_id=self.user)
        locked, release = Event(), Event()

        def intercepted(conn, sql, params=()):
            result = original(conn, sql, params)
            if current_thread().name.startswith("g01_seat_first") and " ".join(sql.lower().split()).startswith(
                    "select company_id from companies where company_id = ?"):
                locked.set()
                if not release.wait(10):
                    raise AssertionError("seat admission company lock was not released")
            return result

        def invite(actor, email):
            try:
                self.repo.create_team_invitation(company_id=self.company, invited_by=actor, email=email, role="viewer")
                return "committed"
            except TeamSeatQuotaExceeded as error:
                self.assertEqual(str(error), "team_member_quota_exhausted")
                return "quota_denied"

        with patch.dict(os.environ, {"JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
                "JIEJING_BILLING_PROVIDER": "manual_seed", "JIEJING_DEFAULT_PLAN_KEY": "operator",
                "JIEJING_SAAS_ENV": "test"}):
            # Two active owners plus two pending invitations consume four of five
            # seats. Different actors cannot serialize accidentally on one user row.
            for index in range(2):
                self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
                    email=f"reserved-{index}@example.test", role="viewer")
            with patch.object(PostgresConnectionAdapter, "execute", intercepted), \
                 ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_seat_first") as first_pool, \
                 ThreadPoolExecutor(max_workers=1, thread_name_prefix="g01_seat_second") as second_pool:
                first = first_pool.submit(invite, self.user, "last-seat-a@example.test")
                try:
                    self.assertTrue(locked.wait(5), "first owner did not reach company admission lock")
                    second = second_pool.submit(invite, second_owner, "last-seat-b@example.test")
                    self.wait_for_lock("companies")
                finally:
                    release.set()
                self.assertEqual((first.result(timeout=15), second.result(timeout=15)), ("committed", "quota_denied"))
        members = self.repo.list_team_members(company_id=self.company)
        invitations = self.repo.list_team_invitations(company_id=self.company)
        self.assertEqual(len(members), 2)
        self.assertEqual(sum(item["status"] == "pending" for item in invitations), 3)
        self.assertFalse(any(item["email"] == "last-seat-b@example.test" for item in invitations))
        print(json.dumps({"case": "distinct_owners_last_seat", "first": "committed", "second": "quota_denied",
            "members_plus_pending": 5, "database_errors": 0}), flush=True)

    def test_concurrent_last_owner_demotion_serializes_and_keeps_one_active_owner(self):
        other = self.repo.create_user_with_company(email="second-owner@example.test", password="local-synthetic-only",
            company_name="Second home")
        second = other["user"]["user_id"]
        self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
            email=other["user"]["email"], role="admin")
        self.repo.set_team_member_access(company_id=self.company, user_id=second, role="owner", actor_user_id=self.user)
        barrier = Barrier(2)
        def demote(user):
            barrier.wait(timeout=5)
            try:
                self.repo.set_team_member_access(company_id=self.company, user_id=user, role="viewer", actor_user_id=user)
                return "changed"
            except ValueError as error:
                self.assertIn("last active owner", str(error))
                return "blocked"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(demote, user) for user in (self.user, second)]
            self.assertEqual(sorted(future.result(timeout=15) for future in futures), ["blocked", "changed"])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from team_members tm join users u using(user_id) "
                "where tm.company_id=%s and tm.role='owner' and u.status='active'", (self.company,)).fetchone()[0], 1)

    def test_member_remove_reinvite_persists_epoch_across_repository_restart_and_preserves_other_company(self):
        from jiejing_saas.repository import SaaSRepository
        other = self.repo.create_user_with_company(email="member-epoch@example.test", password="local-synthetic-only",
            company_name="Member home")
        user, home = other["user"]["user_id"], other["company"]["company_id"]
        self.repo.create_team_invitation(company_id=self.company, invited_by=self.user, email=other["user"]["email"], role="operator")
        target_old = self.access_identity(user=user, company=self.company, versioned=False)
        target_new_unseen = self.access_identity(user=user, company=self.company)
        home_access = self.access_identity(user=user, company=home)
        target_family = self.repo.create_browser_refresh_session(user_id=user, company_id=self.company,
            device_class="desktop", ttl_seconds=3600)
        barrier = Barrier(2)
        def remove():
            barrier.wait(timeout=5)
            self.repo.set_team_member_access(company_id=self.company, user_id=user, role=None, actor_user_id=self.user)
        def refresh():
            barrier.wait(timeout=5)
            try:
                return self.repo.rotate_browser_refresh_session(refresh_token=target_family["refresh_token"])
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoked, renewal = pool.submit(remove), pool.submit(refresh)
            revoked.result(timeout=15)
            rotated = renewal.result(timeout=15)
        restarted = SaaSRepository(RUN / "unused.sqlite", database_engine="postgres", database_url=self.dsn)
        restarted.create_team_invitation(company_id=self.company, invited_by=self.user,
            email=other["user"]["email"], role="operator")
        for identity in (target_old, target_new_unseen):
            self.assertFalse(restarted.ensure_user_session(identity)["active"])
        self.assertTrue(restarted.ensure_user_session(home_access)["active"])
        self.assertTrue(restarted.ensure_user_session(self.access_identity(user=user, company=self.company))["active"])
        for token in (target_family["refresh_token"], rotated["refresh_token"] if rotated else target_family["refresh_token"]):
            with self.assertRaises(ValueError):
                restarted.browser_refresh_session_identity(refresh_token=token)

    def test_every_revoke_path_serializes_company_switch_under_the_user_lock(self):
        from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter
        original = PostgresConnectionAdapter.execute
        for kind in ("family", "access_jti", "other_devices", "refresh_logout"):
            with self.subTest(kind=kind):
                source = self.repo.create_browser_refresh_session(user_id=self.user, company_id=self.company,
                    device_class="desktop", ttl_seconds=3600)
                identity = self.access_identity(family=source["session"]["session_ref"])
                self.assertTrue(self.repo.ensure_user_session(identity)["active"])
                other = self.repo.create_browser_refresh_session(user_id=self.user, company_id=self.company,
                    device_class="desktop", ttl_seconds=3600)
                locked, release = Event(), Event()
                def pause(conn, sql, params=()):
                    result = original(conn, sql, params)
                    if not locked.is_set() and sql.lower() == "select user_id from users where user_id = ? for update":
                        locked.set()
                        if not release.wait(10):
                            raise AssertionError("owned revoke lock was not released")
                    return result
                def revoke():
                    if kind == "family":
                        return self.repo.revoke_browser_session(user_id=self.user, company_id=self.company, session_id=identity["sid"])
                    if kind == "access_jti":
                        return self.repo.revoke_user_session(user_id=self.user, jti=identity["jti"])
                    if kind == "refresh_logout":
                        return self.repo.revoke_browser_session_by_refresh_token(refresh_token=source["refresh_token"])
                    return self.repo.revoke_other_browser_sessions(user_id=self.user, company_id=self.company,
                        current_session_id=other["session"]["session_ref"])
                with patch.object(PostgresConnectionAdapter, "execute", pause), ThreadPoolExecutor(max_workers=2) as pool:
                    revoking = pool.submit(revoke)
                    try:
                        self.assertTrue(locked.wait(5), "revocation must lock the user before session rows")
                        issuing = pool.submit(self.repo.create_browser_refresh_session, user_id=self.user,
                            company_id=self.company, device_class="desktop", ttl_seconds=3600, authorizing_identity=identity)
                        self.wait_for_lock("users")
                    finally:
                        release.set()
                    self.assertTrue(revoking.result(timeout=15))
                    with self.assertRaisesRegex(ValueError, "session_access_revoked"):
                        issuing.result(timeout=15)

    def test_claim_lock_precedes_later_role_revocation(self):
        draft = self.draft()
        confirmation = self.approve(draft["draft_id"])
        claimed, release = Event(), Event()
        def revoke_role():
            with psycopg.connect(self.dsn) as conn:
                conn.execute("update team_members set role='viewer' where company_id=%s and user_id=%s", (self.company, self.user))
        with ThreadPoolExecutor(max_workers=2) as pool, self.pause_claim(claimed, release):
            send = pool.submit(self.execute, self.service, draft, confirmation)
            self.assertTrue(claimed.wait(5))
            revoke = pool.submit(revoke_role)
            try:
                self.wait_for_lock("team_members")
            finally:
                release.set()
            self.assertEqual(send.result(timeout=15)["status"], "sent")
            revoke.result(timeout=15)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(PermissionError):
            self.execute(self.independent(), draft, confirmation)
        self.assertEqual(len(self.calls), 1)


def main():
    global RUN, ADMIN_DSN, psycopg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-owned-local-postgres", action="store_true", required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--driver-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--test", default="")
    args = parser.parse_args()
    work_root = args.work_root.resolve()
    if not work_root.is_dir() or work_root.drive.upper() != "D:" or not work_root.is_relative_to(Path("D:/Codex-Verification")):
        parser.error("work root must be an existing directory inside D:/Codex-Verification")
    pg_bin = args.pg_bin.resolve(strict=True)
    for name in ("postgres.exe", "initdb.exe", "pg_ctl.exe"):
        if not (pg_bin / name).is_file():
            parser.error("missing existing PostgreSQL executable: " + name)
    sys.path[:0] = [str(ROOT), str(args.driver_root.resolve(strict=True))]
    import psycopg as driver
    psycopg = driver
    # Do not inherit a PG service/DSN or any application credential configuration.
    for key in list(os.environ):
        if key.startswith(("PG", "JIEJING_")):
            os.environ.pop(key)
    os.environ["JIEJING_DATABASE_POOL_ENABLED"] = "false"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    RUN = Path(tempfile.mkdtemp(prefix="support-pg-", dir=work_root))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    ADMIN_DSN = f"postgresql://support_test@127.0.0.1:{port}/postgres"
    def command(name, *argv):
        # A full suite owns dozens of test databases. On Windows a clean shutdown
        # checkpoint may need more than 45 seconds; do not claim stopped until
        # pg_ctl confirms this exact owned data directory has exited.
        timeout = 150 if "stop" in argv else 45
        result = subprocess.run([str(pg_bin/name), *map(str, argv)], cwd=RUN,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("owned_postgres_command_failed:" + name)
    started = False
    try:
        command("initdb.exe", "-D", RUN/"data", "--username=support_test", "--auth=trust", "--encoding=UTF8", "--locale=C")
        command("pg_ctl.exe", "-D", RUN/"data", "-l", RUN/"postgres.log", "-w", "start", "-o",
                f"-h 127.0.0.1 -p {port} -c max_connections=24 -c shared_buffers=32MB -c statement_timeout=15000 -c lock_timeout=10000")
        started = True
        with psycopg.connect(ADMIN_DSN, connect_timeout=5) as conn:
            assert conn.execute("show listen_addresses").fetchone()[0] == "127.0.0.1"
            assert Path(conn.execute("show data_directory").fetchone()[0]).resolve() == (RUN/"data").resolve()
            version = conn.execute("show server_version").fetchone()[0]
        print(json.dumps({"engine": "real-postgresql", "version": version, "runtime": str(RUN),
                          "loopback_only": True, "production_accessed": False}), flush=True)
        suite = (unittest.defaultTestLoader.loadTestsFromName(args.test, SupportPostgresTests) if args.test else
                 unittest.defaultTestLoader.loadTestsFromTestCase(SupportPostgresTests))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        if started or (RUN/"data/postmaster.pid").exists():
            command("pg_ctl.exe", "-D", RUN/"data", "-w", "-t", "120", "stop", "-m", "fast")
        print(json.dumps({"owned_postgres_stopped": True, "runtime": str(RUN)}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
