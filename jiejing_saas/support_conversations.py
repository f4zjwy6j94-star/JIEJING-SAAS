"""Tenant-scoped support candidate using the existing repository connection.

No production DDL, automatic network I/O, model invocation or implicit approvals.
Schema version is a deployment dependency; initialize_local_schema is SQLite-only
and must be explicitly called in a local candidate, never from an API GET route.
The API must derive the hash-mode MessageScope from independently verified eBay
connection identity, never request JSON or a display name. Raw mode is local
fixture compatibility only. Existing role and safe-origin checks still apply.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import hashlib
import re
import uuid
from typing import Any

from .ebay_message_adapter import MessageScope, MAX_MESSAGE_TEXT_LENGTH
from .permissions import has_permission

SCHEMA_VERSION = "2026-10-12-support-conversations-v3"
_WHERE = "company_id = ? and store_id = ? and owner_id = ?"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _is_utf8_text(value):
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _message_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("invalid_message_timestamp")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("invalid_message_timestamp") from None


def _ordered_messages(messages):
    # Parse even pre-fix cached records; textual ISO ordering is not chronological
    # when fractional seconds or timezone offsets differ.
    return sorted(messages, key=lambda message: (_message_time(message.get("createdDate")), message["messageId"]))


class SupportConversations:
    def __init__(self, repository, scope: MessageScope):
        self.repository = repository
        self.scope = scope

    @contextmanager
    def _connection(self):
        conn = self.repository._connect()
        try:
            with conn:
                yield conn
        finally:
            if self.repository.database_engine == "sqlite":
                conn.close()

    def _scope_values(self):
        if not self.repository.get_store_for_company(company_id=self.scope.company_id, store_id=self.scope.store_id):
            raise PermissionError("store_not_accessible")
        return (self.scope.company_id, self.scope.store_id, self.scope.owner_storage_key)

    @staticmethod
    def schema_statements():
        # TEXT, not JSONB: avoid bypassing the repository adapter's explicit JSON registry.
        return [
            """create table if not exists support_messages_v1 (
                company_id text not null, store_id text not null, owner_id text not null,
                conversation_id text not null, message_id text not null,
                message_text text not null, created_at text not null, record_text text not null,
                primary key(company_id, store_id, owner_id, conversation_id, message_id))""",
            """create table if not exists support_sync_v1 (
                company_id text not null, store_id text not null, owner_id text not null,
                conversation_id text not null, sync_status text not null,
                attempted_at text not null, last_success_at text, truncated integer not null,
                current_message_ids_text text not null default '[]',
                current_message_hashes_text text not null default '{}',
                sync_generation integer not null default 0,
                primary key(company_id, store_id, owner_id, conversation_id))""",
            """create table if not exists support_drafts_v1 (
                company_id text not null, store_id text not null, owner_id text not null,
                draft_id text not null, revision integer not null, record_text text not null,
                primary key(company_id, store_id, owner_id, draft_id, revision))""",
            """create table if not exists support_send_intents_v1 (
                company_id text not null, store_id text not null, owner_id text not null,
                draft_id text not null, confirmation_id text not null,
                conversation_id text not null, source_message_id text not null,
                binding_hash text not null, status text not null, record_text text not null,
                primary key(company_id, store_id, owner_id, draft_id),
                unique(company_id, store_id, owner_id, confirmation_id),
                unique(company_id, store_id, owner_id, conversation_id, source_message_id))""",
        ]

    def initialize_local_schema(self):
        if self.repository.database_engine != "sqlite":
            raise RuntimeError("support_schema_requires_reviewed_production_migration")
        self.repository.initialize()
        self._scope_values()
        with self._connection() as conn:
            for statement in self.schema_statements():
                conn.execute(statement)
            # Explicit local candidate upgrade only; never reached on PostgreSQL.
            columns = {row["name"] for row in conn.execute("pragma table_info(support_sync_v1)").fetchall()}
            for column, default in (("current_message_ids_text", "[]"), ("current_message_hashes_text", "{}")):
                if column not in columns:
                    conn.execute(f"alter table support_sync_v1 add column {column} text not null default '{default}'")
            if "sync_generation" not in columns:
                conn.execute("alter table support_sync_v1 add column sync_generation integer not null default 0")

    def begin_sync(self, conversation_id: str) -> int:
        """Reserve an ordered attempt before external I/O; old reply eligibility ends now."""
        scope = self._scope_values()
        if not _is_utf8_text(conversation_id) or not conversation_id:
            raise ValueError("conversation_id_required")
        with self._connection() as conn:
            if self.repository.database_engine == "sqlite":
                conn.execute("begin immediate")
            row = conn.execute("""insert into support_sync_v1
                (company_id, store_id, owner_id, conversation_id, sync_status, attempted_at,
                 last_success_at, truncated, current_message_ids_text, current_message_hashes_text, sync_generation)
                values (?, ?, ?, ?, 'syncing', ?, null, 0, '[]', '{}', 1)
                on conflict (company_id, store_id, owner_id, conversation_id) do update set
                sync_status = 'syncing', attempted_at = excluded.attempted_at, truncated = 0,
                current_message_ids_text = '[]', current_message_hashes_text = '{}',
                sync_generation = support_sync_v1.sync_generation + 1
                returning sync_generation""", (*scope, conversation_id, _now())).fetchone()
        return int(row["sync_generation"])

    def sync_attempt_is_current(self, conversation_id: str, generation: int) -> bool:
        if type(generation) is not int or generation < 1:
            return False
        scope = self._scope_values()
        with self._connection() as conn:
            row = conn.execute(f"select sync_generation, sync_status from support_sync_v1 where {_WHERE} and conversation_id = ?",
                               (*scope, conversation_id)).fetchone()
        return bool(row and row["sync_generation"] == generation and row["sync_status"] == "syncing")

    def ingest(self, result: dict[str, Any], *, expected_generation: int | None = None):
        # Network callers must use begin_sync + expected_generation. A direct,
        # synchronous ingest also increments the counter, invalidating older I/O.
        if expected_generation is not None and (type(expected_generation) is not int or expected_generation < 1):
            raise ValueError("support_sync_generation_invalid")
        scope = self._scope_values()
        if result.get("scope") != self.scope.as_dict():
            raise PermissionError("message_scope_mismatch")
        conversation_id = result.get("conversation_id")
        if not _is_utf8_text(conversation_id) or not conversation_id:
            raise ValueError("conversation_id_required")
        status = str(result.get("status") or "invalid_response")
        if not _is_utf8_text(status):
            status = "invalid_response"
        normalized = []
        if status == "ok" and not isinstance(result.get("messages"), list):
            status = "messages_required"
        if status == "ok":
            for message in result["messages"]:
                if (not isinstance(message, dict) or not isinstance(message.get("messageId"), str)
                        or not message["messageId"].strip() or not isinstance(message.get("messageBody"), str)
                        or any(not isinstance(message.get(key), str) or not message[key].strip()
                               for key in ("senderUsername", "recipientUsername"))
                        or any(not _is_utf8_text(message.get(key)) for key in
                               ("messageId", "messageBody", "senderUsername", "recipientUsername"))):
                    # A failed refresh of this bound conversation must invalidate
                    # send eligibility, not leave the prior successful batch usable.
                    status = "invalid_message_record"
                    normalized = []
                    break
                if not any(self.scope.matches_owner(message[key]) for key in ("senderUsername", "recipientUsername")):
                    status = "message_owner_mismatch"
                    normalized = []
                    break
                try:
                    if not _is_utf8_text(message.get("createdDate")):
                        raise ValueError("invalid_message_timestamp")
                    timestamp = _message_time(message.get("createdDate")).isoformat(timespec="microseconds").replace("+00:00", "Z")
                except ValueError:
                    status = "invalid_message_timestamp"
                    normalized = []
                    break
                # Only persist fields needed to display/reply; never media URLs/raw envelopes.
                normalized.append({**{key: message.get(key, "") for key in (
                    "messageId", "messageBody", "senderUsername", "recipientUsername")}, "createdDate": timestamp})
        now = _now()
        with self._connection() as conn:
            if self.repository.database_engine == "sqlite":
                conn.execute("begin immediate")
            if expected_generation is not None:
                lock = " for update" if self.repository.database_engine == "postgres" else ""
                state = conn.execute(f"select sync_generation, sync_status from support_sync_v1 where {_WHERE} and conversation_id = ?{lock}",
                                     (*scope, conversation_id)).fetchone()
                if not state or state["sync_generation"] != expected_generation or state["sync_status"] != "syncing":
                    raise ValueError("support_sync_superseded")
            for item in normalized:
                conn.execute("""insert into support_messages_v1
                    (company_id, store_id, owner_id, conversation_id, message_id, message_text, created_at, record_text)
                    values (?, ?, ?, ?, ?, ?, ?, ?) on conflict do nothing""",
                    (*scope, conversation_id, item["messageId"], item["messageBody"], item["createdDate"], json.dumps(item)))
            conn.execute("""insert into support_sync_v1
                (company_id, store_id, owner_id, conversation_id, sync_status, attempted_at, last_success_at, truncated,
                 current_message_ids_text, current_message_hashes_text, sync_generation)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict (company_id, store_id, owner_id, conversation_id) do update set
                sync_status = excluded.sync_status, attempted_at = excluded.attempted_at,
                last_success_at = coalesce(excluded.last_success_at, support_sync_v1.last_success_at),
                truncated = excluded.truncated, current_message_ids_text = excluded.current_message_ids_text,
                current_message_hashes_text = excluded.current_message_hashes_text,
                sync_generation = """ + ("support_sync_v1.sync_generation + 1" if expected_generation is None else "excluded.sync_generation"),
                (*scope, conversation_id, status, now, now if status == "ok" else None, int(bool(result.get("truncated"))),
                 json.dumps([item["messageId"] for item in normalized]),
                 json.dumps({item["messageId"]: _hash(item) for item in normalized}),
                 1 if expected_generation is None else expected_generation))
        return self.read_snapshot(conversation_id)

    def read_snapshot(self, conversation_id: str):
        scope = self._scope_values()
        with self._connection() as conn:
            rows = conn.execute(f"select record_text from support_messages_v1 where {_WHERE} and conversation_id = ? order by created_at, message_id",
                                (*scope, conversation_id)).fetchall()
            state = conn.execute(f"select * from support_sync_v1 where {_WHERE} and conversation_id = ?",
                                 (*scope, conversation_id)).fetchone()
        messages = [json.loads(row["record_text"]) for row in rows]
        status = state["sync_status"] if state else "never_synced"
        try:
            messages = _ordered_messages(messages)
        except ValueError:
            status = "invalid_message_timestamp"
        return {"scope": self.scope.as_dict(), "conversation_id": conversation_id,
                "messages": messages, "sync_status": status,
                "current_message_ids": json.loads(state["current_message_ids_text"]) if state else [],
                "current_message_hashes": json.loads(state["current_message_hashes_text"]) if state else {},
                "last_success_at": state["last_success_at"] if state else None,
                "truncated": bool(state["truncated"]) if state else False}

    def list_conversations(self, *, limit=25, offset=0):
        if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError("invalid_cached_pagination")
        scope = self._scope_values()
        with self._connection() as conn:
            rows = conn.execute(f"select conversation_id, sync_status, attempted_at, last_success_at, truncated from support_sync_v1 where {_WHERE} order by attempted_at desc, conversation_id limit ? offset ?",
                                (*scope, limit + 1, offset)).fetchall()
        return {"conversations": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit,
                "external_request_performed": False, "scope": self.scope.as_dict()}

    def _require_actor(self, actor_id, permission):
        member = self.repository.get_team_member(company_id=self.scope.company_id, user_id=actor_id)
        if not member or member.get("status") != "active" or not has_permission(str(member.get("role") or ""), permission):
            raise PermissionError("support_missing_permission:" + permission)

    @staticmethod
    def _body(body):
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_MESSAGE_TEXT_LENGTH:
            raise ValueError("invalid_draft_body")
        return body.strip()

    def create_draft(self, conversation_id: str, source_message_id: str, *, body: str,
                     actor_id: str, fact_refs: list[str], ai_review: dict | None = None):
        self._require_actor(actor_id, "create_task")
        snapshot = self.read_snapshot(conversation_id)
        source = next((m for m in snapshot["messages"] if m["messageId"] == source_message_id), None)
        if not source or not self.scope.is_incoming_message(source["senderUsername"], source["recipientUsername"]):
            raise ValueError("incoming_source_message_required")
        if snapshot["sync_status"] != "ok" or snapshot["truncated"]:
            raise ValueError("complete_current_snapshot_required")
        if source_message_id not in snapshot["current_message_ids"] or snapshot["current_message_hashes"].get(source_message_id) != _hash(source):
            raise ValueError("source_message_not_in_current_snapshot")
        if not isinstance(fact_refs, list) or len(fact_refs) > 30 or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in fact_refs):
            raise ValueError("invalid_fact_references")
        draft = {"draft_id": "support-draft-" + uuid.uuid4().hex, "revision": 1,
                 "conversation_id": conversation_id, "source_message_id": source_message_id,
                 "source_hash": _hash(source), "reply_to": source["senderUsername"],
                 "body": self._body(body), "fact_refs": list(fact_refs), "actor_id": actor_id,
                 "created_at": _now(), "scope": self.scope.as_dict(), "status": "draft",
                 "generation_kind": "editable_draft_not_automatic_reply"}
        if ai_review is not None:
            # Internal provenance only. This is not approval, a send policy or
            # a substitute for current-fact checks by an authorized sender.
            if (type(ai_review) is not dict or set(ai_review) != {
                    "binding_hash", "fact_version", "policy_version", "product_binding", "contract_version"}
                    or any(type(value) is not str or not value or len(value) > 300 for value in ai_review.values())
                    or re.fullmatch(r"[0-9a-f]{64}", ai_review["binding_hash"]) is None
                    or ai_review["contract_version"] != "support_ai_decision_v1"):
                raise ValueError("invalid_support_ai_review")
            draft["ai_review"] = dict(ai_review)
            draft["generation_kind"] = "ai_reviewed_draft_not_authorization"
        with self._connection() as conn:
            claimed = conn.execute(f"select draft_id from support_send_intents_v1 where {_WHERE} and conversation_id = ? and source_message_id = ?",
                                   (self.scope.company_id, self.scope.store_id, self.scope.owner_storage_key, conversation_id, source_message_id)).fetchone()
            if claimed:
                raise ValueError("source_message_already_claimed")
            self._insert_draft(conn, draft)
        return draft

    def _insert_draft(self, conn, draft):
        conn.execute("""insert into support_drafts_v1
            (company_id, store_id, owner_id, draft_id, revision, record_text) values (?, ?, ?, ?, ?, ?)""",
            (self.scope.company_id, self.scope.store_id, self.scope.owner_storage_key,
             draft["draft_id"], draft["revision"], json.dumps(draft)))

    def draft_history(self, draft_id):
        scope = self._scope_values()
        with self._connection() as conn:
            rows = conn.execute(f"select record_text from support_drafts_v1 where {_WHERE} and draft_id = ? order by revision",
                                (*scope, draft_id)).fetchall()
        return [json.loads(row["record_text"]) for row in rows]

    def get_draft(self, draft_id):
        history = self.draft_history(draft_id)
        if not history:
            raise KeyError("support_draft_not_found")
        return history[-1]

    def edit_draft(self, draft_id, *, expected_revision: int, body: str, actor_id: str):
        self._require_actor(actor_id, "create_task")
        scope = self._scope_values()
        with self._connection() as conn:
            if self.repository.database_engine == "sqlite":
                conn.execute("begin immediate")
            lock = " for update" if self.repository.database_engine == "postgres" else ""
            conn.execute(f"select revision from support_drafts_v1 where {_WHERE} and draft_id = ? and revision = 1{lock}",
                         (*scope, draft_id)).fetchone()
            attempted = conn.execute(f"select status from support_send_intents_v1 where {_WHERE} and draft_id = ?",
                                     (*scope, draft_id)).fetchone()
            if attempted:
                raise ValueError("attempted_draft_is_immutable")
            row = conn.execute(f"select record_text from support_drafts_v1 where {_WHERE} and draft_id = ? order by revision desc limit 1{lock}",
                               (*scope, draft_id)).fetchone()
            if not row:
                raise KeyError("support_draft_not_found")
            draft = json.loads(row["record_text"])
            if type(expected_revision) is not int or draft["revision"] != expected_revision:
                raise ValueError("draft_revision_conflict")
            draft.update(revision=expected_revision + 1, body=self._body(body), actor_id=actor_id, created_at=_now())
            draft.pop("ai_review", None)
            draft["generation_kind"] = "editable_draft_not_automatic_reply"
            self._insert_draft(conn, draft)
        return draft

    def prepare_confirmation(self, draft_id):
        """Return an item for repository.create_confirmation; this is NOT approval."""
        draft = self.get_draft(draft_id)
        binding = {**self.scope.as_dict(), "draft_id": draft_id, "revision": draft["revision"],
                   "conversation_id": draft["conversation_id"], "source_message_id": draft["source_message_id"],
                   "source_hash": draft["source_hash"], "reply_to": draft["reply_to"],
                   "body_hash": _hash(draft["body"]), "fact_refs_hash": _hash(draft["fact_refs"])}
        risks = ["manual_confirmation_required", "fact_references_unverified"]
        if not draft["fact_refs"]:
            risks.append("facts_not_attached")
        if re.search(r"refund|compensation|guarantee|arriv.*(?:by|on)|退款|赔偿|保证|保证到货", draft["body"], re.I):
            risks.append("sensitive_commitment_review_required")
        return {"action_type": "buyer_message_send", "title": "确认发送买家回复",
                "default_action": "hold", "message_body": draft["body"],
                "support_binding": binding, "support_binding_hash": _hash(binding),
                "risk_flags": risks, "facts_verified": False, "fact_reference_status": "unverified_merchant_references",
                "automatic_send_allowed": False}

    def get_send_intent(self, draft_id):
        scope = self._scope_values()
        with self._connection() as conn:
            row = conn.execute(f"select record_text from support_send_intents_v1 where {_WHERE} and draft_id = ?",
                               (*scope, draft_id)).fetchone()
        return json.loads(row["record_text"]) if row else None

    def execute(self, draft_id, *, confirmation_id: str, actor_id: str, adapter):
        """One claimed attempt from an existing approved confirmation. Never retries.

        This does not alter generic confirmation execution states. Integration must
        route buyer_message_send here, not through the listing adapter; the visible
        execution record should be populated only from this durable receipt.
        """
        self._require_actor(actor_id, "execute_confirmed_action")
        scope = self._scope_values()
        if adapter.scope != self.scope:
            raise PermissionError("adapter_scope_mismatch")
        if not adapter.send_enabled:
            return {"status": "blocked_send_disabled", "message_sent": False}
        item = self.prepare_confirmation(draft_id)
        draft = self.get_draft(draft_id)
        self._body(draft["body"])  # Revalidate legacy/local rows before a durable send claim.
        # Authorization and exact body checks precede token resolution. Re-check
        # under the DB lock below after this non-message credential preflight.
        preliminary = self.repository.get_confirmation(company_id=self.scope.company_id, confirmation_id=confirmation_id)
        if not preliminary or preliminary["store_id"] != self.scope.store_id or preliminary["action_type"] != "buyer_message_send":
            raise PermissionError("support_confirmation_scope_mismatch")
        previous = self.get_send_intent(draft_id)
        if previous:
            if previous["confirmation_id"] != confirmation_id:
                raise ValueError("draft_already_claimed")
            return previous
        if preliminary["status"] != "approved":
            raise PermissionError("approved_confirmation_required")
        self._require_actor(preliminary["decided_by"], "approve_high_risk")
        approved_item = preliminary.get("item") or {}
        if (approved_item.get("support_binding") != item["support_binding"]
                or approved_item.get("support_binding_hash") != item["support_binding_hash"]
                or approved_item.get("message_body") != draft["body"]):
            raise ValueError("confirmation_binding_stale")
        prepared = adapter.prepare_reply(draft["conversation_id"], draft["body"], expected_recipient=draft["reply_to"])
        if isinstance(prepared, dict):
            return {"status": prepared["status"], "message_sent": False, "buyer_message_http_attempted": False,
                    "automatic_retry_allowed": False, "send_intent_created": False}
        with self._connection() as conn:
            if self.repository.database_engine == "sqlite":
                conn.execute("begin immediate")
            lock = " for update" if self.repository.database_engine == "postgres" else ""
            confirmation = conn.execute(f"select * from confirmations where company_id = ? and confirmation_id = ?{lock}",
                                        (self.scope.company_id, confirmation_id)).fetchone()
            if not confirmation or confirmation["store_id"] != self.scope.store_id or confirmation["action_type"] != "buyer_message_send":
                raise PermissionError("support_confirmation_scope_mismatch")
            previous = conn.execute(f"select record_text from support_send_intents_v1 where {_WHERE} and draft_id = ?",
                                    (*scope, draft_id)).fetchone()
            if previous:
                previous = json.loads(previous["record_text"])
                if previous["confirmation_id"] != confirmation_id:
                    raise ValueError("draft_already_claimed")
                return previous
            if confirmation["status"] != "approved":
                raise PermissionError("approved_confirmation_required")
            # Token preparation may take time. Revalidate both actors inside the
            # durable-claim transaction; never reuse preflight permission results.
            # Stable ordering also prevents opposite executor/approver lock order.
            accounts = conn.execute(f"select user_id, status from users where user_id in (?, ?) "
                                    f"order by user_id{lock}",
                                    (actor_id, confirmation["decided_by"])).fetchall()
            active_accounts = {account["user_id"] for account in accounts if account["status"] == "active"}
            members = conn.execute(f"select user_id, role from team_members where company_id = ? "
                                   f"and user_id in (?, ?) order by user_id{lock}",
                                   (self.scope.company_id, actor_id, confirmation["decided_by"])).fetchall()
            roles = {member["user_id"]: member["role"] for member in members if member["user_id"] in active_accounts}
            if not has_permission(roles.get(actor_id), "execute_confirmed_action"):
                raise PermissionError("support_executor_not_authorized")
            if not has_permission(roles.get(confirmation["decided_by"]), "approve_high_risk"):
                raise PermissionError("confirmation_approver_not_authorized")
            approved = confirmation["item_json"]
            approved = json.loads(approved) if isinstance(approved, str) else approved
            if (approved.get("support_binding") != item["support_binding"]
                    or approved.get("support_binding_hash") != item["support_binding_hash"]
                    or approved.get("message_body") != draft["body"]):
                raise ValueError("confirmation_binding_stale")
            # The first revision is a stable serialization row across later inserts.
            conn.execute(f"select revision from support_drafts_v1 where {_WHERE} and draft_id = ? and revision = 1{lock}",
                         (*scope, draft_id)).fetchone()
            current = conn.execute(f"select revision from support_drafts_v1 where {_WHERE} and draft_id = ? order by revision desc limit 1",
                                   (*scope, draft_id)).fetchone()
            if not current or current["revision"] != draft["revision"]:
                raise ValueError("confirmation_binding_stale")
            sync = conn.execute(f"select * from support_sync_v1 where {_WHERE} and conversation_id = ?{lock}",
                                (*scope, draft["conversation_id"])).fetchone()
            if not sync or sync["sync_status"] != "ok" or sync["truncated"] or not sync["last_success_at"]:
                raise ValueError("complete_current_snapshot_required")
            if (datetime.now(timezone.utc) - datetime.fromisoformat(sync["last_success_at"])).total_seconds() > 300:
                raise ValueError("support_snapshot_stale")
            current_ids = json.loads(sync["current_message_ids_text"])
            current_hashes = json.loads(sync["current_message_hashes_text"])
            if draft["source_message_id"] not in current_ids or current_hashes.get(draft["source_message_id"]) != draft["source_hash"]:
                raise ValueError("source_message_not_in_current_snapshot")
            messages = conn.execute(f"select record_text from support_messages_v1 where {_WHERE} and conversation_id = ? order by created_at, message_id",
                                    (*scope, draft["conversation_id"])).fetchall()
            incoming = _ordered_messages([json.loads(row["record_text"]) for row in messages])
            incoming = [message for message in incoming if message["messageId"] in current_ids]
            if any(current_hashes.get(message["messageId"]) != _hash(message) for message in incoming):
                raise ValueError("source_message_not_in_current_snapshot")
            incoming = [m for m in incoming if self.scope.is_incoming_message(m["senderUsername"], m["recipientUsername"])]
            if len(incoming) > 1 and _message_time(incoming[-1]["createdDate"]) == _message_time(incoming[-2]["createdDate"]):
                raise ValueError("source_message_order_ambiguous")
            if not incoming or incoming[-1]["messageId"] != draft["source_message_id"] or _hash(incoming[-1]) != draft["source_hash"]:
                raise ValueError("source_message_changed_since_draft")
            source_claimed = conn.execute(f"select draft_id from support_send_intents_v1 where {_WHERE} and conversation_id = ? and source_message_id = ?",
                                         (*scope, draft["conversation_id"], draft["source_message_id"])).fetchone()
            if source_claimed:
                raise ValueError("source_message_already_claimed")
            receipt = {"status": "result_unknown", "message_sent": False, "draft_id": draft_id,
                       "confirmation_id": confirmation_id, "binding_hash": item["support_binding_hash"],
                       "attempted_at": _now(), "automatic_retry_allowed": False}
            conn.execute("""insert into support_send_intents_v1
                (company_id, store_id, owner_id, draft_id, confirmation_id, conversation_id, source_message_id, binding_hash, status, record_text)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (*scope, draft_id, confirmation_id, draft["conversation_id"], draft["source_message_id"],
                     item["support_binding_hash"], "result_unknown", json.dumps(receipt)))
            self.repository._insert_audit(conn, company_id=self.scope.company_id, store_id=self.scope.store_id,
                user_id=actor_id, actor_type="user", action_type="support.reply.claimed",
                target_type="confirmation", target_id=confirmation_id, summary="Confirmed support reply claimed once.",
                details={"draft_id": draft_id, "binding_hash": item["support_binding_hash"], "automatic_retry_allowed": False})
        try:
            result = adapter.send_prepared_reply(prepared)
        except Exception:
            result = {"status": "result_unknown", "message_sent": False}
        receipt.update({key: result[key] for key in ("status", "message_sent", "message_id", "created_at", "http_status") if key in result})
        if receipt.get("status") == "sent" and (not receipt.get("message_id") or not receipt.get("created_at")):
            receipt.update(status="result_unknown", message_sent=False)
        with self._connection() as conn:
            conn.execute(f"update support_send_intents_v1 set status = ?, record_text = ? where {_WHERE} and draft_id = ? and confirmation_id = ?",
                         (receipt["status"], json.dumps(receipt), *scope, draft_id, confirmation_id))
            self.repository._insert_audit(conn, company_id=self.scope.company_id, store_id=self.scope.store_id,
                user_id=actor_id, actor_type="system", action_type="support.reply.result",
                target_type="confirmation", target_id=confirmation_id, summary="Support reply attempt result recorded.",
                details={"draft_id": draft_id, "status": receipt["status"], "message_sent": receipt["message_sent"],
                         "automatic_retry_allowed": False})
        return receipt
