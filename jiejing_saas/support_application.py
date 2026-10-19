"""Default-off local support facade, not an HTTP authentication or send boundary.

Only trusted server code may construct actor context and enable this facade.
Existing schemas only: this facade never migrates or enables approval/send.
"""
from dataclasses import dataclass, replace
from contextlib import contextmanager
from pathlib import Path
import json
import re
import sqlite3

from .repository import SaaSRepository
from .ebay_message_adapter import MessageScope, EbayMessageAdapter
from .support_conversations import SupportConversations, _hash as message_hash
from .support_ai_decision import (SupportKnowledge, SupportMessage, SupportTurn,
    decide_support_reply, _validate_turn, _result as ai_result)
from .support_token_resolver import SupportTokenResolver
from .config import SaaSSettings

_ROLES = frozenset({"owner", "admin", "support"})
_PREFIX = ("company_id", "store_id", "owner_id")
_SUPPORT_SCHEMA = {
    "support_messages_v1": (_PREFIX + ("conversation_id", "message_id"),
        ("message_text", "created_at", "record_text")),
    "support_sync_v1": (_PREFIX + ("conversation_id",),
        ("sync_status", "attempted_at", "last_success_at", "truncated",
         "current_message_ids_text", "current_message_hashes_text", "sync_generation")),
    "support_drafts_v1": (_PREFIX + ("draft_id", "revision"), ("record_text",)),
    "support_send_intents_v1": (_PREFIX + ("draft_id",),
        ("confirmation_id", "conversation_id", "source_message_id", "binding_hash", "status", "record_text")),
}
_BASE_COLUMNS = {
    "team_members": "company_id,user_id,role",
    "users": "user_id,status",
    "stores": "company_id,store_id,store_json",
    "platform_connections": "company_id,store_id,platform,connection_id,connection_type,status,scopes_json,secret_ref,metadata_json,created_by,created_at",
    "oauth_authorization_requests": "company_id,store_id,oauth_request_id,platform,status,state_nonce,scopes_json,request_json,created_by,updated_at",
    "secret_refs": "company_id,store_id,secret_ref,provider,purpose,status,created_by,metadata_json",
    "audit_logs": "company_id,store_id,actor_type,user_id,created_at,audit_json,action_type,target_type,target_id",
}
_BASE_KEYS = {"team_members": ("company_id", "user_id"), "users": ("user_id",), "stores": ("store_id",),
              "platform_connections": ("connection_id",), "oauth_authorization_requests": ("oauth_request_id",),
              "secret_refs": ("secret_ref",), "audit_logs": ("audit_id",)}


class _Unavailable(Exception):
    pass


class _BorrowedConnection:
    """Nested service contexts cannot commit, close or start a second transaction."""
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def close(self):
        pass

    def execute(self, sql, parameters=()):
        if sql.strip().lower() == "begin immediate":
            # The application alone owns the existing IMMEDIATE write transaction.
            if not self._connection.in_transaction:
                raise RuntimeError("support_transaction_missing")
            return self._connection.execute("select 1")
        return self._connection.execute(sql, parameters)


