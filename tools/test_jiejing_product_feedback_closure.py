#!/usr/bin/env python3
"""Focused repository contract for the real merchant product-feedback closure."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.product_feedback import (  # noqa: E402
    ProductFeedbackIdempotencyConflict,
    ProductFeedbackStatusConflict,
    ProductFeedbackValidationError,
    normalize_product_feedback_payload,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _expect_validation_error(payload: dict[str, object]) -> bool:
    try:
        normalize_product_feedback_payload(payload)
    except ProductFeedbackValidationError:
        return True
    return False


def main() -> int:
    normalized = normalize_product_feedback_payload(
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "detail": "The next step is unclear.",
            "stage_title": "Prepare listing",
        }
    )
    if normalized.get("feedback_type") != "product_improvement":
        return fail(f"valid product feedback was not normalized: {normalized}")
    if normalized.get("module_key") != "workflow" or normalized.get("reason") != "unclear":
        return fail(f"valid feedback enums changed: {normalized}")

    invalid_payloads = (
        {"feedback_type": "support_ticket", "module_key": "workflow", "reason": "unclear"},
        {"feedback_type": "product_improvement", "module_key": "unknown", "reason": "unclear"},
        {"feedback_type": "product_improvement", "module_key": "workflow", "reason": "other"},
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "company_id": "forged-company",
        },
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "user_id": "forged-user",
        },
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "store_id": "forged-store",
        },
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "status": "resolved",
        },
        {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "unclear",
            "internal_note": "forged internal state",
        },
    )
    if not all(_expect_validation_error(payload) for payload in invalid_payloads):
        return fail("invalid enum or client-owned internal field was accepted")

    sanitized = normalize_product_feedback_payload(
        {
            "feedback_type": "product_improvement",
            "module_key": "product",
            "reason": "wrong_result",
            "detail": "\x00<script>alert(1)</script> password=PlainText-2026 api_key=unsafe-value",
            "stage_title": "\x07Listing <b>result</b>",
            "task_id": "task-safe-label",
        }
    )
    serialized_sanitized = str(sanitized).lower()
    for forbidden in ("\x00", "\x07", "<script", "<b>", "plaintext-2026", "unsafe-value"):
        if forbidden in serialized_sanitized:
            return fail(f"feedback sanitizer retained forbidden text: {forbidden}, {sanitized}")
    if "[redacted]" not in serialized_sanitized:
        return fail(f"secret-like feedback text was not redacted: {sanitized}")
    malformed_html = normalize_product_feedback_payload(
        {
            "feedback_type": "product_improvement",
            "module_key": "product",
            "reason": "wrong_result",
            "detail": "Visible text &lt;img src=x onerror=alert(1) unfinished",
            "stage_title": "Listing > orphan <",
        }
    )
    serialized_malformed = str(malformed_html).lower()
    for forbidden in ("<", ">", "onerror", "src=x"):
        if forbidden in serialized_malformed:
            return fail(f"feedback sanitizer retained malformed HTML residue: {forbidden}, {malformed_html}")
    if not _expect_validation_error(
        {
            "feedback_type": "product_improvement",
            "module_key": "product",
            "reason": "wrong_result",
            "detail": "x" * 421,
        }
    ):
        return fail("feedback detail longer than 420 characters was accepted")
    if not _expect_validation_error(
        {
            "feedback_type": "product_improvement",
            "module_key": "product",
            "reason": "wrong_result",
            "stage_title": "x" * 161,
        }
    ):
        return fail("feedback stage title longer than 160 characters was accepted")

    with tempfile.TemporaryDirectory(
        prefix="jiejing-product-feedback-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        db_path = Path(temp_dir) / "saas.sqlite"
        repository = SaaSRepository(db_path)
        first = repository.create_user_with_company(
            email="feedback-first@jiejing-shop.cn",
            password="Feedback-first-password-2026",
            company_name="First Feedback Company",
        )
        second = repository.create_user_with_company(
            email="feedback-second@jiejing-shop.cn",
            password="Feedback-second-password-2026",
            company_name="Second Feedback Company",
        )
        first_company_id = str(first["company"]["company_id"])
        first_user_id = str(first["user"]["user_id"])
        second_company_id = str(second["company"]["company_id"])
        second_user_id = str(second["user"]["user_id"])
        if repository.list_product_feedback(company_id=first_company_id) != []:
            return fail("new company should not invent product feedback")

        feedback_payload = {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "missing_action",
            "detail": "Please add a clearer next action.",
            "stage_title": "Workflow review",
            "task_id": "opaque-task-label",
        }
        created = repository.create_product_feedback(
            company_id=first_company_id,
            user_id=first_user_id,
            idempotency_key="browser-feedback-stable-key-001",
            payload=feedback_payload,
        )
        if created.get("status") != "open" or created.get("duplicate_request") is not False:
            return fail(f"created feedback receipt is wrong: {created}")
        replayed = repository.create_product_feedback(
            company_id=first_company_id,
            user_id=first_user_id,
            idempotency_key="browser-feedback-stable-key-001",
            payload=dict(feedback_payload),
        )
        if replayed.get("feedback_id") != created.get("feedback_id") or replayed.get("duplicate_request") is not True:
            return fail(f"same-key same-payload replay did not return the original receipt: {replayed}")
        conflicting_payload = dict(feedback_payload)
        conflicting_payload["detail"] = "A different normalized request body."
        try:
            repository.create_product_feedback(
                company_id=first_company_id,
                user_id=first_user_id,
                idempotency_key="browser-feedback-stable-key-001",
                payload=conflicting_payload,
            )
        except ProductFeedbackIdempotencyConflict:
            pass
        else:
            return fail("same-key different-payload feedback silently reused or overwrote the original")
        feedback_audits = [
            item
            for item in repository.list_audit_logs(company_id=first_company_id, limit=20)
            if item.get("action_type") == "product_feedback.created"
        ]
        if len(feedback_audits) != 1:
            return fail(f"feedback creation should write exactly one audit event: {feedback_audits}")
        if feedback_audits[0].get("user_id") != first_user_id or "internal_actor" in feedback_audits[0]:
            return fail(f"merchant actor audit identity semantics changed: {feedback_audits[0]}")
        audit_text = json.dumps(feedback_audits, ensure_ascii=False).lower()
        for forbidden in (
            "please add a clearer next action",
            "opaque-task-label",
            "browser-feedback-stable-key-001",
        ):
            if forbidden in audit_text:
                return fail(f"feedback audit copied body, context or idempotency input: {forbidden}")
        with sqlite3.connect(db_path) as raw_connection:
            persisted = raw_connection.execute(
                "select idempotency_key_hash, feedback_json from merchant_product_feedback"
            ).fetchall()
        persisted_text = json.dumps(persisted, ensure_ascii=False).lower()
        if "browser-feedback-stable-key-001" in persisted_text:
            return fail("raw product-feedback idempotency key was persisted")
        if "browser-feedback-stable-key-001" in json.dumps((created, replayed), ensure_ascii=False).lower():
            return fail("raw product-feedback idempotency key was returned in a receipt")
        first_receipts = repository.list_product_feedback(company_id=first_company_id)
        if len(first_receipts) != 1 or first_receipts[0].get("feedback_id") != created.get("feedback_id"):
            return fail(f"first company cannot read its feedback receipt: {first_receipts}")
        if "duplicate_request" in first_receipts[0]:
            return fail(f"historical feedback receipt invented duplicate_request state: {first_receipts[0]}")
        if repository.list_product_feedback(company_id=second_company_id) != []:
            return fail("product feedback crossed the company boundary")
        forbidden_receipt_fields = {
            "company_id",
            "user_id",
            "store_id",
            "detail",
            "stage_title",
            "task_id",
            "idempotency_key",
            "idempotency_key_hash",
        }
        if forbidden_receipt_fields.intersection(first_receipts[0]):
            return fail(f"merchant receipt exposed internal feedback fields: {first_receipts[0]}")
        try:
            repository.transition_product_feedback_status(
                feedback_id=str(created["feedback_id"]),
                actor_user_id=second_user_id,
                target_status="resolved",
            )
        except ProductFeedbackStatusConflict:
            pass
        else:
            return fail("product feedback skipped directly from open to resolved")
        reviewing = repository.transition_product_feedback_status(
            feedback_id=str(created["feedback_id"]),
            actor_user_id=second_user_id,
            target_status="reviewing",
        )
        try:
            repository.transition_product_feedback_status(
                feedback_id=str(created["feedback_id"]),
                actor_user_id=second_user_id,
                target_status="reviewing",
            )
        except ProductFeedbackStatusConflict:
            pass
        else:
            return fail("reviewing product feedback accepted a repeated review transition")
        resolved = repository.transition_product_feedback_status(
            feedback_id=str(created["feedback_id"]),
            actor_user_id=second_user_id,
            target_status="resolved",
        )
        if reviewing.get("status") != "reviewing" or resolved.get("status") != "resolved" or not resolved.get("resolved_at"):
            return fail(f"legal feedback status progression failed: {reviewing}, {resolved}")
        try:
            repository.transition_product_feedback_status(
                feedback_id=str(created["feedback_id"]),
                actor_user_id=second_user_id,
                target_status="reviewing",
            )
        except ProductFeedbackStatusConflict:
            pass
        else:
            return fail("resolved product feedback moved backward")
        try:
            repository.transition_product_feedback_status(
                feedback_id="feedback_unknown",
                actor_user_id=second_user_id,
                target_status="reviewing",
            )
        except KeyError:
            pass
        else:
            return fail("unknown feedback ID did not fail closed")
        status_audits = [
            item
            for item in repository.list_audit_logs(company_id=first_company_id, limit=20)
            if item.get("action_type") == "product_feedback.status_changed"
        ]
        if len(status_audits) != 2:
            return fail(f"legal status transitions should each have one audit: {status_audits}")
        status_audit_text = json.dumps(status_audits, ensure_ascii=False).lower()
        if "please add a clearer next action" in status_audit_text or "opaque-task-label" in status_audit_text:
            return fail("status transition audit copied feedback body or context")
        if second_user_id.lower() in status_audit_text:
            return fail("merchant-visible status audit exposed the internal administrator raw user_id")
        if any("user_id" in item for item in status_audits):
            return fail(f"merchant-visible status audit retained an internal user_id field: {status_audits}")
        if not all(item.get("internal_actor") is True for item in status_audits):
            return fail(f"merchant-visible status audit did not identify a safely hidden internal actor: {status_audits}")
        with sqlite3.connect(db_path) as raw_connection:
            persisted_status_audits = raw_connection.execute(
                """
                select user_id, audit_json from audit_logs
                where company_id = ? and action_type = 'product_feedback.status_changed'
                order by created_at asc
                """,
                (first_company_id,),
            ).fetchall()
        if len(persisted_status_audits) != 2:
            return fail(f"internal status audit persistence count is wrong: {persisted_status_audits}")
        for persisted_user_id, persisted_audit_json in persisted_status_audits:
            persisted_packet = json.loads(persisted_audit_json)
            if persisted_user_id != second_user_id or persisted_packet.get("user_id") != second_user_id:
                return fail("internal status audit did not retain the normalized actor user_id for traceability")
        repository.initialize()
        after_reinitialize = repository.list_product_feedback(company_id=first_company_id)
        if len(after_reinitialize) != 1 or after_reinitialize[0].get("feedback_id") != created.get("feedback_id"):
            return fail(f"repeated SQLite initialize lost product feedback: {after_reinitialize}")

        scope_repository = SaaSRepository(Path(temp_dir) / "scope.sqlite")
        scope_owner = scope_repository.create_user_with_company(
            email="feedback-scope-owner@jiejing-shop.cn",
            password="Feedback-scope-owner-password-2026",
            company_name="Feedback Scope Company",
        )
        scope_member = scope_repository.create_user_with_company(
            email="feedback-scope-member@jiejing-shop.cn",
            password="Feedback-scope-member-password-2026",
            company_name="Feedback Scope Member Company",
        )
        scope_company_id = str(scope_owner["company"]["company_id"])
        scope_owner_id = str(scope_owner["user"]["user_id"])
        scope_member_id = str(scope_member["user"]["user_id"])
        scope_repository.create_team_invitation(
            company_id=scope_company_id,
            invited_by=scope_owner_id,
            email="feedback-scope-member@jiejing-shop.cn",
            role="operator",
        )
        if not scope_repository.get_team_member(company_id=scope_company_id, user_id=scope_member_id):
            return fail("scope test could not establish two users in the same company")
        first_store = scope_repository.create_store(
            company_id=scope_company_id,
            user_id=scope_owner_id,
            payload={"platform": "ebay", "store_name": "Feedback Scope Store One", "marketplace": "EBAY_US"},
        )
        second_store = scope_repository.create_store(
            company_id=scope_company_id,
            user_id=scope_owner_id,
            payload={"platform": "ebay", "store_name": "Feedback Scope Store Two", "marketplace": "EBAY_US"},
        )
        scope_payload = {
            "feedback_type": "product_improvement",
            "module_key": "workflow",
            "reason": "missing_action",
            "detail": "The same normalized feedback text.",
            "stage_title": "Scope conflict check",
        }
        scope_repository.create_product_feedback(
            company_id=scope_company_id,
            user_id=scope_owner_id,
            idempotency_key="same-company-different-user-key",
            payload=scope_payload,
        )
        scope_repository.create_product_feedback(
            company_id=scope_company_id,
            user_id=scope_owner_id,
            store_id=str(first_store["store_id"]),
            idempotency_key="same-company-different-store-key",
            payload=scope_payload,
        )
        scope_conflicts: set[str] = set()
        try:
            scope_repository.create_product_feedback(
                company_id=scope_company_id,
                user_id=scope_member_id,
                idempotency_key="same-company-different-user-key",
                payload=scope_payload,
            )
        except ProductFeedbackIdempotencyConflict:
            scope_conflicts.add("user")
        try:
            scope_repository.create_product_feedback(
                company_id=scope_company_id,
                user_id=scope_owner_id,
                store_id=str(second_store["store_id"]),
                idempotency_key="same-company-different-store-key",
                payload=scope_payload,
            )
        except ProductFeedbackIdempotencyConflict:
            scope_conflicts.add("store")
        if scope_conflicts != {"user", "store"}:
            return fail(f"same-key same-text feedback was reused across server-derived scope: {scope_conflicts}")

        concurrent_payload = {
            "feedback_type": "product_improvement",
            "module_key": "cockpit",
            "reason": "unclear",
            "detail": "Concurrent same-key behavior check.",
            "stage_title": "Concurrent feedback",
        }

        def create_concurrent_feedback(_: int) -> dict[str, object]:
            return scope_repository.create_product_feedback(
                company_id=scope_company_id,
                user_id=scope_owner_id,
                idempotency_key="concurrent-same-key-behavior-check",
                payload=concurrent_payload,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            concurrent_receipts = list(executor.map(create_concurrent_feedback, range(8)))
        concurrent_ids = {str(item.get("feedback_id") or "") for item in concurrent_receipts}
        first_create_count = sum(item.get("duplicate_request") is False for item in concurrent_receipts)
        replay_count = sum(item.get("duplicate_request") is True for item in concurrent_receipts)
        if len(concurrent_ids) != 1 or first_create_count != 1 or replay_count != 7:
            return fail(f"concurrent same-key feedback was not exactly-once: {concurrent_receipts}")
        with sqlite3.connect(Path(temp_dir) / "scope.sqlite") as raw_scope_connection:
            concurrent_row_count = raw_scope_connection.execute(
                "select count(*) from merchant_product_feedback where feedback_id = ?",
                (next(iter(concurrent_ids)),),
            ).fetchone()[0]
        if concurrent_row_count != 1:
            return fail(f"concurrent same-key feedback persisted {concurrent_row_count} rows")

    print("PASS jiejing_product_feedback_closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
