#!/usr/bin/env python3
"""Focused repository contract for the real merchant product-feedback closure."""

from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import inspect
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPS_HOST = "ops.jiejing.shop"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.product_feedback import (  # noqa: E402
    ProductFeedbackIdempotencyConflict,
    ProductFeedbackStatusConflict,
    ProductFeedbackValidationError,
    normalize_product_feedback_payload,
)
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
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

    api_error = _test_http_merchant_tracer()
    if api_error:
        return fail(api_error)

    safe_server_error = _test_http_safe_unhandled_error_log()
    if safe_server_error:
        return fail(safe_server_error)

    sanitized_env_error = _test_sanitized_backend_subprocess_env()
    if sanitized_env_error:
        return fail(sanitized_env_error)

    process_cleanup_error = _test_backend_process_cleanup_contract()
    if process_cleanup_error:
        return fail(process_cleanup_error)

    persistence_failure_error = _test_product_feedback_persistence_failures_return_503()
    if persistence_failure_error:
        return fail(persistence_failure_error)

    scope_denial_error = _test_product_feedback_company_and_ip_denial()
    if scope_denial_error:
        return fail(scope_denial_error)

    rate_limit_error = _test_http_product_feedback_rate_limit()
    if rate_limit_error:
        return fail(rate_limit_error)

    shared_boundary_error = _test_http_shared_feedback_concurrent_boundary()
    if shared_boundary_error:
        return fail(shared_boundary_error)

    limiter_failure_error = _test_product_feedback_limiter_database_failure()
    if limiter_failure_error:
        return fail(limiter_failure_error)

    limiter_config_error = _test_product_feedback_limiter_configuration_bounds()
    if limiter_config_error:
        return fail(limiter_config_error)

    print("PASS jiejing_product_feedback_closure")
    return 0


