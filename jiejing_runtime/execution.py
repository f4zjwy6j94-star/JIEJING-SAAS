"""Execution service boundary for real-world actions.

Adapters generate reports and confirmation items. They do not execute eBay,
payment, refund, ad, procurement, or policy actions directly. This service is
the only future place where confirmed actions can cross into platform APIs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .models import now_iso
from .policies import HIGH_RISK_ACTIONS
from .execution_preflight import ExecutionPreflightChecker, LOW_RISK_ACTIONS


@dataclass(slots=True)
class ExecutionRequest:
    action_type: str
    task_id: str
    user_id: str
    company_id: str
    store_id: str
    platform: str
    payload: dict[str, Any] = field(default_factory=dict)
    confirmation_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    idempotency_key: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    status: str
    action_type: str
    task_id: str
    message: str
    created_at: str = field(default_factory=now_iso)
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action_type": self.action_type,
            "task_id": self.task_id,
            "message": self.message,
            "created_at": self.created_at,
            "audit": self.audit,
        }


class ExecutionService:
    """Strict execution boundary used by the Runtime and future backend."""

    def __init__(self, demo_mode: bool = True) -> None:
        self.demo_mode = demo_mode
        self.preflight_checker = ExecutionPreflightChecker()

    def preflight(self, request: ExecutionRequest) -> dict[str, Any]:
        return self.preflight_checker.review(request)

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        preflight = self.preflight(request)
        if self._is_high_risk(request, preflight) and not self._has_confirmation(request):
            return ExecutionResult(
                status="blocked_confirmation_required",
                action_type=request.action_type,
                task_id=request.task_id,
                message="High-risk action is blocked until the merchant confirms it.",
                audit=self._audit(request, blocked_reason="missing_confirmation", preflight=preflight),
            )

        if self.demo_mode:
            return ExecutionResult(
                status="simulated_no_platform_write",
                action_type=request.action_type,
                task_id=request.task_id,
                message=(
                    "ExecutionService accepted the confirmed action in demo mode and recorded the handoff. "
                    "No real platform action was executed. Production mode still requires the preflight package to pass."
                ),
                audit=self._audit(
                    request,
                    blocked_reason=None,
                    execution_mode="demo_no_platform_write",
                    preflight=preflight,
                ),
            )

        if preflight.get("status") == "blocked_missing_execution_facts":
            return ExecutionResult(
                status="blocked_preflight_missing",
                action_type=request.action_type,
                task_id=request.task_id,
                message="Execution is blocked because required action facts are missing.",
                audit=self._audit(
                    request,
                    blocked_reason="preflight_missing_execution_facts",
                    execution_mode="blocked",
                    preflight=preflight,
                ),
            )

        if str(preflight.get("canonical_action_type") or request.action_type) in LOW_RISK_ACTIONS:
            return ExecutionResult(
                status="ready_low_risk_internal_handoff",
                action_type=request.action_type,
                task_id=request.task_id,
                message="Request passed boundary checks for an internal low-risk handoff. No eBay write or public listing was executed.",
                audit=self._audit(
                    request,
                    blocked_reason=None,
                    execution_mode="internal_low_risk_handoff",
                    preflight=preflight,
                ),
            )

        return ExecutionResult(
            status="ready_for_platform_adapter",
            action_type=request.action_type,
            task_id=request.task_id,
            message="Request passed boundary checks and is ready for a platform-specific adapter.",
            audit=self._audit(
                request,
                blocked_reason=None,
                execution_mode="platform_adapter_required",
                preflight=preflight,
            ),
        )

    def _has_confirmation(self, request: ExecutionRequest) -> bool:
        return bool(request.confirmation_id and request.confirmed_by and request.confirmed_at)

    def _is_high_risk(self, request: ExecutionRequest, preflight: dict[str, Any]) -> bool:
        canonical = str(preflight.get("canonical_action_type") or request.action_type)
        return request.action_type in HIGH_RISK_ACTIONS or canonical in HIGH_RISK_ACTIONS or canonical not in LOW_RISK_ACTIONS

    def _audit(
        self,
        request: ExecutionRequest,
        blocked_reason: str | None,
        execution_mode: str = "blocked",
        preflight: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "user_id": request.user_id,
            "company_id": request.company_id,
            "store_id": request.store_id,
            "platform": request.platform,
            "confirmation_id": request.confirmation_id,
            "confirmed_by": request.confirmed_by,
            "confirmed_at": request.confirmed_at,
            "idempotency_key_present": bool(_idempotency_key(request)),
            "idempotency": self._idempotency_boundary(request=request, preflight=preflight),
            "execution_intent": self._execution_intent(request=request, preflight=preflight),
            "demo_mode": self.demo_mode,
            "blocked_reason": blocked_reason,
            "execution_mode": execution_mode,
            "preflight": preflight or self.preflight(request),
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
        }

    def _idempotency_boundary(self, *, request: ExecutionRequest, preflight: dict[str, Any] | None) -> dict[str, Any]:
        canonical_action = str((preflight or {}).get("canonical_action_type") or request.action_type)
        key = _idempotency_key(request)
        return {
            "idempotency_required": canonical_action in HIGH_RISK_ACTIONS or canonical_action not in LOW_RISK_ACTIONS,
            "idempotency_key": key,
            "duplicate_prevention_key": _duplicate_prevention_key(request=request, canonical_action=canonical_action, idempotency_key=key),
            "payload_hash": _payload_hash(request.payload),
            "safe_to_retry_queue_job": bool(key),
            "same_key_same_payload_required": True,
        }

    def _execution_intent(self, *, request: ExecutionRequest, preflight: dict[str, Any] | None) -> dict[str, Any]:
        canonical_action = str((preflight or {}).get("canonical_action_type") or request.action_type)
        low_risk = canonical_action in LOW_RISK_ACTIONS
        platform_adapter = f"{request.platform}.{canonical_action}"
        if canonical_action == "prepare_listing_draft":
            platform_adapter = "jiejing_internal.prepare_listing_draft"
        return {
            "intent_id": _duplicate_prevention_key(
                request=request,
                canonical_action=canonical_action,
                idempotency_key=_idempotency_key(request),
            ),
            "canonical_action_type": canonical_action,
            "platform": request.platform,
            "task_id": request.task_id,
            "store_id": request.store_id,
            "confirmation_id": request.confirmation_id,
            "platform_adapter": platform_adapter,
            "platform_adapter_called": False,
            "requires_preflight_status": "ready_low_risk" if low_risk else "ready_for_platform_adapter",
            "requires_confirmation": not low_risk,
            "audit_log_required": True,
            "creates_public_listing": False,
            "writes_to_ebay": False,
            "stores_internal_draft_only": canonical_action == "prepare_listing_draft",
            "confirmation_center_required_before_public_publish": True,
        }


def _idempotency_key(request: ExecutionRequest) -> str | None:
    value = request.idempotency_key or request.payload.get("idempotency_key")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _duplicate_prevention_key(
    *,
    request: ExecutionRequest,
    canonical_action: str,
    idempotency_key: str | None,
) -> str:
    stable_key = idempotency_key or "missing_idempotency_key"
    raw = "|".join(
        [
            request.company_id,
            request.store_id,
            request.platform,
            canonical_action,
            request.confirmation_id or "unconfirmed",
            stable_key,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
