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
PUBLISH_INTAKE_KEYS = (
    "product", "sku", "title", "condition", "category_id", "category_leaf", "price", "currency", "quantity",
    "merchant_location_key", "inventory_location_key", "inventory_location_name", "inventory_location_city",
    "inventory_location_state", "inventory_location_country", "item_location", "package_weight_g", "package_length_cm",
    "package_width_cm", "package_height_cm", "material", "procurement_cost", "shipping_cost", "ebay_fee", "ad_budget",
    "return_risk_reserve", "exchange_rate", "net_profit", "gross_margin_percent", "item_specifics", "image_urls",
    "description_html", "fulfillment_policy_id", "payment_policy_id", "return_policy_id",
)
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
    if (not isinstance(body, dict) or set(body) not in (keys, keys | {"publish_intake"})
            or body["contract_version"] != CONTRACT_VERSION):
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
    if "publish_intake" in body:
        _validate_publish_intake(body["publish_intake"])
    return {**body, "listing_project_identity": identity, "fields": dict(fields),
            "merchant_edited_fields": sorted(set(edited))}


def _validate_publish_intake(value):
    # Draft input only. Evidence, simulation flags and execution authority are
    # never accepted here and must still come from their authenticated sources.
    if not isinstance(value, dict) or set(value) != {"values", "basis"}:
        raise CheckpointValidationError()
    for fields in value.values():
        if not isinstance(fields, dict) or not set(fields).issubset(PUBLISH_INTAKE_KEYS):
            raise CheckpointValidationError()
        for key, text in fields.items():
            limit = 6000 if key in ("description_html", "image_urls", "item_specifics") else 800
            if not isinstance(text, str) or len(text) > limit or "\x00" in text:
                raise CheckpointValidationError()
            try:
                text.encode("utf-8")
            except UnicodeEncodeError:
                raise CheckpointValidationError() from None


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


def _scope(conn, company_id, store_id, *, lock=False):
    if not conn.execute("select store_id from stores where company_id = ? and store_id = ?" + (" for update" if lock else ""),
                        (company_id, store_id)).fetchone():
        raise KeyError("listing_draft_not_found")


def _base_candidate(repository, conn, company_id, store_id, identity, excluded_ids, *,
                    report_types=("listing.package", "product.listing", "merchant.product_facts", "ai_ceo.market_research")):
    def field(key):
        if repository.database_engine == "postgres":
            return f"r.report_json -> 'listing_project_identity' ->> '{key}'"
        return f"json_extract(r.report_json, '$.listing_project_identity.{key}')"
    predicates = " and ".join(f"({field(key)}) = ?" for key in IDENTITY_KEYS)
    # Compare instants, not offset-bearing SQLite text; new fact actions advance
    # primary reports by at least a millisecond. Postgres already uses timestamptz.
    order_time = "r.created_at" if repository.database_engine == "postgres" else "julianday(r.created_at)"
    exclusion = " and r.report_id not in (" + ",".join("?" for _ in excluded_ids) + ")" if excluded_ids else ""
    parameters = (company_id, store_id, *report_types, *(identity[key] for key in IDENTITY_KEYS))
    parameters += tuple(excluded_ids)
    row = conn.execute(
        f"""select r.*, t.company_id, t.store_id, t.user_id from reports r
        join tasks t on t.task_id = r.task_id
        where t.company_id = ? and t.store_id = ? and r.status = 'saved'
          and r.report_type in ({','.join('?' for _ in report_types)})
          and {predicates}{exclusion}
        order by case when r.report_type = 'ai_ceo.market_research' then 1 else 0 end,
          {order_time} desc, r.report_id desc limit 1""",
        parameters,
    ).fetchone()
    if not row:
        raise KeyError("listing_draft_not_found")
    return repository._report_row_to_dict(row)


def _rewrite_contract(base):
    report = base.get("report") if isinstance(base.get("report"), dict) else {}
    handoff = report.get("listing_handoff") if isinstance(report.get("listing_handoff"), dict) else {}
    fields = handoff.get("listing_fields") if isinstance(handoff.get("listing_fields"), dict) else {}
    if "buyer_copy_rewrite" not in fields:
        return None
    rewrite = fields["buyer_copy_rewrite"]
    return rewrite if isinstance(rewrite, dict) else {}


def _valid_rewrite_anchors(base, rewrite):
    return (rewrite.get("contract_version") == "listing_buyer_copy_rewrite_v1"
            and base.get("report_type") == "listing.package"
            and base.get("runtime_run_id") == "listing_draft_generation"
            and base.get("report", {}).get("contract_version") == "listing_ai_draft_generation_v1"
            and isinstance(rewrite.get("expected_base_report_id"), str)
            and re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", rewrite["expected_base_report_id"]) is not None
            and not isinstance(rewrite.get("expected_checkpoint_revision"), bool)
            and isinstance(rewrite.get("expected_checkpoint_revision"), int)
            and 0 <= rewrite["expected_checkpoint_revision"] < 2147483647)