def _test_http_merchant_tracer() -> str:
    with tempfile.TemporaryDirectory(prefix="jiejing-product-feedback-http-", ignore_cleanup_errors=True) as temp_dir:
        port = _free_port()
        env = _sanitized_backend_test_env(
            {
                "JIEJING_INTERNAL_ADMIN_EMAILS": "feedback-http-admin@example.test",
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false",
                "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "false",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS": "60",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER": "12",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY": "30",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP": "60",
            },
        )
        database_path = Path(temp_dir) / "saas.sqlite"
        process = _start_backend_test_process(
            database_path=database_path,
            runtime_database_path=Path(temp_dir) / "runtime.sqlite",
            output_root=temp_dir,
            port=port,
            env=env,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            if not _wait_for_health(base_url):
                return "product-feedback test backend did not become healthy"

            payload = {
                "idempotency_key": "feedback-http-tracer-key-001",
                "feedback_type": "product_improvement",
                "module_key": "workflow",
                "reason": "unclear",
                "detail": "The HTTP feedback step is unclear.",
                "stage_title": "HTTP feedback tracer",
            }
            unauth_get, _ = _request_json(f"{base_url}/product-feedback")
            unauth_post, _ = _request_json(f"{base_url}/product-feedback", method="POST", body=payload)
            if unauth_get != 401 or unauth_post != 401:
                return f"product feedback must require authentication: GET={unauth_get}, POST={unauth_post}"

            merchant = _register(base_url, "feedback-http-merchant@example.test")
            token = str(merchant.get("token") or "")
            create_status, created = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=payload,
            )
            receipt = created.get("product_feedback") if isinstance(created.get("product_feedback"), dict) else {}
            if (
                create_status != 201
                or created.get("delivered") is not True
                or receipt.get("status") != "open"
                or receipt.get("duplicate_request") is not False
            ):
                return f"authenticated product feedback create contract failed: {create_status} {created}"
            serialized_created = json.dumps(created, ensure_ascii=False)
            if any(
                raw_value in serialized_created
                for raw_value in (payload["idempotency_key"], payload["detail"], payload["stage_title"])
            ):
                return f"product feedback creation response leaked browser-only input: {created}"
            list_status, listed = _request_json(f"{base_url}/product-feedback?limit=20", token=token)
            receipts = listed.get("product_feedback_receipts")
            if list_status != 200 or not isinstance(receipts, list) or len(receipts) != 1:
                return f"merchant product feedback list contract failed: {list_status} {listed}"
            if receipts[0].get("feedback_id") != receipt.get("feedback_id"):
                return f"merchant product feedback list did not return the created receipt: {listed}"

            replay_status, replayed = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=dict(payload),
            )
            replay_receipt = (
                replayed.get("product_feedback") if isinstance(replayed.get("product_feedback"), dict) else {}
            )
            if (
                replay_status != 200
                or replayed.get("delivered") is not True
                or replay_receipt.get("feedback_id") != receipt.get("feedback_id")
                or replay_receipt.get("duplicate_request") is not True
            ):
                return f"idempotent product feedback replay contract failed: {replay_status} {replayed}"

            conflicting_payload = dict(payload)
            conflicting_payload["detail"] = "A different HTTP payload under the same idempotency key."
            try:
                conflict_status, conflict = _request_json(
                    f"{base_url}/product-feedback",
                    method="POST",
                    token=token,
                    body=conflicting_payload,
                )
            except Exception as exc:
                return f"idempotency conflict dropped the HTTP response instead of returning 409: {exc.__class__.__name__}"
            if conflict_status != 409 or conflict.get("status") != 409:
                return f"same-key different-payload feedback must return 409: {conflict_status} {conflict}"
            serialized_conflict = json.dumps(conflict, ensure_ascii=False)
            if payload["idempotency_key"] in serialized_conflict or conflicting_payload["detail"] in serialized_conflict:
                return f"product feedback conflict response leaked idempotency or feedback content: {conflict}"

            non_string_key_payload = dict(payload)
            non_string_key_payload["idempotency_key"] = ["feedback-keys-must-be-strings"]
            non_string_key_status, non_string_key = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=non_string_key_payload,
            )
            if non_string_key_status != 400 or non_string_key.get("status") != 400:
                return f"non-string product feedback idempotency key must return 400: {non_string_key_status} {non_string_key}"

            invalid_payload = {
                **payload,
                "idempotency_key": "feedback-http-invalid-key-001",
                "company_id": "forged-company-must-not-be-trusted",
            }
            try:
                invalid_status, invalid = _request_json(
                    f"{base_url}/product-feedback",
                    method="POST",
                    token=token,
                    body=invalid_payload,
                )
            except Exception as exc:
                return f"invalid product feedback dropped the HTTP response instead of returning 400: {exc.__class__.__name__}"
            if invalid_status != 400 or invalid.get("status") != 400:
                return f"client-owned feedback scope fields must return 400: {invalid_status} {invalid}"
            after_invalid_status, after_invalid = _request_json(f"{base_url}/product-feedback", token=token)
            after_invalid_receipts = after_invalid.get("product_feedback_receipts")
            if after_invalid_status != 200 or not isinstance(after_invalid_receipts, list) or len(after_invalid_receipts) != 1:
                return f"invalid feedback left a partial record: {after_invalid_status} {after_invalid}"
            malformed_status, malformed = _request_raw_json(
                f"{base_url}/product-feedback",
                token=token,
                raw_body=b'{"idempotency_key":',
            )
            if malformed_status != 400 or malformed.get("status") != 400:
                return f"malformed product feedback JSON must return 400: {malformed_status} {malformed}"

            second_merchant = _register(base_url, "feedback-http-second@example.test")
            second_token = str(second_merchant.get("token") or "")
            second_status, second_list = _request_json(f"{base_url}/product-feedback?limit=500", token=second_token)
            if second_status != 200 or second_list.get("product_feedback_receipts") != []:
                return f"product feedback crossed the authenticated company boundary: {second_status} {second_list}"
            stale_merchant = _register(base_url, "feedback-http-stale-member@example.test")
            stale_token = str(stale_merchant.get("token") or "")
            with sqlite3.connect(database_path) as connection:
                stale_identity = connection.execute(
                    "select user_id, default_company_id from users where email = ?",
                    ("feedback-http-stale-member@example.test",),
                ).fetchone()
                if not stale_identity:
                    return "stale-member HTTP fixture could not resolve the authenticated identity"
                connection.execute(
                    "delete from team_members where company_id = ? and user_id = ?",
                    (stale_identity[1], stale_identity[0]),
                )
            stale_payload = {
                **payload,
                "idempotency_key": "feedback-http-stale-member-key-001",
                "detail": "This body must never be echoed by a stale membership response.",
            }
            try:
                stale_status, stale_response = _request_json(
                    f"{base_url}/product-feedback",
                    method="POST",
                    token=stale_token,
                    body=stale_payload,
                )
            except Exception as exc:
                return f"stale-member feedback disconnected instead of returning a safe 403: {exc.__class__.__name__}"
            if stale_status != 403 or stale_response.get("status") != 403 or stale_response.get("error") != "access denied":
                return f"stale-member feedback must return a non-enumerating 403: {stale_status} {stale_response}"
            serialized_stale = json.dumps(stale_response, ensure_ascii=False).lower()
            for forbidden in (
                str(stale_identity[0]).lower(),
                str(stale_identity[1]).lower(),
                stale_payload["idempotency_key"].lower(),
                stale_payload["detail"].lower(),
                "team member",
            ):
                if forbidden in serialized_stale:
                    return f"stale-member feedback 403 leaked scope or request content: {stale_response}"
            safe_status, safe_list = _request_json(
                f"{base_url}/product-feedback?limit=500&company_id=forged-company",
                token=token,
            )
            safe_receipts = safe_list.get("product_feedback_receipts")
            if safe_status != 200 or not isinstance(safe_receipts, list) or len(safe_receipts) > 50:
                return f"merchant product feedback list was not bounded: {safe_status} {safe_list}"
            forbidden_receipt_fields = {
                "company_id",
                "user_id",
                "store_id",
                "detail",
                "stage_title",
                "task_id",
                "idempotency_key",
                "idempotency_key_hash",
                "internal_note",
                "duplicate_request",
            }
            if any(forbidden_receipt_fields.intersection(item) for item in safe_receipts):
                return f"merchant feedback API exposed internal receipt fields: {safe_list}"

            feedback_id = str(receipt.get("feedback_id") or "")
            for route in ("review", "resolve"):
                unauth_owner_status, _ = _request_json(
                    f"{base_url}/owner/product-feedback/{route}",
                    method="POST",
                    body={"feedback_id": feedback_id},
                    host=OPS_HOST,
                )
                if unauth_owner_status != 401:
                    return f"unauthenticated owner feedback {route} must return 401, got {unauth_owner_status}"
                merchant_owner_status, merchant_owner = _request_json(
                    f"{base_url}/owner/product-feedback/{route}",
                    method="POST",
                    token=token,
                    body={"feedback_id": feedback_id},
                    host=OPS_HOST,
                )
                if merchant_owner_status != 403:
                    return f"ordinary merchant owner feedback {route} must return 403: {merchant_owner_status} {merchant_owner}"
            operations_status, _ = _request_json(
                f"{base_url}/owner/operations/feedback",
                token=token,
                host=OPS_HOST,
            )
            if operations_status != 403:
                return f"ordinary merchant feedback operations detail must return 403, got {operations_status}"

            admin = _register(base_url, "feedback-http-admin@example.test")
            admin_token = str(admin.get("token") or "")
            app_host_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
                host="app.jiejing.shop",
            )
            localhost_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
            )
            if app_host_status != 403 or localhost_status != 403:
                return (
                    "internal admin escaped the operations host boundary for feedback: "
                    f"app={app_host_status}, local={localhost_status}"
                )
            invalid_owner_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id, "target_status": "resolved"},
                host=OPS_HOST,
            )
            if invalid_owner_status != 400:
                return f"owner feedback action must reject browser-selected status fields, got {invalid_owner_status}"
            skipped_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/resolve",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
                host=OPS_HOST,
            )
            if skipped_status != 409:
                return f"owner feedback action must reject open-to-resolved state skipping, got {skipped_status}"
            review_status, reviewed = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
                host=OPS_HOST,
            )
            reviewed_receipt = reviewed.get("product_feedback") if isinstance(reviewed.get("product_feedback"), dict) else {}
            if review_status != 200 or reviewed_receipt.get("status") != "reviewing":
                return f"internal admin feedback review contract failed: {review_status} {reviewed}"
            repeated_review_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
                host=OPS_HOST,
            )
            if repeated_review_status != 409:
                return f"repeated feedback review must return 409, got {repeated_review_status}"
            resolve_status, resolved = _request_json(
                f"{base_url}/owner/product-feedback/resolve",
                method="POST",
                token=admin_token,
                body={"feedback_id": feedback_id},
                host=OPS_HOST,
            )
            resolved_receipt = resolved.get("product_feedback") if isinstance(resolved.get("product_feedback"), dict) else {}
            if resolve_status != 200 or resolved_receipt.get("status") != "resolved":
                return f"internal admin feedback resolve contract failed: {resolve_status} {resolved}"
            unknown_status, _ = _request_json(
                f"{base_url}/owner/product-feedback/review",
                method="POST",
                token=admin_token,
                body={"feedback_id": "feedback_unknown"},
                host=OPS_HOST,
            )
            if unknown_status != 404:
                return f"unknown feedback owner action must return 404, got {unknown_status}"
        finally:
            _terminate_backend_process(process)
    return ""


