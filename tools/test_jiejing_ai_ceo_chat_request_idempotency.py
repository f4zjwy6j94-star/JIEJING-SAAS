#!/usr/bin/env python3
"""Focused contracts for tenant-scoped AI CEO chat request idempotency."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
import sqlite3
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import (
    _ai_ceo_chat_request_fingerprint,
    _resolve_ai_ceo_chat_final_response,
)
from jiejing_saas.repository import SaaSRepository


def main() -> int:
    fingerprint_context = {
        "contract_version": "ai_ceo_chat_request_fingerprint_v1",
        "message": "识别图片并生成 Listing 草稿",
        "command": {"id": "command-asset-replay"},
        "conversation_history": [],
        "source_asset_ids": ["media_src_one", "media_src_two"],
        "listing_project_identity": {"key": "listing-project-one"},
        "active_listing_context": {"product_name": "平板电脑支架"},
        "supplier_fact_attestation": {"supplier_facts_verified": False},
        "client_now": "2026-09-01T10:00:00+08:00",
        "client_timezone": "Asia/Shanghai",
    }
    fingerprint = _ai_ceo_chat_request_fingerprint(
        secret=b"server-only-fingerprint-secret",
        canonical_request=fingerprint_context,
    )
    assert fingerprint != _ai_ceo_chat_request_fingerprint(
        secret=b"server-only-fingerprint-secret",
        canonical_request={**fingerprint_context, "source_asset_ids": ["media_src_one", "media_src_three"]},
    )
    assert fingerprint != _ai_ceo_chat_request_fingerprint(
        secret=b"server-only-fingerprint-secret",
        canonical_request={
            **fingerprint_context,
            "supplier_fact_attestation": {"supplier_facts_verified": True},
        },
    )

    with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-idempotency-", ignore_cleanup_errors=True) as temp:
        database_path = Path(temp) / "saas.sqlite"
        repository = SaaSRepository(database_path)
        first = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-abc12345",
            payload_fingerprint="a" * 64,
        )
        duplicate = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-abc12345",
            payload_fingerprint="a" * 64,
        )

        assert first["claim_state"] == "claimed", first
        assert duplicate["claim_state"] == "in_progress", duplicate
        assert first["request_task"]["task_id"] == duplicate["request_task"]["task_id"]
        assert first["request_task"]["task_id"].startswith("task_ai_ceo_request_")
        assert first["request_task"]["input"]["idempotency_key_hash"]
        assert "ceo-command-abc12345" not in str(first["request_task"]["input"])

        conflict = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-abc12345",
            payload_fingerprint="b" * 64,
        )
        assert conflict["claim_state"] == "conflict", conflict

        first_response_payload = {
            "reply": "safe cached reply",
            "model_usage": {
                "input_tokens": 31,
                "output_tokens": 97,
                "total_tokens": 128,
                "access_token": "must-never-be-replayed",
            },
            "model_secret_resolution": {
                "status": "ready",
                "secret_value": "must-never-be-replayed",
            },
            "provider": {"api_key": "must-never-be-replayed"},
            "secret_exposed": False,
        }
        first_finalize = repository.finalize_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            request_task_id=first["request_task"]["task_id"],
            terminal_status="completed",
            response_status=200,
            response_payload=first_response_payload,
        )
        assert first_finalize["_idempotent_finalize_applied"] is True, first_finalize
        first_outgoing_payload, first_outgoing_status = _resolve_ai_ceo_chat_final_response(
            attempted_payload=first_response_payload,
            attempted_status=HTTPStatus.OK,
            finalized_request=first_finalize,
            request_task_id=first["request_task"]["task_id"],
        )
        assert first_outgoing_status == HTTPStatus.OK
        assert first_outgoing_payload["model_usage"] == first_finalize["output"]["response_payload"]["model_usage"]
        assert first_outgoing_payload["model_secret_resolution"] == {
            "status": "ready",
            "secret_value": "[REDACTED]",
        }
        assert "must-never-be-replayed" not in str(first_outgoing_payload)
        replay = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-abc12345",
            payload_fingerprint="a" * 64,
        )
        assert replay["claim_state"] == "replay", replay
        assert replay["replay"]["response_status"] == 200
        assert replay["replay"]["response_payload"]["reply"] == "safe cached reply"
        assert replay["replay"]["response_payload"]["model_usage"] == {
            "input_tokens": 31,
            "output_tokens": 97,
            "total_tokens": 128,
            "access_token": "[REDACTED]",
        }
        assert "must-never-be-replayed" not in str(replay["replay"])
        assert replay["replay"]["secret_exposed"] is False
        assert replay["replay"]["real_platform_writes_enabled"] is False

        other_tenant = repository.claim_ai_ceo_chat_request(
            company_id="company_b",
            store_id="store_b",
            user_id="user_b",
            idempotency_key="ceo-command-abc12345",
            payload_fingerprint="a" * 64,
        )
        assert other_tenant["claim_state"] == "claimed", other_tenant
        assert other_tenant["request_task"]["task_id"] != first["request_task"]["task_id"]
        assert repository.get_task(
            company_id="company_b", task_id=first["request_task"]["task_id"]
        ) is None

        orphan = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-orphan123",
            payload_fingerprint="c" * 64,
        )
        orphan_task_id = orphan["request_task"]["task_id"]
        stale_updated_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with sqlite3.connect(database_path) as conn:
            conn.execute(
                "update tasks set updated_at = ? where task_id = ?",
                (stale_updated_at, orphan_task_id),
            )

        reconciled_orphan = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-orphan123",
            payload_fingerprint="c" * 64,
        )
        assert reconciled_orphan["claim_state"] == "replay", reconciled_orphan
        assert reconciled_orphan["request_task"]["status"] == "blocked", reconciled_orphan
        orphan_replay = reconciled_orphan["replay"]
        assert orphan_replay["idempotent_replay_ready"] is True
        assert orphan_replay["response_status"] == 409
        orphan_payload = orphan_replay["response_payload"]
        assert orphan_payload["ai_ceo_chat_request"]["status"] == "reconciliation_required"
        assert orphan_payload["ai_ceo_chat"]["status"] == "request_reconciliation_required"
        assert orphan_payload["usage_consumed"] is None
        assert orphan_payload["usage_consumed_known"] is False
        assert orphan_payload["listing_created"] is False
        assert orphan_payload["real_platform_writes_enabled"] is False
        assert orphan_payload["secret_exposed"] is False

        repeated_orphan = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-orphan123",
            payload_fingerprint="c" * 64,
        )
        assert repeated_orphan["claim_state"] == "replay", repeated_orphan
        assert repeated_orphan["replay"] == orphan_replay

        late_finalize = repository.finalize_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            request_task_id=orphan_task_id,
            terminal_status="completed",
            response_status=201,
            response_payload={
                "ai_ceo_chat": {"status": "model_answered", "answer": "late result"},
                "usage_consumed": True,
                "listing_created": True,
            },
        )
        assert late_finalize["_idempotent_finalize_applied"] is False, late_finalize
        assert late_finalize["output"] == orphan_replay
        outgoing_payload, outgoing_status = _resolve_ai_ceo_chat_final_response(
            attempted_payload={
                "ai_ceo_chat": {"status": "model_answered", "answer": "late result"},
                "usage_consumed": True,
                "listing_created": True,
            },
            attempted_status=HTTPStatus.CREATED,
            finalized_request=late_finalize,
            request_task_id=orphan_task_id,
        )
        assert outgoing_status == HTTPStatus.CONFLICT, outgoing_status
        assert outgoing_payload["ai_ceo_chat_request"]["status"] == "reconciliation_required"
        assert outgoing_payload["ai_ceo_chat"]["status"] == "request_reconciliation_required"
        assert outgoing_payload["usage_consumed"] is None
        assert outgoing_payload["usage_consumed_known"] is False
        assert outgoing_payload["listing_created"] is False
        assert outgoing_payload["idempotent_replay"] is True
        assert "late result" not in str(outgoing_payload)
        after_late_finalize = repository.claim_ai_ceo_chat_request(
            company_id="company_a",
            store_id="store_a",
            user_id="user_a",
            idempotency_key="ceo-command-orphan123",
            payload_fingerprint="c" * 64,
        )
        assert after_late_finalize["request_task"]["status"] == "blocked", after_late_finalize
        assert after_late_finalize["replay"] == orphan_replay

        app_source = (ROOT / "app.js").read_text(encoding="utf-8")
        assert "usage_consumed: saasTriStateBoolean(errorPayload.usage_consumed)" in app_source
        assert "usage_consumed: saasTriStateBoolean(payload?.usage_consumed)" in app_source

        api_source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
        endpoint_start = api_source.index(
            'parts[0] == "stores" and parts[2] == "merchant-ceo" and parts[3] == "chat"'
        )
        endpoint_source = api_source[endpoint_start : api_source.index("\n        if ", endpoint_start + 20)]
        replay_position = endpoint_source.index('request_claim["claim_state"] == "replay"')
        source_read_position = endpoint_source.index("self.media_source_asset_store.read_for_provider(")
        assert replay_position < source_read_position, "terminal replay must not depend on source asset availability"
        assert '"source_asset_ids": source_asset_ids' in endpoint_source

    print("PASS jiejing_ai_ceo_chat_request_idempotency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
