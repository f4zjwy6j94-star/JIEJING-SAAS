#!/usr/bin/env python3
"""Postgres-shaped OAuth approval timestamp regressions."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402


class _Cursor:
    def __init__(self, *, one: dict[str, Any] | None = None, many: list[dict[str, Any]] | None = None, rowcount: int = -1) -> None:
        self._one = one
        self._many = list(many or [])
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self._one

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._many)


class _ApprovedOAuthPostgresBoundary:
    """Minimal DB boundary with psycopg-style dict rows and timestamptz values."""

    def __init__(self, *, decided_at: Any, consume_rowcount: int = 1) -> None:
        self.confirmation_status = "approved"
        self.consume_rowcount = consume_rowcount
        self.oauth_request_inserts = 0
        self.audit_inserts = 0
        self.confirmation = {
            "confirmation_id": "confirmation-fixture",
            "company_id": "company-fixture",
            "store_id": "store-fixture",
            "task_id": None,
            "runtime_run_id": "new_ebay_account_oauth_authorization_gate",
            "action_type": "ebay_oauth_scope_change",
            "title": "Postgres datetime approval",
            "status": "approved",
            "default_action": "hold",
            "created_at": "2026-08-11T00:00:00+00:00",
            "item_json": {
                "source": "new_ebay_account_low_risk_smoke",
                "requested_step": "new_account_oauth_authorization_gate",
                "scope_profile": "seller_read_only",
                "secret_exposed": False,
            },
            "decided_by": "owner-fixture",
            "decided_at": decided_at,
            "decision_note": "Approved",
        }

    def __enter__(self) -> "_ApprovedOAuthPostgresBoundary":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        normalized = " ".join(sql.lower().split())
        if "select store_id, platform from stores" in normalized:
            return _Cursor(one={"store_id": "store-fixture", "platform": "ebay"})
        if "from platform_connections" in normalized:
            return _Cursor(many=[])
        if "from oauth_authorization_requests" in normalized and "status in" in normalized:
            return _Cursor(many=[])
        if "select * from confirmations" in normalized:
            row = dict(self.confirmation)
            row["status"] = self.confirmation_status
            return _Cursor(one=row)
        if normalized.startswith("update confirmations set status = 'executed'"):
            if self.confirmation_status != "approved" or self.consume_rowcount != 1:
                return _Cursor(rowcount=0)
            self.confirmation_status = "executed"
            return _Cursor(rowcount=1)
        if normalized.startswith("insert into oauth_authorization_requests"):
            self.oauth_request_inserts += 1
            return _Cursor(rowcount=1)
        if normalized.startswith("insert into audit_logs"):
            self.audit_inserts += 1
            return _Cursor(rowcount=1)
        raise AssertionError(f"unexpected SQL shape: {normalized[:80]}")


class _ExpiredOAuthPostgresBoundary:
    def __init__(self, *, decided_at: datetime) -> None:
        self.old_status = "approved"
        self.new_confirmation: dict[str, Any] | None = None
        self.confirmation_inserts = 0
        self.audit_inserts = 0
        self.memory_inserts = 0
        self.old_confirmation = {
            "confirmation_id": "expired-confirmation-fixture",
            "company_id": "company-fixture",
            "store_id": "store-fixture",
            "task_id": None,
            "runtime_run_id": "new_ebay_account_oauth_authorization_gate",
            "action_type": "ebay_oauth_scope_change",
            "title": "Expired Postgres datetime approval",
            "status": "approved",
            "default_action": "hold",
            "created_at": decided_at - timedelta(minutes=1),
            "item_json": {
                "source": "new_ebay_account_low_risk_smoke",
                "requested_step": "new_account_oauth_authorization_gate",
                "scope_profile": "seller_read_only",
                "secret_exposed": False,
            },
            "decided_by": "owner-fixture",
            "decided_at": decided_at,
            "decision_note": "Approved",
        }

    def __enter__(self) -> "_ExpiredOAuthPostgresBoundary":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        normalized = " ".join(sql.lower().split())
        if "select store_id, platform from stores" in normalized:
            return _Cursor(one={"store_id": "store-fixture", "platform": "ebay"})
        if "select * from confirmations" in normalized and "status in ('pending', 'approved')" in normalized:
            row = dict(self.old_confirmation)
            row["status"] = self.old_status
            return _Cursor(many=[row] if self.old_status in {"pending", "approved"} else [])
        if "select request_json from oauth_authorization_requests" in normalized:
            return _Cursor(many=[])
        if normalized.startswith("update confirmations set status = 'expired'"):
            if self.old_status != "approved":
                return _Cursor(rowcount=0)
            self.old_status = "expired"
            return _Cursor(rowcount=1)
        if normalized.startswith("insert into confirmations"):
            self.confirmation_inserts += 1
            self.new_confirmation = {
                "confirmation_id": params[0],
                "company_id": params[1],
                "store_id": params[2],
                "task_id": params[3],
                "runtime_run_id": params[4],
                "action_type": params[5],
                "title": params[6],
                "status": params[7],
                "default_action": params[8],
                "created_at": params[9],
                "item_json": params[10],
                "decided_by": params[11],
                "decided_at": params[12],
                "decision_note": params[13],
            }
            return _Cursor(rowcount=1)
        if normalized.startswith("insert into audit_logs"):
            self.audit_inserts += 1
            return _Cursor(rowcount=1)
        if "select memory_id, created_at from merchant_memory" in normalized:
            return _Cursor(one=None)
        if normalized.startswith("insert into merchant_memory"):
            self.memory_inserts += 1
            return _Cursor(rowcount=1)
        if "select * from confirmations where company_id" in normalized:
            if self.new_confirmation and params[1] == self.new_confirmation["confirmation_id"]:
                return _Cursor(one=dict(self.new_confirmation))
            return _Cursor(one=None)
        raise AssertionError(f"unexpected SQL shape: {normalized[:80]}")


class _PostgresShapedRepository(SaaSRepository):
    def __init__(self, boundary: Any) -> None:
        super().__init__(ROOT / "output" / "unused-postgres-oauth-contract.sqlite", database_engine="postgres", database_url="postgresql://unused.invalid/jiejing")
        self._boundary = boundary

    def initialize(self) -> None:
        return None

    def _connect(self) -> _ApprovedOAuthPostgresBoundary:
        return self._boundary


def main() -> int:
    boundary = _ApprovedOAuthPostgresBoundary(
        decided_at=datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=5)
    )
    repo = _PostgresShapedRepository(boundary)
    result = repo.create_approved_read_only_oauth_authorization_request(
        company_id="company-fixture",
        store_id="store-fixture",
        user_id="owner-fixture",
        confirmation_id="confirmation-fixture",
        plan={
            "platform": "ebay",
            "status": "ready_to_redirect",
            "state_nonce": "state-fixture",
            "scopes": ["https://api.ebay.com/oauth/api_scope"],
            "scope_profile": "seller_read_only",
            "authorization_url": None,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    )
    if result.get("status") != "ready_to_redirect":
        raise AssertionError("a fresh Postgres timestamptz approval must create the read-only plan exactly once")
    if boundary.confirmation_status != "executed" or boundary.oauth_request_inserts != 1 or boundary.audit_inserts != 1:
        raise AssertionError("the fresh Postgres approval must be consumed with one request and one audit")

    explicit_iso_boundary = _ApprovedOAuthPostgresBoundary(
        decided_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    )
    explicit_iso_result = _PostgresShapedRepository(
        explicit_iso_boundary
    ).create_approved_read_only_oauth_authorization_request(
        company_id="company-fixture",
        store_id="store-fixture",
        user_id="owner-fixture",
        confirmation_id="confirmation-fixture",
        plan={
            "platform": "ebay",
            "status": "ready_to_redirect",
            "state_nonce": "explicit-iso-state-fixture",
            "scopes": ["https://api.ebay.com/oauth/api_scope"],
            "scope_profile": "seller_read_only",
            "authorization_url": None,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    )
    if explicit_iso_result.get("status") != "ready_to_redirect":
        raise AssertionError("the existing explicit ISO timestamp contract must remain accepted")

    invalid_timestamps = (
        datetime.now() - timedelta(minutes=5),
        datetime.now(timezone.utc) + timedelta(hours=1),
        datetime.now(timezone.utc) - timedelta(minutes=16),
        "not-an-explicit-iso-timestamp",
    )
    for invalid_timestamp in invalid_timestamps:
        invalid_boundary = _ApprovedOAuthPostgresBoundary(decided_at=invalid_timestamp)
        invalid_repo = _PostgresShapedRepository(invalid_boundary)
        try:
            invalid_repo.create_approved_read_only_oauth_authorization_request(
                company_id="company-fixture",
                store_id="store-fixture",
                user_id="owner-fixture",
                confirmation_id="confirmation-fixture",
                plan={
                    "platform": "ebay",
                    "status": "ready_to_redirect",
                    "state_nonce": "invalid-state-fixture",
                    "scopes": ["https://api.ebay.com/oauth/api_scope"],
                    "scope_profile": "seller_read_only",
                    "authorization_url": None,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
        except ValueError as exc:
            if str(exc) != "oauth_plan_exact_approval_required":
                raise AssertionError("invalid timestamp rejection must use the fixed public code") from exc
            if getattr(exc, "diagnostic_code", "") != "approval_predicate_rejected":
                raise AssertionError("invalid timestamp rejection must expose only the fixed internal predicate branch") from exc
        else:
            raise AssertionError("naive, future, expired, and malformed approval timestamps must fail closed")
        if invalid_boundary.oauth_request_inserts != 0 or invalid_boundary.confirmation_status != "approved":
            raise AssertionError("invalid timestamps must not consume approval or create OAuth state")

    consume_conflict_boundary = _ApprovedOAuthPostgresBoundary(
        decided_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        consume_rowcount=0,
    )
    try:
        _PostgresShapedRepository(
            consume_conflict_boundary
        ).create_approved_read_only_oauth_authorization_request(
            company_id="company-fixture",
            store_id="store-fixture",
            user_id="owner-fixture",
            confirmation_id="confirmation-fixture",
            plan={
                "platform": "ebay",
                "status": "ready_to_redirect",
                "state_nonce": "consume-conflict-state-fixture",
                "scopes": ["https://api.ebay.com/oauth/api_scope"],
                "scope_profile": "seller_read_only",
                "authorization_url": None,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
        )
    except ValueError as exc:
        if str(exc) != "oauth_plan_exact_approval_required":
            raise AssertionError("consume conflict must preserve the fixed public error") from exc
        if getattr(exc, "diagnostic_code", "") != "approval_consume_conflict":
            raise AssertionError("consume conflict must expose only the fixed internal CAS branch") from exc
    else:
        raise AssertionError("a zero-row approval consume must fail closed")
    if consume_conflict_boundary.oauth_request_inserts != 0:
        raise AssertionError("consume conflict must not create OAuth state")

    expired_boundary = _ExpiredOAuthPostgresBoundary(
        decided_at=datetime.now(timezone.utc) - timedelta(minutes=16)
    )
    expired_repo = _PostgresShapedRepository(expired_boundary)
    replacement = expired_repo.create_read_only_oauth_confirmation(
        company_id="company-fixture",
        store_id="store-fixture",
        user_id="owner-fixture",
    )
    if replacement.get("status") != "pending":
        raise AssertionError("an expired Postgres timestamptz approval must produce one replacement pending card")
    if (
        expired_boundary.old_status != "expired"
        or expired_boundary.confirmation_inserts != 1
        or expired_boundary.audit_inserts != 2
        or expired_boundary.memory_inserts != 1
    ):
        raise AssertionError("expired Postgres approval replacement must remain atomic and auditable")

    for diagnostic_code in ("approval_predicate_rejected", "approval_consume_conflict"):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            SaaSBackendHandler._log_oauth_plan_exact_approval_rejection(object(), diagnostic_code)
        lines = [line for line in stderr.getvalue().splitlines() if line]
        if len(lines) != 1:
            raise AssertionError("each OAuth approval rejection must emit one fixed internal event")
        if json.loads(lines[0]) != {
            "event": "oauth_plan_exact_approval_rejected",
            "diagnostic_code": diagnostic_code,
            "secret_exposed": False,
        }:
            raise AssertionError("OAuth approval diagnostics must contain only allowlisted fixed fields")

    unknown_stderr = io.StringIO()
    with contextlib.redirect_stderr(unknown_stderr):
        SaaSBackendHandler._log_oauth_plan_exact_approval_rejection(
            object(), "SENTINEL_IDENTIFIER_MUST_NOT_LEAK"
        )
    if json.loads(unknown_stderr.getvalue()).get("diagnostic_code") != "unknown":
        raise AssertionError("unallowlisted OAuth approval diagnostics must fail closed")
    if "sentinel" in unknown_stderr.getvalue().lower():
        raise AssertionError("OAuth approval diagnostics leaked an unallowlisted value")

    class _ThrowingStderr:
        @staticmethod
        def write(_: str) -> int:
            raise OSError("diagnostic sink unavailable")

    with contextlib.redirect_stderr(_ThrowingStderr()):
        SaaSBackendHandler._log_oauth_plan_exact_approval_rejection(
            object(), "approval_predicate_rejected"
        )
    print("PASS jiejing_postgres_oauth_datetime_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