def _test_http_product_feedback_rate_limit() -> str:
    with tempfile.TemporaryDirectory(prefix="jiejing-product-feedback-rate-limit-", ignore_cleanup_errors=True) as temp_dir:
        database_path = Path(temp_dir) / "saas.sqlite"
        port = _free_port()
        env = _sanitized_backend_test_env(
            {
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false",
                "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "false",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS": "60",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER": "2",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY": "30",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP": "60",
            },
        )
        process = _start_backend_test_process(
            database_path=database_path,
            runtime_database_path=Path(temp_dir) / "runtime.sqlite",
            output_root=temp_dir,
            port=port,
            env=env,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            if not _wait_for_health(base_url):
                return "product-feedback rate-limit backend did not become healthy"
            merchant = _register(base_url, "feedback-rate-limit@example.test")
            token = str(merchant.get("token") or "")
            payload = {
                "idempotency_key": "feedback-rate-limit-key-001",
                "feedback_type": "product_improvement",
                "module_key": "workflow",
                "reason": "unclear",
                "detail": "The shared feedback limiter needs a focused contract.",
                "stage_title": "Shared limiter",
            }
            first_status, first = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=payload,
                ip="198.51.100.77",
            )
            replay_status, replay = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=dict(payload),
                ip="198.51.100.77",
            )
            blocked_payload = dict(payload)
            blocked_payload["idempotency_key"] = "feedback-rate-limit-key-002"
            blocked_payload["detail"] = "This request must be blocked before persistence."
            blocked_status, blocked = _request_json(
                f"{base_url}/product-feedback",
                method="POST",
                token=token,
                body=blocked_payload,
                ip="198.51.100.77",
            )
            if first_status != 201 or first.get("delivered") is not True:
                return f"first feedback submission should pass the shared limiter: {first_status} {first}"
            if replay_status != 200 or replay.get("delivered") is not True:
                return f"idempotent feedback replay should pass but consume limiter capacity: {replay_status} {replay}"
            if blocked_status != 429 or blocked.get("delivered") is True:
                return f"third user submission should be rejected by the dedicated limiter: {blocked_status} {blocked}"
            merchant_rate_limit_fields = {
                "error",
                "status",
                "delivered",
                "retryable",
                "queue_locally",
                "retry_after_seconds",
                "external_provider_action_triggered",
                "real_platform_write_performed",
                "secret_exposed",
            }
            if set(blocked) != merchant_rate_limit_fields:
                return f"429 feedback response exposed non-merchant rate-limit fields: {blocked}"
            serialized_blocked = json.dumps(blocked, ensure_ascii=False)
            if "198.51.100.77" in serialized_blocked:
                return "product feedback rate-limit response exposed the raw client IP"
            list_status, listed = _request_json(f"{base_url}/product-feedback", token=token)
            receipts = listed.get("product_feedback_receipts")
            if list_status != 200 or not isinstance(receipts, list) or len(receipts) != 1:
                return f"rate-limited feedback request persisted a record: {list_status} {listed}"
            with sqlite3.connect(database_path) as connection:
                rows = connection.execute(
                    """
                    select bucket_key_hash, scope, request_count, limit_count
                    from api_rate_limit_buckets
                    where scope like 'product_feedback:%'
                    order by scope
                    """
                ).fetchall()
            scopes = {str(row[1]) for row in rows}
            expected_scopes = {
                "product_feedback:submit:company",
                "product_feedback:submit:ip",
                "product_feedback:submit:user",
            }
            if scopes != expected_scopes:
                return f"product feedback did not use all three dedicated shared buckets: {rows}"
            serialized_rows = json.dumps(rows, ensure_ascii=False)
            if "198.51.100.77" in serialized_rows or any(len(str(row[0])) != 64 for row in rows):
                return f"shared feedback bucket persisted a raw subject instead of hashes: {rows}"
        finally:
            _terminate_backend_process(process)
    return ""