class _RepositoryView:
    """Only the service's required interface; no initialize/approval/send proxy."""
    def __init__(self, connection, db_path, *, database_engine="sqlite", write=False):
        self._borrowed = _BorrowedConnection(connection)
        self.db_path = db_path
        self.database_engine = database_engine
        self._lock = database_engine == "postgres" and write

    def _connect(self):
        return self._borrowed

    def get_store_for_company(self, *, company_id, store_id):
        row = self._borrowed.execute("select store_json from stores where company_id=? and store_id=?" +
                                     (" for share" if self._lock else ""),
                                     (company_id, store_id)).fetchone()
        if not row:
            return None
        value = row["store_json"]
        return value if isinstance(value, dict) else json.loads(value)

    def get_team_member(self, *, company_id, user_id):
        row = self._borrowed.execute("select tm.role,u.status from team_members tm join users u on u.user_id=tm.user_id "
            "where tm.company_id=? and tm.user_id=?" + (" for share of tm,u" if self._lock else ""),
            (company_id, user_id)).fetchone()
        return dict(row) if row and row["status"] == "active" else None

    def get_support_connection_boundary(self, *, company_id, store_id):
        if self._lock:
            # Hold existing bound metadata through a cache mutation. No token is
            # resolved; new requests always derive and check the boundary again.
            self._borrowed.execute("select connection_id from platform_connections where company_id=? and store_id=? "
                "and lower(platform)='ebay' order by connection_id for share", (company_id, store_id)).fetchall()
            boundary = SaaSRepository.get_support_connection_boundary(self, company_id=company_id, store_id=store_id)
            binding = boundary.get("internal") or {}
            if not boundary.get("connection_bound"):
                return boundary
            for table, key, value in (("oauth_authorization_requests", "oauth_request_id", binding.get("oauth_request_id")),
                                     ("secret_refs", "secret_ref", binding.get("secret_ref"))):
                self._borrowed.execute(f"select {key} from {table} where company_id=? and store_id=? and {key}=? for share",
                    (company_id, store_id, value)).fetchall()
            self._borrowed.execute("select audit_id from audit_logs where company_id=? and store_id=? "
                "and action_type='oauth.callback.received' and target_type='oauth_authorization_request' "
                "and target_id=? order by audit_id for share", (company_id, store_id, binding.get("oauth_request_id"))).fetchall()
        return SaaSRepository.get_support_connection_boundary(self, company_id=company_id, store_id=store_id)


def _postgres_schema_probe(connection):
    """Check physical public objects on every request, independent of ledger."""
    try:
        tables = {**{table: (key, ()) for table, key in _BASE_KEYS.items()}, **_SUPPORT_SCHEMA}
        for table, (key, rest) in tables.items():
            columns = _BASE_COLUMNS.get(table, ",".join(key + rest))
            # Acquire the relation read lock before catalog checks, protecting
            # against incompatible ordinary ALTER/DROP in this transaction.
            connection.execute(f"select {columns} from public.{table} limit 0")
            constraints = connection.execute("""select con.contype::text as kind,
                    array_agg(att.attname::text order by k.ordinality) as columns
                from pg_catalog.pg_constraint con
                join pg_catalog.pg_class rel on rel.oid=con.conrelid
                join pg_catalog.pg_namespace ns on ns.oid=rel.relnamespace
                join pg_catalog.pg_index ix on ix.indexrelid=con.conindid
                cross join lateral unnest(con.conkey) with ordinality as k(attnum,ordinality)
                join pg_catalog.pg_attribute att on att.attrelid=rel.oid and att.attnum=k.attnum and not att.attisdropped
                where ns.nspname='public' and rel.relname=? and con.contype in ('p','u')
                  and con.convalidated and not con.condeferrable and ix.indisvalid and ix.indisready
                group by con.oid,con.contype""", (table,)).fetchall()
            if [tuple(row["columns"]) for row in constraints if row["kind"] == "p"] != [key]:
                raise _Unavailable("support_schema_not_ready")
            if table not in _SUPPORT_SCHEMA:
                continue
            columns = {row["column_name"]: row for row in connection.execute("""select column_name,udt_name,is_nullable,column_default
                from information_schema.columns where table_schema='public' and table_name=?""", (table,)).fetchall()}
            if set(columns) != set(key + rest):
                raise _Unavailable("support_schema_not_ready")
            for name in key + rest:
                row = columns[name]
                if (row["udt_name"] != ("int4" if name in {"revision", "truncated", "sync_generation"} else "text")
                        or row["is_nullable"] != ("YES" if name == "last_success_at" else "NO")):
                    raise _Unavailable("support_schema_not_ready")
            if table == "support_sync_v1":
                for name, default in (("current_message_ids_text", "'[]'::text"),
                                      ("current_message_hashes_text", "'{}'::text"), ("sync_generation", "0")):
                    if columns[name]["column_default"] != default:
                        raise _Unavailable("support_schema_not_ready")
            if table == "support_send_intents_v1":
                actual = {tuple(row["columns"]) for row in constraints if row["kind"] == "u"}
                if actual != {_PREFIX + ("confirmation_id",), _PREFIX + ("conversation_id", "source_message_id")}:
                    raise _Unavailable("support_schema_not_ready")
        for name, table, keys, options in (
                ("idx_support_messages_scope_order", "support_messages_v1", _PREFIX + ("conversation_id", "created_at", "message_id"), [0, 0, 0, 0, 0, 0]),
                ("idx_support_sync_scope_order", "support_sync_v1", _PREFIX + ("attempted_at", "conversation_id"), [0, 0, 0, 3, 0])):
            rows = connection.execute("""select am.amname,ix.indisvalid,ix.indisready,ix.indnkeyatts,
                    ix.indpred is null as no_predicate,ix.indexprs is null as no_expression,
                    ix.indoption::smallint[] as options,
                    array(select att.attname::text from unnest(ix.indkey) with ordinality as k(attnum,ordinality)
                      join pg_catalog.pg_attribute att on att.attrelid=rel.oid and att.attnum=k.attnum and not att.attisdropped
                      order by k.ordinality) as columns
                from pg_catalog.pg_index ix join pg_catalog.pg_class idx on idx.oid=ix.indexrelid
                join pg_catalog.pg_class rel on rel.oid=ix.indrelid
                join pg_catalog.pg_namespace ns on ns.oid=rel.relnamespace
                join pg_catalog.pg_am am on am.oid=idx.relam
                where ns.nspname='public' and idx.relname=? and rel.relname=?""", (name, table)).fetchall()
            if len(rows) != 1:
                raise _Unavailable("support_schema_not_ready")
            row = rows[0]
            if not (row["amname"] == "btree" and row["indisvalid"] and row["indisready"] and row["no_predicate"]
                    and row["no_expression"] and row["indnkeyatts"] == len(keys)
                    and tuple(row["columns"]) == keys and list(row["options"]) == options):
                raise _Unavailable("support_schema_not_ready")
    except _Unavailable:
        raise
    except Exception:
        # Fail closed on missing/altered objects or driver errors without leaking
        # DSNs or SQL values. Never repair a schema from an HTTP request.
        raise _Unavailable("support_schema_not_ready") from None


