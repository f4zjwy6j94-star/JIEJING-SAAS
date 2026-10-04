"""Read-only, explicit-task recovery for the audited pre-operation Listing writer."""
from __future__ import annotations

import hashlib
import json
import re

from .listing_draft_checkpoint import FIELD_KEYS, normalize_identity
from .listing_draft_generation import is_listing_buyer_copy_rewrite_contract, listing_draft_generation_request_failure
from .repository import normalize_merchant_product_fact_packet
from .sensitive_text import contains_secret_like_data

CONTRACT_VERSION = "listing_generation_legacy_recovery_v1"
_SAFETY = {"model_called": False, "usage_consumed": False,
           "real_platform_writes_enabled": False, "secret_exposed": False}
_FACT_KEYS = ("product_name", "merchant_confirmed_facts", "derived_listing_suggestions", "simulation_only",
              "source_records", "field_evidence", "pending_field_evidence", "fact_conflicts", "buyer_copy_requires_validated_listing_generation",
              "vision_contract_version", "source_mode", "sensitive_text_detected")


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value) and not contains_secret_like_data(value) else ""


def _packet_matches(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    a = normalize_merchant_product_fact_packet(left, source="authenticated_merchant_request")
    b = normalize_merchant_product_fact_packet(right, source="authenticated_merchant_request")
    return a.get("sensitive_text_detected") is False and b.get("sensitive_text_detected") is False and all(
        a.get(key) == b.get(key) for key in _FACT_KEYS)


def _failed_usage_proof(task, ledger):
    if len(ledger) != 1:
        return ""
    row, output = ledger[0], task.get("output") or {}
    usage = _json(row.get("usage_json") or {})
    details = usage.get("details") or {}
    company, task_id = task.get("company_id"), task.get("task_id")
    expected_hash = hashlib.sha256(f"model-usage|{company}|{task_id}:listing-draft-model-usage:v1".encode("utf-8")).hexdigest()
    count, failure = row.get("request_count"), output.get("failure_code")
    if (task.get("input", {}).get("contract_version") != "listing_ai_draft_generation_v1"
        or row.get("company_id") != company or row.get("task_id") != task_id or row.get("user_id") != task.get("user_id")
        or row.get("idempotency_key_hash") != expected_hash
        or usage.get("contract_version") != "2026-07-14-model-usage-ledger-v1"
        or not all(usage.get(key) is False for key in ("secret_exposed", "prompts_stored", "responses_stored", "provider_credentials_stored"))
        or not all(details.get(key) is False for key in ("prompts_stored", "responses_stored"))
        or details.get("outcome") != "failed"
        or task.get("status") != "failed" or output.get("model_called") is not True
        or output.get("usage_consumed") is not True or output.get("usage_ledger_recorded") is not True
        or type(count) is not int or count <= 0 or type(output.get("model_request_count")) is not int
        or output["model_request_count"] != count
        or not isinstance(failure, str) or not re.fullmatch(r"listing_[a-z0-9_]{1,110}", failure)
        or details.get("failure_code") != failure
        or output.get("real_platform_writes_enabled") is not False or output.get("secret_exposed") is not False):
        return ""
    return failure


def _saved_listing_report(report, company_id, store_id, identity):
    data = report.get("report") or {}
    return (report.get("company_id") == company_id and report.get("store_id") == store_id
            and report.get("status") == "saved" and report.get("report_type") == "listing.package"
            and report.get("runtime_run_id") == "listing_draft_generation"
            and data.get("contract_version") == "listing_ai_draft_generation_v1"
            and data.get("listing_project_identity") == identity and data.get("secret_exposed") is False
            and data.get("real_platform_writes_enabled") is False and not contains_secret_like_data(report))


def read_legacy_listing_generation_result(*, repository, company_id, store_id, user_id, task_id,
                                         listing_project_identity, expected_base_report_id, expected_checkpoint_revision):
    """A selected task is evidence only; this call never creates or resumes work."""
    valid_revision = type(expected_checkpoint_revision) is int and 1 <= expected_checkpoint_revision < 2147483647
    result = {"contract_version": CONTRACT_VERSION, "company_id": _identifier(company_id), "store_id": _identifier(store_id),
              "user_id": _identifier(user_id), "task_id": _identifier(task_id),
              "listing_project_identity": {"key": "", "source_report_id": "", "candidate_id": ""},
              "expected_base_report_id": _identifier(expected_base_report_id),
              "expected_checkpoint_revision": expected_checkpoint_revision if valid_revision else None,
              "status": "legacy_evidence_incomplete", "can_retry": False, "report": None, "proof_kind": "",
              "failure_code": "listing_legacy_evidence_incomplete",
              "merchant_message": "这次历史生成的证据还不完整，请保留现有文案继续核对，不要重复生成。", **_SAFETY}
    try:
        identity = normalize_identity(listing_project_identity)
        if (contains_secret_like_data(identity) or not all(_identifier(value)
                    for value in (company_id, store_id, user_id, task_id, expected_base_report_id)) or not valid_revision):
            return result
        result["listing_project_identity"] = identity
        evidence = repository.read_legacy_listing_generation_evidence(company_id=company_id, store_id=store_id,
            user_id=user_id, task_id=task_id, identity=identity, base_report_id=expected_base_report_id,
            revision=expected_checkpoint_revision)
        task = evidence.get("task") or {}
        inputs, output = task.get("input") or {}, task.get("output") or {}
        if (task.get("company_id") != company_id or task.get("store_id") != store_id or task.get("user_id") != user_id
            or task.get("task_type") != "listing_draft_generation" or task.get("task_id") != task_id
            or inputs.get("contract_version") != "listing_ai_draft_generation_v1"
            or inputs.get("generation_mode") != "rewrite_buyer_copy"
            or inputs.get("listing_project_identity") != identity or evidence.get("related_truncated") is not False):
            return result
        historical = evidence.get("checkpoint") or {}
        receipt = _json(historical.get("receipt_json") or {})
        current = inputs.get("current_draft_fields")
        base = evidence.get("base_report") or {}
        if (listing_draft_generation_request_failure(current, generation_mode="rewrite_buyer_copy")
            or historical.get("actor_user_id") != user_id
            or receipt.get("company_id") != company_id or receipt.get("store_id") != store_id
            or receipt.get("listing_project_identity") != identity
            or receipt.get("base_report_id") != expected_base_report_id
            or type(receipt.get("revision")) is not int or receipt["revision"] != expected_checkpoint_revision
            or receipt.get("source") != "merchant_edit"
            or receipt.get("fields") != {key: current[key] for key in FIELD_KEYS}
            or receipt.get("merchant_edited_fields") != sorted(set(current["merchant_edited_fields"]))
            or base.get("company_id") != company_id or base.get("store_id") != store_id
            or base.get("status") != "saved" or base.get("report", {}).get("listing_project_identity") != identity
            or not _packet_matches(inputs.get("merchant_product_fact_packet"), base.get("report", {}).get("merchant_product_fact_packet"))):
            return result
        reports = evidence.get("reports") or []
        selected_reports = [item for item in reports if item.get("task_id") == task_id]
        if selected_reports:
            saved = selected_reports[0]
            data = saved.get("report") or {}
            rewrite = data.get("listing_handoff", {}).get("listing_fields", {}).get("buyer_copy_rewrite")
            if (len(selected_reports) == 1 and _saved_listing_report(saved, company_id, store_id, identity)
                and is_listing_buyer_copy_rewrite_contract(rewrite)
                and rewrite["expected_base_report_id"] == expected_base_report_id
                and rewrite["expected_checkpoint_revision"] == expected_checkpoint_revision
                and rewrite["previous_fields"] == receipt["fields"]
                and rewrite["previous_merchant_edited_fields"] == receipt["merchant_edited_fields"]
                and _packet_matches(data.get("merchant_product_fact_packet"), inputs.get("merchant_product_fact_packet"))):
                return {**result, "status": "report_saved", "report": saved, "failure_code": "",
                        "merchant_message": "已找到这次保存的文案，请核对已有版本，不要重复生成。"}
            return result
        for other in evidence.get("related_tasks", []):
            if other.get("task_id") == task_id:
                continue
            other_reports = [item for item in reports if item.get("task_id") == other.get("task_id")]
            other_ledger = [row for row in evidence.get("related_ledger", []) if row.get("task_id") == other.get("task_id")]
            if (other.get("status") == "completed" and len(other_reports) == 1
                and _saved_listing_report(other_reports[0], company_id, store_id, identity)):
                continue
            if not other_reports and _failed_usage_proof(other, other_ledger):
                continue
            return result
        failure = _failed_usage_proof(task, evidence.get("ledger") or [])
        if not failure:
            return result
        # The audited legacy writer commits model_completed under this exact
        # unique key before its sole report save. INSERT OR IGNORE cannot turn
        # that row into failed after an uncertain save/ledger acknowledgement.
        return {**result, "status": "legacy_failed_before_report", "can_retry": True,
                "proof_kind": "immutable_failed_usage_ledger", "failure_code": failure,
                "merchant_message": "已核对这次生成：文案未保存，原稿已保留。你可以确认后重新生成。"}
    except Exception:
        return result