def _test_http_safe_unhandled_error_log() -> str:
    query_secret = "QUERY-SECRET-MUST-NOT-LOG"
    raw_ip = "198.51.100.123"
    with tempfile.TemporaryDirectory(prefix="jiejing-safe-handler-error-", ignore_cleanup_errors=True) as temp_dir:
        port = _free_port()
        env = _sanitized_backend_test_env(
            {
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false",
                "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "false",
            },
        )
        process = _start_backend_test_process(
            database_path=Path(temp_dir) / "saas.sqlite",
            runtime_database_path=Path(temp_dir) / "runtime.sqlite",
            output_root=temp_dir,
            port=port,
            env=env,
        )
        stderr = ""
        try:
            base_url = f"http://127.0.0.1:{port}"
            if not _wait_for_health(base_url):
                return "safe-handler-error backend did not become healthy"
            merchant = _register(base_url, "feedback-safe-handler-error@example.test")
            token = str(merchant.get("token") or "")
            try:
                _request_json(
                    f"{base_url}/queue-jobs/recover-stale",
                    method="POST",
                    token=token,
                    body={"limit": query_secret},
                    ip=raw_ip,
                )
            except Exception:
                pass
        finally:
            _, stderr = _terminate_backend_process(process)
        if "http_request_handler_error" not in stderr:
            return f"unhandled request failure did not emit the safe server event: {stderr[-1200:]}"
        forbidden = (query_secret, raw_ip, "127.0.0.1", "Traceback", "ValueError", "invalid literal")
        if any(value in stderr for value in forbidden):
            return f"unhandled request failure leaked address, query, or exception details: {stderr[-1200:]}"
    return ""


def _test_http_shared_feedback_concurrent_boundary() -> str:
    with tempfile.TemporaryDirectory(prefix="jiejing-shared-feedback-boundary-", ignore_cleanup_errors=True) as temp_dir:
        database_path = Path(temp_dir) / "saas.sqlite"
        runtime_database_path = Path(temp_dir) / "runtime.sqlite"
        env = _sanitized_backend_test_env(
            {
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false",
                "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "false",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS": "60",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER": "3",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY": "30",
                "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP": "60",
            }
        )
        first_port = _free_port()
        second_port = _free_port()
        while second_port == first_port:
            second_port = _free_port()
        ports = (first_port, second_port)
        processes: list[subprocess.Popen[str]] = []
        base_urls = [f"http://127.0.0.1:{port}" for port in ports]
        try:
            for port in ports:
                processes.append(
                    _start_backend_test_process(
                        database_path=database_path,
                        runtime_database_path=runtime_database_path,
                        output_root=temp_dir,
                        port=port,
                        env=env,
                    )
                )
            if not all(_wait_for_health(base_url) for base_url in base_urls):
                return "shared feedback boundary backends did not become healthy"
            merchant = _register(base_urls[0], "feedback-shared-boundary@example.test")
            token = str(merchant.get("token") or "")

            def submit(index: int) -> tuple[int, dict[str, object]]:
                return _request_json(
                    f"{base_urls[index % len(base_urls)]}/product-feedback",
                    method="POST",
                    token=token,
                    ip="203.0.113.211",
                    body={
                        "idempotency_key": f"feedback-shared-boundary-{index:03d}",
                        "feedback_type": "product_improvement",
                        "module_key": "workflow",
                        "reason": "unclear",
                        "detail": f"Shared boundary request {index}",
                    },
                )

            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(submit, range(6)))
            statuses = [status for status, _ in results]
            if statuses.count(201) != 3 or statuses.count(429) != 3 or set(statuses) != {201, 429}:
                return f"shared concurrent feedback boundary was not exactly enforced across processes: {statuses}"
            list_status, listed = _request_json(f"{base_urls[1]}/product-feedback", token=token)
            receipts = listed.get("product_feedback_receipts")
            if list_status != 200 or not isinstance(receipts, list) or len(receipts) != 3:
                return f"shared concurrent feedback boundary persisted the wrong record count: {list_status} {listed}"
            with sqlite3.connect(database_path) as connection:
                row = connection.execute(
                    """
                    select bucket_key_hash, request_count, limit_count
                    from api_rate_limit_buckets
                    where scope = 'product_feedback:submit:user'
                    """
                ).fetchone()
            if not row or len(str(row[0])) != 64 or int(row[1]) != 6 or int(row[2]) != 3:
                return f"shared concurrent user bucket did not preserve the exact hashed boundary: {row}"
        finally:
            for process in processes:
                _terminate_backend_process(process)
    return ""


