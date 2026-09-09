"""One-shot, scoped Listing generation operations; status reads never execute work."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .listing_draft_checkpoint import FIELD_KEYS, normalize_identity
from .repository import MERCHANT_PRODUCT_FACT_KEYS, _redact_secret_like, normalize_merchant_product_fact_packet
from .sensitive_text import contains_secret_like_data

CONTRACT_VERSION = "listing_generation_operation_v1"
SAFETY = {"real_platform_writes_enabled": False, "secret_exposed": False}


def _operation_task_id(company_id: str, store_id: str, user_id: str, operation_id: str) -> str:
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,96}", operation_id):
        raise ValueError("listing_generation_operation_invalid")
    if contains_secret_like_data({"operation_id": operation_id}):
        raise ValueError("listing_generation_operation_invalid")
    if not all(isinstance(value, str) and value for value in (company_id, store_id, user_id)):
        raise ValueError("listing_generation_operation_scope_invalid")
    return "task_listing_op_" + hashlib.sha256(
        "\0".join((CONTRACT_VERSION, company_id, store_id, user_id, operation_id)).encode("utf-8")
    ).hexdigest()[:40]


def build_listing_generation_operation(*, company_id: str, store_id: str, user_id: str, operation_id: str,
    listing_project_identity: dict[str, Any], merchant_product_fact_packet: dict[str, Any],
    current_draft_fields: dict[str, Any], generation_mode: str = "preserve_merchant_edits",
    expected_base_report_id: str | None = None, expected_checkpoint_revision: int | None = None) -> dict[str, Any]:
    from .listing_draft_generation import listing_draft_generation_request_failure, _safe_current_draft_fields
    task_id = _operation_task_id(company_id, store_id, user_id, operation_id)
    identity = normalize_identity(listing_project_identity)
    failure = listing_draft_generation_request_failure(current_draft_fields, generation_mode=generation_mode)
    if failure:
        raise ValueError(failure)
    if generation_mode == "rewrite_buyer_copy" and (
        not isinstance(expected_base_report_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", expected_base_report_id)
        or type(expected_checkpoint_revision) is not int or not 0 <= expected_checkpoint_revision < 2147483647
    ):
        raise ValueError("listing_generation_operation_anchors_invalid")
    if generation_mode != "rewrite_buyer_copy" and (
        expected_base_report_id is not None or expected_checkpoint_revision is not None
    ):
        raise ValueError("listing_generation_operation_anchors_invalid")
    if not isinstance(merchant_product_fact_packet, dict) or not isinstance(current_draft_fields, dict):
        raise ValueError("listing_generation_operation_input_invalid")
    normalized_packet = normalize_merchant_product_fact_packet(merchant_product_fact_packet,
        source="authenticated_merchant_request")
    if (set(merchant_product_fact_packet) - set(normalized_packet)
        or set(current_draft_fields) - {*FIELD_KEYS, "merchant_edited_fields"}):
        raise ValueError("listing_generation_operation_input_invalid")
    for key in ("merchant_confirmed_facts", "derived_listing_suggestions", "source_confirmed_facts"):
        facts = merchant_product_fact_packet.get(key, {})
        if not isinstance(facts, dict) or set(facts) - set(MERCHANT_PRODUCT_FACT_KEYS):
            raise ValueError("listing_generation_operation_input_invalid")
    payload = {"listing_project_identity": identity, "generation_mode": generation_mode,
        "expected_base_report_id": expected_base_report_id, "expected_checkpoint_revision": expected_checkpoint_revision,
        "merchant_product_fact_packet": merchant_product_fact_packet, "current_draft_fields": current_draft_fields}
    if contains_secret_like_data(payload) or _redact_secret_like(payload) != payload:
        raise ValueError("listing_generation_operation_sensitive_input")
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 100_000:
        raise ValueError("listing_generation_operation_input_too_large")
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {"task_id": task_id, "company_id": company_id, "store_id": store_id, "user_id": user_id,
        "operation_id": operation_id, "fingerprint": fingerprint,
        "input_data": {"contract_version": CONTRACT_VERSION, "operation_id": operation_id,
            "fingerprint": fingerprint, **json.loads(encoded), "merchant_product_fact_packet": normalized_packet,
            "current_draft_fields": (json.loads(encoded)["current_draft_fields"] if generation_mode == "rewrite_buyer_copy"
                                     else _safe_current_draft_fields(current_draft_fields)),
            "model_usage_required": True, "frontend_gets_model_api_key": False, "runtime_gets_raw_ebay_token": False, **SAFETY}}


def claim_listing_generation_operation(repository, *, operation: dict[str, Any]) -> dict[str, Any]:
    claimed = repository.claim_listing_generation_operation_task(
        task_id=operation["task_id"], company_id=operation["company_id"], store_id=operation["store_id"],
        user_id=operation["user_id"], input_data=operation["input_data"])
    view = read_listing_generation_operation(repository, company_id=operation["company_id"],
        store_id=operation["store_id"], user_id=operation["user_id"], operation_id=operation["operation_id"],
        listing_project_identity=operation["input_data"]["listing_project_identity"], fingerprint=operation["fingerprint"])
    return {**view, "claimed": claimed["claimed"] and view["status"] != "conflict", "task": claimed["task"]}


def read_listing_generation_operation(repository, *, company_id: str, store_id: str, user_id: str,
    operation_id: str, listing_project_identity: dict[str, Any], fingerprint: str | None = None) -> dict[str, Any]:
    from .listing_draft_generation import is_listing_buyer_copy_rewrite_contract
    task_id = _operation_task_id(company_id, store_id, user_id, operation_id)
    identity = normalize_identity(listing_project_identity)
    view = {"contract_version": CONTRACT_VERSION, "operation_id": operation_id, "task_id": task_id,
        "company_id": company_id, "store_id": store_id, "user_id": user_id, "listing_project_identity": identity,
        "generation_mode": None, "expected_base_report_id": None, "expected_checkpoint_revision": None,
        "status": "not_found", "can_retry": False, "report": None, "failure_code": "", "message": "尚未找到本次生成记录，请勿重复生成。",
        "model_called": None, "usage_consumed": None, "report_save_attempted": None, **SAFETY}
    task = repository.get_task(company_id=company_id, task_id=task_id)
    if not task:
        return view
    data, output = task.get("input") or {}, task.get("output") or {}
    if (task.get("store_id") != store_id or task.get("user_id") != user_id
        or task.get("task_type") != "listing_draft_generation" or data.get("contract_version") != CONTRACT_VERSION
        or data.get("operation_id") != operation_id or data.get("listing_project_identity") != identity
        or fingerprint is not None and data.get("fingerprint") != fingerprint):
        return {**view, "status": "conflict", "failure_code": "listing_generation_operation_conflict",
                "message": "本次操作与原请求不一致，请保留现有草稿。"}
    view.update({key: data.get(key) for key in ("generation_mode", "expected_base_report_id", "expected_checkpoint_revision")})
    view.update({key: output.get(key) if type(output.get(key)) is bool else None
                 for key in ("model_called", "usage_consumed", "report_save_attempted")})
    reports = repository.list_listing_generation_operation_reports(company_id=company_id, store_id=store_id,
        user_id=user_id, task_id=task_id)
    valid = []
    for report in reports:
        body = report.get("report") or {}
        handoff = body.get("listing_handoff") or {}
        fields = handoff.get("listing_fields") or {}
        rewrite = fields.get("buyer_copy_rewrite") or {}
        if (report.get("task_id") == task_id and report.get("company_id") == company_id
            and report.get("store_id") == store_id and report.get("user_id") == user_id
            and report.get("report_type") == "listing.package" and report.get("status") == "saved"
            and report.get("runtime_run_id") == "listing_draft_generation"
            and body.get("listing_project_identity") == identity and handoff.get("ready_for_listing_draft") is True
            and body.get("real_platform_writes_enabled") is False
            and body.get("merchant_product_fact_packet") == data.get("merchant_product_fact_packet")
            and (data.get("generation_mode") != "rewrite_buyer_copy" or (
                is_listing_buyer_copy_rewrite_contract(rewrite)
                and rewrite.get("expected_base_report_id") == data.get("expected_base_report_id")
                and rewrite.get("expected_checkpoint_revision") == data.get("expected_checkpoint_revision")
                and rewrite.get("previous_fields") == {key: data["current_draft_fields"][key] for key in FIELD_KEYS}
                and set(rewrite.get("previous_merchant_edited_fields", []))
                    == set(data["current_draft_fields"].get("merchant_edited_fields", []))))):
            valid.append(report)
    if len(valid) == 1 and len(reports) == 1:
        return {**view, "status": "report_saved", "report": valid[0], "report_save_attempted": True,
                "message": "已找到本次生成的文案，请核对后采用。"}
    if reports or output.get("phase") in ("saving_report", "report_saved", "save_unknown"):
        return {**view, "status": "save_unknown", "message": "保存结果仍待确认，请保留现有草稿，不要重复生成。"}
    if (task.get("status") == "failed" and output.get("phase") == "failed_before_report"
        and output.get("report_save_attempted") is False):
        return {**view, "status": "failed_before_report", "can_retry": True,
                "failure_code": str(output.get("failure_code") or "listing_model_generation_failed"),
                "message": "已确认本次没有保存新文案；现有草稿未被替换，可以由你重新发起生成。"}
    return {**view, "status": "running", "message": "本次生成尚无可确认的最终结果，请稍后再次核对，不要重复生成。"}


def transition_listing_generation_operation(repository, *, operation_task: dict[str, Any],
    expected_phases: tuple[str, ...], phase: str, status: str, output: dict[str, Any],
    model_metadata: dict[str, str] | None = None) -> dict[str, Any] | None:
    return repository.transition_listing_generation_operation_task(task_id=operation_task["task_id"],
        company_id=operation_task["company_id"], store_id=operation_task["store_id"], user_id=operation_task["user_id"],
        expected_phases=expected_phases, phase=phase, status=status, output={**output, **SAFETY}, model_metadata=model_metadata)


def finish_listing_generation_operation(repository, *, operation_task: dict[str, Any], failure_code: str,
    model_called: bool = False, usage_consumed: bool = False, model_request_count: int = 0,
    report_save_attempted: bool = False, expected_phases: tuple[str, ...] = ("before_model",)) -> dict[str, Any] | None:
    return transition_listing_generation_operation(repository, operation_task=operation_task,
        expected_phases=expected_phases,
        phase="save_unknown" if report_save_attempted else "failed_before_report", status="failed",
        output={"failure_code": failure_code, "model_called": model_called, "usage_consumed": usage_consumed,
                "model_request_count": model_request_count, "report_save_attempted": report_save_attempted})