def _schema_probe(connection):
    """Existing-schema check, never a migration or proof of production compatibility."""
    try:
        for table, columns in _BASE_COLUMNS.items():
            connection.execute(f"select {columns} from {table} limit 0")
            rows = connection.execute(f"pragma table_info({table})").fetchall()
            actual_key = tuple(row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"])
            if actual_key != _BASE_KEYS[table]:
                raise _Unavailable("support_schema_not_ready")
        for table, (key, rest) in _SUPPORT_SCHEMA.items():
            rows = connection.execute(f"pragma table_info({table})").fetchall()
            columns = {row["name"]: row for row in rows}
            if not set(key + rest) <= set(columns):
                raise _Unavailable("support_schema_not_ready")
            actual_key = tuple(row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"])
            if actual_key != key:
                raise _Unavailable("support_schema_not_ready")
            for name in key + rest:
                expected_type = "INTEGER" if name in {"revision", "truncated", "sync_generation"} else "TEXT"
                if columns[name]["type"].upper() != expected_type or (name != "last_success_at" and not columns[name]["notnull"]):
                    raise _Unavailable("support_schema_not_ready")
            if table == "support_sync_v1" and str(columns["sync_generation"]["dflt_value"]) != "0":
                raise _Unavailable("support_schema_not_ready")
        indices = connection.execute("pragma index_list(support_send_intents_v1)").fetchall()
        unique_keys = set()
        for index in indices:
            if index["unique"] and not index["partial"]:
                name = str(index["name"]).replace('"', '""')
                unique_keys.add(tuple(row["name"] for row in connection.execute(f'pragma index_info("{name}")').fetchall()))
        if not {_PREFIX + ("confirmation_id",), _PREFIX + ("conversation_id", "source_message_id")} <= unique_keys:
            raise _Unavailable("support_schema_not_ready")
    except sqlite3.DatabaseError:
        raise _Unavailable("support_schema_not_ready") from None


def _valid_id(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) is not None


def _payload(payload, required, optional=()):
    # Positive schema: identity/owner/ref/token/mode/read/send switches cannot enter.
    if type(payload) is not dict or not set(required) <= set(payload) or set(payload) - set(required) - set(optional):
        raise ValueError("support_payload_not_allowed")
    return dict(payload)


def _text(value, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError("support_text_invalid")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise ValueError("support_text_invalid") from None
    return value


@dataclass(frozen=True)
class SupportActorContext:
    """Server-authenticated identifiers; never construct directly from request JSON."""
    actor_id: str
    company_id: str
    store_id: str


def _blocked(code):
    return {"status": "blocked", "blocked_by": [code], "send_enabled": False,
            "automatic_send_allowed": False, "live_end_to_end_verified": False,
            "external_request_performed": False, "schema_write_performed": False,
            "secret_exposed": False}


class SupportApplication:
    def __init__(self, repository, *, enabled=False, sync_enabled=False, resolver=None, settings=None,
                 ai_enabled=False, ai_knowledge_loader=None, ai_model_factory=None):
        self._repository = repository
        self._enabled = enabled is True
        self._sync_enabled = sync_enabled is True
        # Server dependencies only; an HTTP factory must not deserialize these.
        self._resolver = resolver
        self._settings = replace(settings) if type(settings) is SaaSSettings else None
        self._ai_enabled = ai_enabled is True
        self._ai_knowledge_loader = ai_knowledge_loader
        self._ai_model_factory = ai_model_factory

    @contextmanager
    def _database_session(self, *, write=False):
        if self._repository.database_engine == "postgres":
            try:
                connection = self._repository._connect()
            except Exception:
                raise _Unavailable("support_database_unavailable") from None
            # The adapter context alone owns commit/rollback and pooled release.
            # All nested service/repository contexts receive a borrowed view.
            with connection:
                connection.execute("set transaction isolation level read committed, read write" if write else
                                   "set transaction isolation level repeatable read, read only")
                connection.execute("set local search_path = pg_catalog, public, pg_temp")
                _postgres_schema_probe(connection)
                yield _RepositoryView(connection, self._repository.db_path, database_engine="postgres", write=write)
            return
        if self._repository.database_engine != "sqlite":
            raise _Unavailable("support_database_not_supported")
        path = Path(self._repository.db_path)
        if not path.is_file():
            raise _Unavailable("support_schema_not_ready")
        connection = sqlite3.connect(path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("begin immediate" if write else "begin")
            _schema_probe(connection)
            yield _RepositoryView(connection, path)
            if write:
                connection.commit()
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    @contextmanager
    def _session(self, context, *, write=False):
        if not self._enabled:
            raise _Unavailable("support_application_disabled")
        if type(context) is not SupportActorContext or not all(_valid_id(value) for value in
                (context.actor_id, context.company_id, context.store_id)):
            raise PermissionError("support_actor_context_required")
        with self._database_session(write=write) as view:
            member = view.get_team_member(company_id=context.company_id, user_id=context.actor_id)
            if not member or member["role"] not in _ROLES:
                raise PermissionError("support_actor_not_authorized")
            if not view.get_store_for_company(company_id=context.company_id, store_id=context.store_id):
                raise PermissionError("support_store_not_accessible")
            boundary = view.get_support_connection_boundary(company_id=context.company_id, store_id=context.store_id)
            if (boundary.get("contract_version") != "2026-10-12-support-connection-boundary-v1"
                    or boundary.get("connection_bound") is not True
                    or set(boundary.get("blocked_by") or ()) - {"support_message_scope_missing", "support_message_scope_unverified"}):
                raise _Unavailable("support_connection_unavailable")
            binding = boundary.get("internal") or {}
            if (binding.get("company_id") != context.company_id or binding.get("store_id") != context.store_id
                    or binding.get("owner_binding_kind") != "sha256_casefold_ebay_username"):
                raise _Unavailable("support_connection_unavailable")
            scope = MessageScope(context.company_id, context.store_id, binding.get("owner_username_hash"),
                                 owner_binding_kind="sha256_casefold_ebay_username")
            yield SupportConversations(view, scope), binding

    def capability(self, context):
        try:
            with self._session(context):
                return {"status": "local_cache_available", "cache_available": True,
                        "credentials_verified": False, "requires_live_owner_check": True,
                        "send_enabled": False, "automatic_send_allowed": False,
                        "live_end_to_end_verified": False, "external_request_performed": False,
                        "schema_write_performed": False, "secret_exposed": False}
        except _Unavailable as exc:
            return _blocked(str(exc))

    def list_conversations(self, context, *, limit=25, offset=0):
        try:
            with self._session(context) as (service, _):
                result = service.list_conversations(limit=limit, offset=offset)
                return {"conversations": [{key: item[key] for key in
                    ("conversation_id", "sync_status", "attempted_at", "last_success_at", "truncated")}
                    for item in result["conversations"]], "has_more": result["has_more"],
                    "external_request_performed": False, "send_enabled": False}
        except _Unavailable as exc:
            return _blocked(str(exc))

    def get_conversation(self, context, conversation_id, *, limit=50, offset=0):
        if not _valid_id(conversation_id):
            raise ValueError("invalid_conversation_id")
        self._message_page_bounds(limit, offset)
        try:
            with self._session(context) as (service, _):
                return self._snapshot(service, service.read_snapshot(conversation_id), limit=limit, offset=offset)
        except _Unavailable as exc:
            return _blocked(str(exc))

    def create_draft(self, context, payload):
        values = _payload(payload, ("conversation_id", "source_message_id", "body"), ("fact_refs",))
        if not all(_valid_id(values[key]) for key in ("conversation_id", "source_message_id")):
            raise ValueError("support_message_id_invalid")
        body = _text(values["body"], 2000)
        facts = values.get("fact_refs", [])
        if type(facts) is not list or len(facts) > 30:
            raise ValueError("support_fact_refs_invalid")
        facts = [_text(value, 200) for value in facts]
        try:
            with self._session(context, write=True) as (service, _):
                return self._draft(service.create_draft(values["conversation_id"], values["source_message_id"],
                    body=body, actor_id=context.actor_id, fact_refs=facts))
        except _Unavailable as exc:
            return _blocked(str(exc))

    def _ai_turn(self, context, service, conversation_id):
        """Load only a complete, current owner-bound conversation and its facts.

        The loader is a trusted backend dependency. No fallback to the latest
        store product, buyer-mentioned title or browser-selected project exists.
        An eventual live loader must resolve/lock versioned product and policy
        records; this local slice does not enable an HTTP or automated sender.
        """
        if not callable(self._ai_knowledge_loader):
            raise ValueError("support_knowledge_unavailable")
        knowledge = self._ai_knowledge_loader(context=context, scope=service.scope,
                                               conversation_id=conversation_id)
        if (type(knowledge) is not SupportKnowledge or knowledge.scope != service.scope
                or knowledge.conversation_id != conversation_id):
            raise ValueError("support_product_binding_required")
        snapshot = service.read_snapshot(conversation_id)
        ids = snapshot["current_message_ids"]
        if (snapshot["sync_status"] != "ok" or snapshot["truncated"] or not ids
                or len(set(ids)) != len(ids)):
            raise ValueError("complete_current_snapshot_required")
        messages = [row for row in snapshot["messages"] if row["messageId"] in ids]
        if len(messages) != len(ids) or any(snapshot["current_message_hashes"].get(row["messageId"])
                                          != message_hash(row) for row in messages):
            raise ValueError("support_message_snapshot_changed")
        if len({row["createdDate"] for row in messages}) != len(messages):
            raise ValueError("support_message_order_ambiguous")
        turn = SupportTurn(company_id=service.scope.company_id, store_id=service.scope.store_id,
            owner_id=service.scope.owner_storage_key, conversation_id=conversation_id,
            source_message_id=messages[-1]["messageId"], product_binding=knowledge.product_binding,
            policy_version=knowledge.policy_version, fact_version=knowledge.fact_version, complete=True,
            messages=tuple(SupportMessage(row["messageId"], "incoming" if service.scope.is_incoming_message(
                row["senderUsername"], row["recipientUsername"]) else "outgoing", row["messageBody"])
                for row in messages), facts=knowledge.facts)
        _validate_turn(turn)
        return turn

    def propose_ai_reply(self, context, payload):
        """Local AI-to-reviewed-draft slice; does not approve or send a reply."""
        values = _payload(payload, ("conversation_id",))
        conversation_id = values["conversation_id"]
        if not _valid_id(conversation_id):
            raise ValueError("invalid_conversation_id")
        if not self._enabled:
            return _blocked("support_application_disabled")
        if not self._ai_enabled:
            return _blocked("support_ai_disabled")
        try:
            with self._session(context) as (service, initial_binding):
                try:
                    turn = self._ai_turn(context, service, conversation_id)
                except (ValueError, TypeError, AttributeError, UnicodeError):
                    return ai_result("human_required", ["invalid_or_incomplete_context"])
            if not callable(self._ai_model_factory):
                return ai_result("human_required", ["model_unavailable"])
            try:
                model = self._ai_model_factory(context=context)
            except Exception:
                return ai_result("human_required", ["model_unavailable"])
            # No database transaction is held while awaiting a model provider.
            decision = decide_support_reply(model_client=model, turn=turn)
            if decision["status"] != "reply_candidate":
                return decision
            with self._session(context, write=True) as (service, binding):
                try:
                    current_turn = self._ai_turn(context, service, conversation_id)
                except (ValueError, TypeError, AttributeError, UnicodeError):
                    raise _Unavailable("support_ai_context_changed") from None
                if binding != initial_binding or current_turn != turn:
                    raise _Unavailable("support_ai_context_changed")
                draft = service.create_draft(conversation_id, turn.source_message_id,
                    body=decision["body"], actor_id=context.actor_id, fact_refs=decision["evidence_keys"],
                    ai_review={"binding_hash": decision["binding_hash"], "fact_version": turn.fact_version,
                        "policy_version": turn.policy_version, "product_binding": turn.product_binding,
                        "contract_version": decision["contract_version"]})
                return {**decision, "draft": self._draft(draft)}
        except _Unavailable as exc:
            return _blocked(str(exc))

    def sync(self, context, payload):
        values = _payload(payload, ("conversation_id",), ("limit", "max_pages"))
        conversation_id = values["conversation_id"]
        if not _valid_id(conversation_id):
            raise ValueError("invalid_conversation_id")
        limit, pages = values.get("limit", 25), values.get("max_pages", 1)
        if type(limit) is not int or not 1 <= limit <= 50 or type(pages) is not int or not 1 <= pages <= 3:
            raise ValueError("invalid_pagination_bound")
        if not self._enabled:
            return _blocked("support_application_disabled")
        if not self._sync_enabled:
            return _blocked("support_sync_disabled")
        resolver = self._resolver
        if resolver is None and self._settings is not None:
            # Authenticate/revalidate the exact store before constructing any
            # credential dependency. No request field can supply a resolver.
            try:
                with self._session(context):
                    pass
            except _Unavailable as exc:
                return _blocked(str(exc))
            from .support_credential_adapters import build_support_resolver
            resolver = build_support_resolver(self._repository, self._settings,
                company_id=context.company_id, store_id=context.store_id, enabled=self._sync_enabled)
        if (type(resolver) is not SupportTokenResolver or resolver.repository is not self._repository
                or resolver.verification_enabled is not True):
            return _blocked("support_trusted_resolver_required")
        message_attempted = False
        verification_attempted = False
        try:
            with self._session(context, write=True) as (service, initial_binding):
                scope = service.scope
                generation = service.begin_sync(conversation_id)
            verification_attempted = True
            resolution = resolver.resolve(company_id=context.company_id, store_id=context.store_id)
            verified = resolution.public_result()["credentials_verified"] is True and resolution.scope == scope

            def checked_token(message_scope):
                # Each paginated GET rechecks actor + exact connection before credentials.
                with self._session(context) as (current, binding):
                    if (binding != initial_binding or current.scope != message_scope
                            or not current.sync_attempt_is_current(conversation_id, generation)):
                        return {"ok": False, "status": "support_context_changed"}
                    return resolution.token_provider(message_scope)

            if verified:
                adapter = EbayMessageAdapter(scope, token_provider=checked_token,
                                             read_enabled=True, send_enabled=False)
                # Record actual message HTTP attempts, not token verification as message I/O.
                original_transport = adapter.transport
                def observe_transport(request, timeout):
                    nonlocal message_attempted
                    message_attempted = True
                    return original_transport(request, timeout)
                adapter.transport = observe_transport
                incoming = adapter.get_conversation(conversation_id, limit=limit, max_pages=pages)
            else:
                incoming = {"scope": scope.as_dict(), "conversation_id": conversation_id,
                            "status": "credential_verification_failed", "messages": None}
            # Network is outside the DB transaction. A revoked actor or replaced
            # connection cannot persist or receive even a successful late response.
            with self._session(context, write=True) as (service, binding):
                if binding != initial_binding or service.scope != scope:
                    raise _Unavailable("support_context_changed")
                if not service.sync_attempt_is_current(conversation_id, generation):
                    raise _Unavailable("support_sync_superseded")
                public = self._snapshot(service, service.ingest(incoming, expected_generation=generation))
            return {**public, "external_request_performed": True if message_attempted else None,
                    "buyer_message_http_attempted": message_attempted,
                    "credential_verification_attempted": verification_attempted}
        except _Unavailable as exc:
            # Resolver attempts may perform credential HTTP that this facade
            # cannot observe. Unknown is not a claim of zero external traffic.
            return {**_blocked(str(exc)), "external_request_performed": True if message_attempted else None if verification_attempted else False,
                    "buyer_message_http_attempted": message_attempted,
                    "credential_verification_attempted": verification_attempted}

    def discover(self, context, payload):
        """Explicit bounded incoming discovery, including when cache is empty.

        Only return validated IDs/cursor. List summaries are not owner-verified
        message snapshots and cannot be ingested or replied to. Detail sync must
        still pass its existing generation/owner guards. No polling or writes.
        """
        values = _payload(payload, (), ("limit", "max_pages", "offset"))
        limit, pages, offset = values.get("limit", 25), values.get("max_pages", 1), values.get("offset", 0)
        if (type(limit) is not int or not 1 <= limit <= 50 or type(pages) is not int or not 1 <= pages <= 3
                or type(offset) is not int or not 0 <= offset <= 10000):
            raise ValueError("invalid_pagination_bound")
        if not self._enabled:
            return _blocked("support_application_disabled")
        if not self._sync_enabled:
            return _blocked("support_sync_disabled")
        message_attempted = verification_attempted = False
        try:
            with self._session(context) as (service, initial_binding):
                scope = service.scope
            resolver = self._resolver
            if resolver is None and self._settings is not None:
                from .support_credential_adapters import build_support_resolver
                resolver = build_support_resolver(self._repository, self._settings,
                    company_id=context.company_id, store_id=context.store_id, enabled=True)
            if (type(resolver) is not SupportTokenResolver or resolver.repository is not self._repository
                    or resolver.verification_enabled is not True):
                return _blocked("support_trusted_resolver_required")
            verification_attempted = True
            resolution = resolver.resolve(company_id=context.company_id, store_id=context.store_id)
            if resolution.public_result()["credentials_verified"] is not True or resolution.scope != scope:
                raise _Unavailable("support_credential_verification_failed")

            def checked_token(message_scope):
                with self._session(context) as (current, binding):
                    if binding != initial_binding or current.scope != message_scope:
                        return {"ok": False, "status": "support_context_changed"}
                    return resolution.token_provider(message_scope)

            adapter = EbayMessageAdapter(scope, token_provider=checked_token, read_enabled=True, send_enabled=False)
            transport = adapter.transport
            def observed_transport(request, timeout):
                nonlocal message_attempted
                message_attempted = True
                return transport(request, timeout)
            adapter.transport = observed_transport
            incoming = adapter.get_conversations(limit=limit, max_pages=pages, offset=offset)
            with self._session(context) as (current, binding):
                if binding != initial_binding or current.scope != scope:
                    raise _Unavailable("support_context_changed")
                if incoming.get("status") != "ok" or incoming.get("scope") != scope.as_dict():
                    raise _Unavailable("support_discovery_unavailable")
                # Defense-in-depth projection; raw summaries can include buyer
                # identities/media URLs and never cross this application boundary.
                entries = incoming.get("conversations")
                if type(entries) is not list or any(type(item) is not dict
                        or not _valid_id(item.get("conversationId")) for item in entries):
                    raise _Unavailable("support_discovery_unavailable")
                ids = list(dict.fromkeys(item["conversationId"] for item in entries))
                return {"status": "discovered", "conversation_ids": ids,
                    "has_more": incoming["truncated"], "next_offset": incoming["next_offset"],
                    "external_request_performed": message_attempted, "buyer_message_http_attempted": message_attempted,
                    "credential_verification_attempted": True, "send_enabled": False,
                    "automatic_send_allowed": False, "schema_write_performed": False}
        except _Unavailable as exc:
            return {**_blocked(str(exc)), "external_request_performed": True if message_attempted else None if verification_attempted else False,
                    "buyer_message_http_attempted": message_attempted,
                    "credential_verification_attempted": verification_attempted}

    def edit_draft(self, context, draft_id, payload):
        values = _payload(payload, ("expected_revision", "body"))
        if not _valid_id(draft_id):
            raise ValueError("support_draft_id_invalid")
        body = _text(values["body"], 2000)
        if type(values["expected_revision"]) is not int or values["expected_revision"] < 1:
            raise ValueError("draft_revision_conflict")
        try:
            with self._session(context, write=True) as (service, _):
                return self._draft(service.edit_draft(draft_id, expected_revision=values["expected_revision"],
                    body=body, actor_id=context.actor_id))
        except _Unavailable as exc:
            return _blocked(str(exc))

    def preview_confirmation(self, context, draft_id):
        """Prepare the real service item, but do not persist, approve or expose binding."""
        if not _valid_id(draft_id):
            raise ValueError("support_draft_id_invalid")
        try:
            with self._session(context) as (service, _):
                item = service.prepare_confirmation(draft_id)
                return {"status": "preview_only", "confirmation_created": False, "approved": False,
                        "send_enabled": False, "automatic_send_allowed": False,
                        "message_body": item["message_body"], "risk_flags": list(item["risk_flags"]),
                        "facts_verified": False, "fact_reference_status": item["fact_reference_status"],
                        "default_action": "hold", "integration_pending": "trusted_confirmation_creation_and_execution"}
        except _Unavailable as exc:
            return _blocked(str(exc))

    @staticmethod
    def _draft(draft):
        return {**{key: draft[key] for key in ("draft_id", "revision", "conversation_id", "source_message_id",
                    "body", "fact_refs", "created_at", "status", "generation_kind")},
                "facts_verified": False, "send_enabled": False}

    @staticmethod
    def _message_page_bounds(limit, offset):
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or not 0 <= offset <= 2147483647):
            raise ValueError("invalid_cached_message_pagination")

    @staticmethod
    def _snapshot(service, snapshot, *, limit=50, offset=0):
        SupportApplication._message_page_bounds(limit, offset)
        # The domain snapshot retains complete, canonically ordered history for
        # confirmation checks (including legacy timestamps). Only its public
        # projection is paged; do not delete records or confuse this with an
        # incomplete upstream synchronization. Explicit sync uses this same
        # bounded response and never returns thousands of messages at once.
        page = snapshot["messages"][offset:offset + limit]
        has_more = offset + len(page) < len(snapshot["messages"])
        return {"conversation_id": snapshot["conversation_id"], "sync_status": snapshot["sync_status"],
                "last_success_at": snapshot["last_success_at"], "truncated": snapshot["truncated"],
                "message_offset": offset, "message_limit": limit, "has_more": has_more,
                "next_offset": offset + len(page) if has_more else None,
                "messages": [{"message_id": message["messageId"], "body": message["messageBody"],
                    "created_at": message["createdDate"], "direction": "incoming" if service.scope.is_incoming_message(
                        message["senderUsername"], message["recipientUsername"]) else "outgoing"}
                    for message in page], "external_request_performed": False, "send_enabled": False}