def _test_product_feedback_limiter_database_failure() -> str:
    raw_ip = "192.0.2.88"
    identity = {
        "user_id": "user_database_failure_must_not_leak",
        "company_id": "company_database_failure_must_not_leak",
    }
    sent: list[tuple[dict[str, object], object]] = []

    class BrokenLimiterRepository:
        def consume_rate_limit_bucket(self, **_: object) -> dict[str, object]:
            raise sqlite3.OperationalError("simulated shared limiter outage")

    class FakeHandler:
        repository = BrokenLimiterRepository()

        @staticmethod
        def _client_ip_for_rate_limit() -> str:
            return raw_ip

        @staticmethod
        def _send_json(payload: dict[str, object], *, status: object = 200) -> None:
            sent.append((payload, status))

    try:
        allowed = SaaSBackendHandler._check_product_feedback_rate_limit(FakeHandler(), identity)
    except Exception as exc:
        return f"shared limiter database failure escaped instead of returning 503: {exc.__class__.__name__}"
    if allowed is not False or len(sent) != 1:
        return f"shared limiter database failure did not fail closed exactly once: allowed={allowed}, sent={sent}"
    payload, status = sent[0]
    if int(status) != 503 or payload.get("status") != 503:
        return f"shared limiter database failure must return 503: {status} {payload}"
    merchant_unavailable_fields = {
        "error",
        "status",
        "delivered",
        "retryable",
        "queue_locally",
        "retry_after_seconds",
        "external_provider_action_triggered",
        "real_platform_write_performed",
        "secret_exposed",
    }
    if set(payload) != merchant_unavailable_fields:
        return f"503 feedback response exposed non-merchant availability fields: {payload}"
    if payload.get("delivered") is True or payload.get("retryable") is not True or payload.get("queue_locally") is not True:
        return f"shared limiter database failure returned an unsafe recovery contract: {payload}"
    serialized = json.dumps(payload, ensure_ascii=False)
    if raw_ip in serialized or any(str(value) in serialized for value in identity.values()):
        return f"shared limiter failure response leaked a raw rate-limit subject: {payload}"
    limiter_source = inspect.getsource(SaaSBackendHandler._check_product_feedback_rate_limit)
    if "self.repository.consume_rate_limit_bucket" not in limiter_source or "self._consume_rate_limit" in limiter_source:
        return "product feedback limiter must prove shared repository use without process-local fallback"
    return ""


def _test_sanitized_backend_subprocess_env() -> str:
    unsafe_host_values = {
        "JIEJING_DATABASE_ENGINE": "postgres",
        "JIEJING_DATABASE_URL": "postgresql://external-database-must-not-be-used.invalid/test",
        "JIEJING_QUEUE_PROVIDER": "redis_streams",
        "JIEJING_QUEUE_URL": "redis://external-queue-must-not-be-used.invalid/0",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "true",
        "JIEJING_EBAY_WRITE_LIVE": "true",
        "JIEJING_STRIPE_SECRET_KEY": "TEST-PROVIDER-SECRET-MUST-NOT-BE-INHERITED",
        "JIEJING_MODEL_BASE_URL": "https://external-model-must-not-be-used.invalid",
        "JIEJING_VAULT_ADDR": "https://external-vault-must-not-be-used.invalid",
    }
    previous = {name: os.environ.get(name) for name in unsafe_host_values}
    try:
        os.environ.update(unsafe_host_values)
        try:
            sanitized = _sanitized_backend_test_env(
                {
                    "JIEJING_INTERNAL_ADMIN_EMAILS": "sanitized-env-admin@example.test",
                    "JIEJING_DATABASE_ENGINE": "postgres",
                }
            )
        except NameError:
            return "shared sanitized backend subprocess environment helper is missing"
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    forced = {
        "JIEJING_DATABASE_ENGINE": "sqlite",
        "JIEJING_DATABASE_ADAPTER": "sqlite-local",
        "JIEJING_QUEUE_PROVIDER": "local_worker",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
        "JIEJING_EBAY_WRITE_LIVE": "false",
        "JIEJING_VAULT_ENABLED": "false",
    }
    if any(sanitized.get(name) != value for name, value in forced.items()):
        return "sanitized backend subprocess environment did not force local no-live adapters"
    forbidden_names = {
        "JIEJING_DATABASE_URL",
        "JIEJING_QUEUE_URL",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_MODEL_BASE_URL",
        "JIEJING_VAULT_ADDR",
    }
    if forbidden_names.intersection(sanitized):
        return "sanitized backend subprocess environment retained external endpoints or provider credentials"
    if sanitized.get("JIEJING_INTERNAL_ADMIN_EMAILS") != "sanitized-env-admin@example.test":
        return "sanitized backend subprocess environment dropped a safe test-only override"
    return ""


def _test_backend_process_cleanup_contract() -> str:
    source = Path(__file__).read_text(encoding="utf-8")
    if "." + "stderr.read(" in source or "." + "stdout.read(" in source:
        return "backend test process pipes must not be read before termination/communicate"
    helper_call = "_terminate_backend_" + "process(process)"
    if source.count(helper_call) < 3:
        return "all spawned feedback backend processes must use the shared termination helper"
    return ""