def _base(repository, conn, company_id, store_id, identity, *, superseded=None):
    # An unadopted rewrite must not hide newer merchant facts/edits forever.
    # Keep its immutable report as history, but fall back to the valid source.
    # Walk only pending rewrite predecessors; the ordinary one-row path stays.
    excluded = []
    pending = []
    while True:
        base = _base_candidate(repository, conn, company_id, store_id, identity, excluded)
        rewrite = _rewrite_contract(base)
        if rewrite is None:
            break
        adopted = conn.execute("""select checkpoint_id from listing_draft_edit_revisions
            where company_id = ? and store_id = ? and project_key = ? and source_report_id = ?
              and candidate_id = ? and base_report_id = ? limit 1""",
            (company_id, store_id, *(identity[key] for key in IDENTITY_KEYS), base["report_id"])).fetchone()
        if adopted:
            break
        pending.append((base, rewrite))
        excluded.append(base["report_id"])
    if pending:
        head = conn.execute("""select revision from listing_draft_edit_heads
            where company_id = ? and store_id = ? and project_key = ? and source_report_id = ? and candidate_id = ?""",
            (company_id, store_id, *(identity[key] for key in IDENTITY_KEYS))).fetchone()
        revision = head["revision"] if head else 0
        for candidate, rewrite in reversed(pending):
            if (_valid_rewrite_anchors(candidate, rewrite)
                and rewrite["expected_checkpoint_revision"] == revision
                and rewrite["expected_base_report_id"] == base["report_id"]):
                base = candidate
            elif superseded is not None:
                superseded.append(candidate["report_id"])
    return base


def _generation_evidence(repository, conn, company_id, store_id, identity, superseded):
    # The recent-report feed is not a dependency store. Retrieve immutable
    # generation evidence by the full tenant/store/project identity, regardless
    # of unrelated newer work. This is not validation of the current facts.
    excluded = list(superseded)
    while True:
        try:
            candidate = _base_candidate(repository, conn, company_id, store_id, identity, excluded,
                                        report_types=("listing.package", "product.listing"))
        except KeyError:
            return None
        body = candidate.get("report") if isinstance(candidate.get("report"), dict) else {}
        handoff = body.get("listing_handoff") if isinstance(body.get("listing_handoff"), dict) else {}
        valid = (candidate.get("runtime_run_id") == "listing_draft_generation"
                 and body.get("contract_version") == "listing_ai_draft_generation_v1"
                 and handoff.get("source_mode") == "project_scoped_live_model"
                 and handoff.get("ready_for_listing_draft") is True)
        rewrite = _rewrite_contract(candidate)
        if valid and rewrite is not None:
            # Unadopted rewrites must not resurrect rejected text or borrow a
            # newer generation proof when reopening an older text checkpoint.
            valid = bool(_valid_rewrite_anchors(candidate, rewrite) and conn.execute(
                """select checkpoint_id from listing_draft_edit_revisions
                where company_id = ? and store_id = ? and project_key = ? and source_report_id = ?
                  and candidate_id = ? and base_report_id = ? limit 1""",
                (company_id, store_id, *(identity[key] for key in IDENTITY_KEYS), candidate["report_id"])).fetchone())
        if valid:
            return candidate
        excluded.append(candidate["report_id"])


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
    superseded = []
    base = _base(repository, conn, company_id, store_id, identity, superseded=superseded)
    try:
        facts = _base_candidate(repository, conn, company_id, store_id, identity, [],
                                report_types=("merchant.product_facts",))
    except KeyError:
        facts = None
    return {"contract_version": CONTRACT_VERSION, "status": "saved" if checkpoint else "empty",
            "checkpoint": checkpoint, "current_revision": checkpoint["revision"] if checkpoint else 0,
            "current_base_report_id": base["report_id"], "current_base_report": base,
            "validated_generation_report": _generation_evidence(repository, conn, company_id, store_id, identity, superseded),
            # Generation may be the latest copy base, but later fact saves
            # still need the separate fact head for optimistic concurrency.
            "current_product_fact_report": facts,
            "base_changed": bool(checkpoint and checkpoint["base_report_id"] != base["report_id"]),
            **({"superseded_rewrite_report_ids": superseded} if superseded else {}), **SAFETY}


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
                              "current_base_report": view["current_base_report"],
                              **({"superseded_rewrite_report_ids": view["superseded_rewrite_report_ids"]}
                                 if view.get("superseded_rewrite_report_ids") else {}), **SAFETY})


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
        # Fact saves use this same store lock. Keep their source update and this
        # short adoption transaction ordered on Postgres; reads remain unlocked.
        _scope(conn, company_id, store_id, lock=repository.database_engine == "postgres")
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
        if "publish_intake" in body:
            checkpoint["publish_intake"] = body["publish_intake"]
        elif head["checkpoint_id"]:
            # Older tabs and buyer-copy adoption still use the v1 request.
            # Omitting the new field must not erase a newer device's form.
            prior = conn.execute("""select receipt_json from listing_draft_edit_revisions
                where checkpoint_id = ? and company_id = ? and store_id = ? and project_key = ?""",
                (head["checkpoint_id"], *scope)).fetchone()
            prior_receipt = _decode(prior["receipt_json"]) if prior else {}
            if "publish_intake" in prior_receipt:
                checkpoint["publish_intake"] = prior_receipt["publish_intake"]
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
