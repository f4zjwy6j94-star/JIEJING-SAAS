"""Tenant-scoped merchant edit persistence, independent of AI reports and publication."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager

from jiejing_runtime.models import now_iso
from .json_safe import json_default
from .sensitive_text import contains_secret_like_data

CONTRACT_VERSION = "listing_merchant_edit_v1"
FIELD_KEYS = ("title", "selling_points", "description", "category", "item_specifics",
              "keywords", "price", "images", "logistics", "risk_notes")
IDENTITY_KEYS = ("key", "source_report_id", "candidate_id")
SAFETY = {"model_called": False, "usage_consumed": False,
          "real_platform_writes_enabled": False, "secret_exposed": False}


class CheckpointValidationError(ValueError):
    def __init__(self, code="listing_draft_invalid_request", status=400):
        super().__init__(code)
        self.status = status


class CheckpointConflict(Exception):
    def __init__(self, payload):
        super().__init__(payload["error_code"])
        self.payload = payload


def normalize_identity(value):
    if not isinstance(value, dict) or set(value) != set(IDENTITY_KEYS):
        raise CheckpointValidationError()
    for key, limit in (("key", 160), ("source_report_id", 160), ("candidate_id", 120)):
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or (not text and key == "key"):
            raise CheckpointValidationError()
        if text and not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
            raise CheckpointValidationError()
    return {key: value[key] for key in IDENTITY_KEYS}


def _request(project_key, body):
    keys = {"contract_version", "listing_project_identity", "base_report_id", "expected_revision",
            "mutation_id", "fields", "merchant_edited_fields"}
    if not isinstance(body, dict) or set(body) != keys or body["contract_version"] != CONTRACT_VERSION:
        raise CheckpointValidationError()
    identity = normalize_identity(body["listing_project_identity"])
    if identity["key"] != project_key:
        raise CheckpointValidationError()
    for key, lower in (("base_report_id", 1), ("mutation_id", 8)):
        value = body[key]
        if not isinstance(value, str) or not re.fullmatch(rf"[A-Za-z0-9._:-]{{{lower},160}}", value):
            raise CheckpointValidationError()
    revision = body["expected_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or not 0 <= revision < 2147483647:
        raise CheckpointValidationError()
    fields = body["fields"]
    if not isinstance(fields, dict) or set(fields) != set(FIELD_KEYS):
        raise CheckpointValidationError()
    for key, value in fields.items():
        if not isinstance(value, str) or len(value) > (1400 if key in ("description", "selling_points") else 800):
            raise CheckpointValidationError()
        if "\x00" in value:
            raise CheckpointValidationError()
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise CheckpointValidationError() from None
    edited = body["merchant_edited_fields"]
    if not isinstance(edited, list) or len(edited) > len(FIELD_KEYS) or any(
            not isinstance(key, str) or key not in FIELD_KEYS for key in edited):
        raise CheckpointValidationError()
    if contains_secret_like_data(body):
        raise CheckpointValidationError("listing_draft_sensitive_text", 422)
    return {**body, "listing_project_identity": identity, "fields": dict(fields),
            "merchant_edited_fields": sorted(set(edited))}


def _decode(value):
    return json.loads(value) if isinstance(value, str) else value


@contextmanager
def _connection(repository):
    conn = repository._connect()
    try:
        with conn:
            yield conn
    finally:
        # The Postgres adapter returns its pool lease on context exit; sqlite does not close itself.
        if repository.database_engine != "postgres":
            conn.close()


def _scope(conn, company_id, store_id):
    if not conn.execute("select store_id from stores where company_id = ? and store_id = ?",
                        (company_id, store_id)).fetchone():
        raise KeyError("listing_draft_not_found")


def _base(repository, conn, company_id, store_id, identity):
    def field(key):
        if repository.database_engine == "postgres":
            return f"r.report_json -> 'listing_project_identity' ->> '{key}'"
        return f"json_extract(r.report_json, '$.listing_project_identity.{key}')"
    predicates = " and ".join(f"({field(key)}) = ?" for key in IDENTITY_KEYS)
    row = conn.execute(
        f"""select r.*, t.company_id, t.store_id from reports r
        join tasks t on t.task_id = r.task_id
        where t.company_id = ? and t.store_id = ? and r.status = 'saved'
          and r.report_type in ('listing.package','product.listing','merchant.product_facts','ai_ceo.market_research')
          and {predicates}
        order by case when r.report_type = 'ai_ceo.market_research' then 1 else 0 end,
          r.created_at desc, r.report_id desc limit 1""",
        (company_id, store_id, *(identity[key] for key in IDENTITY_KEYS)),
    ).fetchone()
    if not row:
        raise KeyError("listing_draft_not_found")
    return repository._report_row_to_dict(row)


def _view(repository, conn, company_id, store_id, identity):
    row = conn.execute(
        """select r.receipt_json from listing_draft_edit_heads h
        join listing_draft_edit_revisions r on r.checkpoint_id = h.checkpoint_id
        where h.company_id = ? and h.store_id = ? and h.project_key = ?""",
        (company_id, store_id, identity["key"]),
    ).fetchone()
    checkpoint = _decode(row["receipt_json"]) if row else None
    if checkpoint and checkpoint["listing_project_identity"] != identity:
        raise KeyError("listing_draft_not_found")
    base = _base(repository, conn, company_id, store_id, identity)
    return {"contract_version": CONTRACT_VERSION, "status": "saved" if checkpoint else "empty",
            "checkpoint": checkpoint, "current_revision": checkpoint["revision"] if checkpoint else 0,
            "current_base_report_id": base["report_id"], "current_base_report": base,
            "base_changed": bool(checkpoint and checkpoint["base_report_id"] != base["report_id"]), **SAFETY}


def read_checkpoint(repository, *, company_id, store_id, identity):
    identity = normalize_identity(identity)
    repository.initialize()
    with _connection(repository) as conn:
        _scope(conn, company_id, store_id)
        return _view(repository, conn, company_id, store_id, identity)


def _conflict(repository, conn, company_id, store_id, identity, body, code):
    view = _view(repository, conn, company_id, store_id, identity)
    raise CheckpointConflict({"contract_version": CONTRACT_VERSION, "status": "conflict", "error_code": code,
                              "expected_revision": body["expected_revision"],
                              "current_revision": view["current_revision"], "latest_checkpoint": view["checkpoint"],
                              "current_base_report_id": view["current_base_report_id"],
                              "current_base_report": view["current_base_report"], **SAFETY})


def save_checkpoint(repository, *, company_id, store_id, user_id, project_key, body):
    body = _request(project_key, body)
    repository.initialize()
    identity = body["listing_project_identity"]
    created_at = now_iso()
    checkpoint_id = "listing_edit_" + uuid.uuid4().hex
    fingerprint = hashlib.sha256(json.dumps({"user_id": user_id, "body": body}, sort_keys=True,
                                            ensure_ascii=False).encode()).hexdigest()
    with _connection(repository) as conn:
        if repository.database_engine != "postgres":
            conn.execute("begin immediate")
        _scope(conn, company_id, store_id)
        scope = (company_id, store_id, project_key)
        conn.execute("""insert into listing_draft_edit_heads
            (company_id,store_id,project_key,source_report_id,candidate_id,revision,checkpoint_id,updated_at)
            values (?,?,?,?,?,0,'',?) on conflict (company_id,store_id,project_key) do nothing""",
            (*scope, identity["source_report_id"], identity["candidate_id"], created_at))
        lock = " for update" if repository.database_engine == "postgres" else ""
        head = conn.execute("""select * from listing_draft_edit_heads
            where company_id = ? and store_id = ? and project_key = ?""" + lock, scope).fetchone()
        if head["source_report_id"] != identity["source_report_id"] or head["candidate_id"] != identity["candidate_id"]:
            raise KeyError("listing_draft_not_found")
        previous = conn.execute("""select payload_fingerprint,receipt_json from listing_draft_edit_revisions
            where company_id = ? and store_id = ? and project_key = ? and mutation_id = ?""",
            (*scope, body["mutation_id"])).fetchone()
        if previous:
            if previous["payload_fingerprint"] != fingerprint:
                _conflict(repository, conn, company_id, store_id, identity, body, "listing_draft_mutation_conflict")
            return {"contract_version": CONTRACT_VERSION, "status": "saved",
                    "checkpoint": _decode(previous["receipt_json"]), "idempotent_replay": True, **SAFETY}
        base = _base(repository, conn, company_id, store_id, identity)
        if base["report_id"] != body["base_report_id"]:
            _conflict(repository, conn, company_id, store_id, identity, body, "listing_draft_base_conflict")
        if head["revision"] != body["expected_revision"]:
            _conflict(repository, conn, company_id, store_id, identity, body, "listing_draft_revision_conflict")
        revision = head["revision"] + 1
        checkpoint = {"checkpoint_id": checkpoint_id, "revision": revision, "mutation_id": body["mutation_id"],
                      "company_id": company_id, "store_id": store_id, "listing_project_identity": identity,
                      "base_report_id": base["report_id"], "fields": body["fields"],
                      "merchant_edited_fields": body["merchant_edited_fields"], "saved_at": created_at,
                      "source": "merchant_edit"}
        conn.execute("""insert into listing_draft_edit_revisions
            (checkpoint_id,company_id,store_id,project_key,source_report_id,candidate_id,revision,
             mutation_id,payload_fingerprint,base_report_id,actor_user_id,created_at,receipt_json)
            values (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (checkpoint_id, company_id, store_id, project_key, identity["source_report_id"], identity["candidate_id"],
             revision, body["mutation_id"], fingerprint, base["report_id"], user_id, created_at,
             json.dumps(checkpoint, ensure_ascii=False, default=json_default)))
        changed = conn.execute("""update listing_draft_edit_heads set revision = ?, checkpoint_id = ?, updated_at = ?
            where company_id = ? and store_id = ? and project_key = ? and revision = ? returning checkpoint_id""",
            (revision, checkpoint_id, created_at, *scope, body["expected_revision"])).fetchone()
        if not changed:
            _conflict(repository, conn, company_id, store_id, identity, body, "listing_draft_revision_conflict")
        repository._insert_audit(conn, company_id=company_id, store_id=store_id, user_id=user_id,
                                 actor_type="user", action_type="listing.merchant_edit.saved",
                                 target_type="listing_checkpoint", target_id=checkpoint_id,
                                 summary="Merchant Listing edits saved without model or platform execution.",
                                 details={"revision": revision, **SAFETY})
    return {"contract_version": CONTRACT_VERSION, "status": "saved", "checkpoint": checkpoint,
            "idempotent_replay": False, **SAFETY}