def _test_product_feedback_persistence_failures_return_503() -> str:
    class FailingRepository:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def list_product_feedback(self, **_: object) -> list[dict[str, object]]:
            raise self.exc

        def create_product_feedback(self, **_: object) -> dict[str, object]:
            raise self.exc

        def transition_product_feedback_status(self, **_: object) -> dict[str, object]:
            raise self.exc

    class FakeHandler:
        def __init__(self, *, path: str, body: dict[str, object], exc: Exception) -> None:
            self.path = path
            self.body = body
            self.repository = FailingRepository(exc)
            self.sent: list[tuple[dict[str, object], object]] = []
            self.close_connection = False

        def _handle_get(self) -> None:
            SaaSBackendHandler._handle_get(self)

        def _handle_post(self) -> None:
            SaaSBackendHandler._handle_post(self)

        @staticmethod
        def _require_safe_mutation_origin() -> bool:
            return True

        @staticmethod
        def _check_expensive_api_rate_limit(**_: object) -> bool:
            return True

        @staticmethod
        def _require_auth() -> dict[str, str]:
            return {"company_id": "company_failure_test", "user_id": "user_failure_test"}

        @staticmethod
        def _check_product_feedback_rate_limit(_: dict[str, object]) -> bool:
            return True

        def _read_json_body(self) -> dict[str, object]:
            return self.body

        @staticmethod
        def _require_platform_internal_admin(_: dict[str, object], __: str) -> bool:
            return True

        @staticmethod
        def _require_operations_console_request(_: str) -> bool:
            return True

        def _handle_service_dependency_exception(self, exc: Exception) -> bool:
            return SaaSBackendHandler._handle_service_dependency_exception(self, exc)

        @staticmethod
        def _is_database_unavailable_exception(exc: Exception) -> bool:
            return SaaSBackendHandler._is_database_unavailable_exception(exc)

        def _send_json(self, payload: dict[str, object], *, status: object = 200) -> None:
            self.sent.append((payload, status))

        def _send_error(self, status: object, message: str) -> None:
            self._send_json({"error": message, "status": int(status)}, status=status)

    cases = (
        (
            "list",
            "GET",
            "/product-feedback",
            {},
            sqlite3.OperationalError("database is locked"),
        ),
        (
            "create",
            "POST",
            "/product-feedback",
            {
                "idempotency_key": "feedback-persistence-failure-key",
                "feedback_type": "product_improvement",
                "module_key": "workflow",
                "reason": "unclear",
            },
            sqlite3.OperationalError("attempt to write a readonly database"),
        ),
        (
            "transition",
            "POST",
            "/owner/product-feedback/resolve",
            {"feedback_id": "feedback_persistence_failure"},
            sqlite3.DatabaseError("database disk image is malformed"),
        ),
    )
    for operation, method, path, body, exc in cases:
        handler = FakeHandler(path=path, body=body, exc=exc)
        try:
            if method == "GET":
                SaaSBackendHandler.do_GET(handler)
            else:
                SaaSBackendHandler.do_POST(handler)
        except Exception as raised:
            return (
                f"{operation} SQLite persistence failure escaped instead of returning 503: "
                f"{raised.__class__.__name__}: {raised}"
            )
        if len(handler.sent) != 1:
            return f"{operation} SQLite persistence failure did not return exactly one response: {handler.sent}"
        payload, status = handler.sent[0]
        if (
            int(status) != 503
            or payload.get("status") != 503
            or payload.get("error") != "database_unavailable"
            or payload.get("retryable") is not True
            or handler.close_connection is not True
        ):
            return f"{operation} SQLite persistence failure returned an unsafe contract: {status} {payload}"
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        if any(marker in serialized for marker in ("locked", "readonly", "malformed", "company_failure_test")):
            return f"{operation} SQLite persistence failure leaked internal details: {payload}"
    if SaaSBackendHandler._is_database_unavailable_exception(
        sqlite3.IntegrityError("unique constraint failed")
    ):
        return "ordinary SQLite integrity violations must not be misclassified as infrastructure outages"

    postgres_error_type = type(
        "OperationalError",
        (Exception,),
        {"__module__": "psycopg.errors"},
    )
    postgres_error = postgres_error_type(
        "select * from oauth_authorization_requests where state_nonce = "
        "'SENTINEL_STATE_VALUE' params=SENTINEL_PARAMS "
        "dsn=postgresql://SENTINEL_USER:SENTINEL_PASSWORD@SENTINEL_HOST/db"
    )
    postgres_error.sqlstate = "08006"
    handler = FakeHandler(
        path="/product-feedback?confirmation_id=SENTINEL_CONFIRMATION_ID",
        body={},
        exc=postgres_error,
    )
    handler.command = "GET"
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        SaaSBackendHandler.do_GET(handler)
    log_lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
    if len(log_lines) != 1:
        return f"Postgres 503 must emit one fixed value-free diagnostic event: count={len(log_lines)}"
    try:
        log_event = json.loads(log_lines[0])
    except json.JSONDecodeError:
        return "Postgres 503 diagnostic must be structured JSON"
    expected_log = {
        "event": "database_dependency_error",
        "route_class": "read_request",
        "error_type": "OperationalError",
        "sqlstate": "08006",
        "secret_exposed": False,
    }
    if log_event != expected_log:
        return f"Postgres 503 diagnostic did not use the fixed allowlisted contract: {log_event}"
    exposed = (stderr.getvalue() + json.dumps(handler.sent, ensure_ascii=False)).lower()
    for forbidden in (
        "sentinel_state_value",
        "sentinel_params",
        "sentinel_user",
        "sentinel_password",
        "sentinel_host",
        "sentinel_confirmation_id",
        "oauth_authorization_requests",
        "select *",
        "postgresql://",
    ):
        if forbidden in exposed:
            return f"Postgres 503 diagnostic leaked a forbidden sentinel category: {forbidden}"

    unknown_error_type = type(
        "SENTINEL_ERROR_TYPE",
        (Exception,),
        {"__module__": "psycopg.errors"},
    )
    unknown_error = unknown_error_type("SENTINEL_EXCEPTION_MESSAGE")
    unknown_error.sqlstate = "SENTINEL_SQLSTATE"
    unknown_handler = FakeHandler(
        path="/product-feedback?trace=SENTINEL_QUERY_VALUE",
        body={},
        exc=unknown_error,
    )
    unknown_handler.command = "GET"
    unknown_stderr = io.StringIO()
    with contextlib.redirect_stderr(unknown_stderr):
        SaaSBackendHandler.do_GET(unknown_handler)
    unknown_lines = [line for line in unknown_stderr.getvalue().splitlines() if line.strip()]
    if len(unknown_lines) != 1:
        return "unknown Postgres diagnostics must still emit exactly one fixed event"
    try:
        unknown_event = json.loads(unknown_lines[0])
    except json.JSONDecodeError:
        return "unknown Postgres diagnostic must remain structured JSON"
    if unknown_event.get("error_type") != "unknown" or unknown_event.get("sqlstate") != "unknown":
        return f"unallowlisted Postgres diagnostics must fail closed: {unknown_event}"
    unknown_serialized = (
        unknown_stderr.getvalue() + json.dumps(unknown_handler.sent, ensure_ascii=False)
    ).lower()
    if "sentinel" in unknown_serialized:
        return "unallowlisted Postgres diagnostics leaked a sentinel value"

    for representative_path, method, expected_route_class in (
        ("/health/deep?trace=SENTINEL_PUBLIC_PATH", "GET", "read_request"),
        ("/auth/register?trace=SENTINEL_PUBLIC_MUTATION", "POST", "write_request"),
        ("/product-feedback?trace=SENTINEL_AUTHENTICATED_PATH", "GET", "read_request"),
    ):
        route_handler = FakeHandler(path=representative_path, body={}, exc=postgres_error)
        route_handler.command = method
        route_stderr = io.StringIO()
        with contextlib.redirect_stderr(route_stderr):
            SaaSBackendHandler._log_database_dependency_error(route_handler, postgres_error)
        try:
            route_event = json.loads(route_stderr.getvalue())
        except json.JSONDecodeError:
            return "database dependency route classification must emit one structured event"
        if route_event.get("route_class") != expected_route_class:
            return f"database dependency route classification was misleading: {route_event}"
        if "sentinel" in route_stderr.getvalue().lower() or "path" in route_event:
            return "database dependency route classification must not record request paths"

    class ThrowingStderr:
        @staticmethod
        def write(_: str) -> int:
            raise OSError("SENTINEL_STDERR_FAILURE")

    stderr_failure_handler = FakeHandler(
        path="/product-feedback",
        body={},
        exc=postgres_error_type("SENTINEL_DATABASE_FAILURE"),
    )
    stderr_failure_handler.command = "GET"
    try:
        with contextlib.redirect_stderr(ThrowingStderr()):
            SaaSBackendHandler.do_GET(stderr_failure_handler)
    except Exception as exc:
        return (
            "diagnostic stderr failure must not interrupt the fixed public 503 response: "
            f"{exc.__class__.__name__}"
        )
    if len(stderr_failure_handler.sent) != 1:
        return "diagnostic stderr failure must still return exactly one public response"
    failure_payload, failure_status = stderr_failure_handler.sent[0]
    if (
        int(failure_status) != 503
        or failure_payload.get("error") != "database_unavailable"
        or failure_payload.get("retryable") is not True
        or stderr_failure_handler.close_connection is not True
    ):
        return "diagnostic stderr failure changed the fixed public 503 contract"
    return ""


def _test_product_feedback_company_and_ip_denial() -> str:
    for denied_scope in ("product_feedback:submit:company", "product_feedback:submit:ip"):
        calls: list[str] = []
        sent: list[tuple[dict[str, object], object]] = []

        class SelectiveDenialRepository:
            @staticmethod
            def consume_rate_limit_bucket(**kwargs: object) -> dict[str, object]:
                scope = str(kwargs.get("scope") or "")
                calls.append(scope)
                return {
                    "allowed": scope != denied_scope,
                    "retry_after_seconds": 17,
                }

        class FakeHandler:
            repository = SelectiveDenialRepository()

            @staticmethod
            def _client_ip_for_rate_limit() -> str:
                return "192.0.2.111"

            @staticmethod
            def _send_json(payload: dict[str, object], *, status: object = 200) -> None:
                sent.append((payload, status))

        allowed = SaaSBackendHandler._check_product_feedback_rate_limit(
            FakeHandler(),
            {"user_id": "user_scope_denial", "company_id": "company_scope_denial"},
        )
        if allowed is not False or len(sent) != 1 or int(sent[0][1]) != 429:
            return f"{denied_scope} denial did not return 429: allowed={allowed}, sent={sent}"
        if set(calls) != {
            "product_feedback:submit:user",
            "product_feedback:submit:company",
            "product_feedback:submit:ip",
        }:
            return f"{denied_scope} denial skipped a dedicated scope: {calls}"
        serialized = json.dumps(sent[0][0], ensure_ascii=False)
        if denied_scope in serialized or "192.0.2.111" in serialized:
            return f"{denied_scope} denial leaked internal scope or IP: {sent[0][0]}"
    return ""


def _test_product_feedback_limiter_configuration_bounds() -> str:
    env_names = {
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS": "999999999",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER": "999999999",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY": "999999999",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP": "999999999",
    }
    previous = {name: os.environ.get(name) for name in env_names}
    calls: list[dict[str, object]] = []

    class RecordingLimiterRepository:
        def consume_rate_limit_bucket(self, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            return {"allowed": True, "retry_after_seconds": 1}

    class FakeHandler:
        repository = RecordingLimiterRepository()

        @staticmethod
        def _client_ip_for_rate_limit() -> str:
            return "192.0.2.99"

        @staticmethod
        def _send_json(_: dict[str, object], *, status: object = 200) -> None:
            raise AssertionError(f"bounded valid limiter checks must remain allowed, got HTTP {status}")

    try:
        os.environ.update(env_names)
        allowed = SaaSBackendHandler._check_product_feedback_rate_limit(
            FakeHandler(),
            {"user_id": "user_bound", "company_id": "company_bound"},
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if allowed is not True or len(calls) != 3:
        return f"bounded product feedback limiter did not perform all three checks: {calls}"
    limits_by_scope = {str(call.get("scope")): int(call.get("limit") or 0) for call in calls}
    windows = {int(call.get("window_seconds") or 0) for call in calls}
    expected_limits = {
        "product_feedback:submit:user": 120,
        "product_feedback:submit:company": 300,
        "product_feedback:submit:ip": 600,
    }
    if limits_by_scope != expected_limits or windows != {3600}:
        return f"product feedback limiter environment overrides were not capped: {limits_by_scope}, windows={windows}"
    return ""


def _register(base_url: str, email: str) -> dict[str, object]:
    status, body = _request_json(
        f"{base_url}/auth/register",
        method="POST",
        body={
            "email": email,
            "password": "Product-feedback-http-test-2026",
            "company_name": "Product Feedback HTTP Test",
        },
    )
    if status != 201:
        raise RuntimeError(f"product-feedback test registration failed with HTTP {status}: {body}")
    return body


def _sanitized_backend_test_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    inherited_runtime_names = {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    env = {
        name: value
        for name in inherited_runtime_names
        if (value := os.environ.get(name)) is not None
    }
    allowed_override_names = {
        "JIEJING_INTERNAL_ADMIN_EMAILS",
        "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER",
        "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS",
        "JIEJING_SAFE_ACCESS_LOG",
        "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED",
    }
    env.update(
        {
            name: str(value)
            for name, value in (overrides or {}).items()
            if name in allowed_override_names
        }
    )
    env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_SAAS_SESSION_SECRET": "product-feedback-tests-only-not-a-production-secret",
            "JIEJING_DATABASE_ENGINE": "sqlite",
            "JIEJING_DATABASE_ADAPTER": "sqlite-local",
            "JIEJING_QUEUE_PROVIDER": "local_worker",
            "JIEJING_VAULT_PROVIDER": "secret_ref_only",
            "JIEJING_VAULT_ENABLED": "false",
            "JIEJING_EXECUTION_ADAPTER": "demo_no_platform_write",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "false",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "false",
            "JIEJING_EBAY_READ_ONLY_LIVE": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_ALLOW_HERMES_ADAPTERS": "false",
            "JIEJING_MODEL_DISABLE_LIVE": "true",
            "JIEJING_PUBLIC_SEARCH_LIVE": "false",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _terminate_backend_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
    return stdout or "", stderr or ""


def _start_backend_test_process(
    *,
    database_path: Path,
    runtime_database_path: Path,
    output_root: str | Path,
    port: int,
    env: dict[str, str],
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(database_path),
            "--runtime-db",
            str(runtime_database_path),
            "--output-root",
            str(output_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    body: dict[str, object] | None = None,
    ip: str = "203.0.113.10",
    host: str = "",
) -> tuple[int, dict[str, object]]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "JiejingProductFeedbackTest/1.0",
        "X-Forwarded-For": ip,
    }
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
        headers["X-Forwarded-Proto"] = "https"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return int(exc.code), parsed


def _request_raw_json(
    url: str,
    *,
    token: str,
    raw_body: bytes,
    ip: str = "203.0.113.10",
) -> tuple[int, dict[str, object]]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "JiejingProductFeedbackTest/1.0",
        "X-Forwarded-For": ip,
    }
    request = urllib.request.Request(url, data=raw_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), json.loads(payload) if payload else {}


def _wait_for_health(base_url: str) -> bool:
    for _ in range(100):
        try:
            status, body = _request_json(f"{base_url}/health")
        except urllib.error.URLError:
            time.sleep(0.1)
            continue
        if status == 200 and body.get("status") == "ok":
            return True
        time.sleep(0.1)
    return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
