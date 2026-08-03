"""Pure validation contract for tenant-scoped merchant product feedback."""

from __future__ import annotations

import html
import hashlib
import json
import re
from typing import Any


PRODUCT_FEEDBACK_TYPES = {"product_improvement"}
PRODUCT_FEEDBACK_MODULE_KEYS = {
    "cockpit",
    "workflow",
    "product",
    "bulk",
    "media",
    "confirm",
    "service",
    "connect",
    "activity",
}
PRODUCT_FEEDBACK_REASONS = {"unclear", "wrong_result", "missing_action"}
PRODUCT_FEEDBACK_STATUSES = {"open", "reviewing", "resolved"}
PRODUCT_FEEDBACK_ALLOWED_FIELDS = {
    "feedback_type",
    "module_key",
    "reason",
    "detail",
    "stage_title",
    "task_id",
    "report_id",
    "confirmation_id",
    "packet_id",
}


class ProductFeedbackValidationError(ValueError):
    """Raised when a browser payload crosses the feedback input contract."""


class ProductFeedbackIdempotencyConflict(RuntimeError):
    """Raised when one company reuses a feedback key for another payload."""


class ProductFeedbackStatusConflict(RuntimeError):
    """Raised when a feedback status transition is not the next legal step."""


def product_feedback_payload_hash(
    payload: dict[str, Any],
    *,
    user_id: str,
    store_id: str | None = None,
) -> str:
    normalized = normalize_product_feedback_payload(payload)
    semantic_request = {
        "payload": normalized,
        "server_scope": {
            "user_id": str(user_id or "").strip(),
            "store_id": str(store_id or "").strip(),
        },
    }
    canonical = json.dumps(
        semantic_request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_product_feedback_payload(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ProductFeedbackValidationError("product feedback payload must be an object")
    unknown = sorted(str(key) for key in payload if key not in PRODUCT_FEEDBACK_ALLOWED_FIELDS)
    if unknown:
        raise ProductFeedbackValidationError("product feedback contains unsupported fields")

    feedback_type = _required_text(payload, "feedback_type")
    module_key = _required_text(payload, "module_key")
    reason = _required_text(payload, "reason")
    if feedback_type not in PRODUCT_FEEDBACK_TYPES:
        raise ProductFeedbackValidationError("unsupported product feedback type")
    if module_key not in PRODUCT_FEEDBACK_MODULE_KEYS:
        raise ProductFeedbackValidationError("unsupported product feedback module")
    if reason not in PRODUCT_FEEDBACK_REASONS:
        raise ProductFeedbackValidationError("unsupported product feedback reason")

    normalized = {
        "feedback_type": feedback_type,
        "module_key": module_key,
        "reason": reason,
    }
    limits = {
        "detail": 420,
        "stage_title": 160,
        "task_id": 160,
        "report_id": 160,
        "confirmation_id": 160,
        "packet_id": 160,
    }
    for key, limit in limits.items():
        value = payload.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ProductFeedbackValidationError(f"{key} must be text")
        stripped = value.strip()
        if len(stripped) > limit:
            raise ProductFeedbackValidationError(f"{key} is too long")
        normalized[key] = _sanitize_feedback_text(stripped)
    return normalized


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductFeedbackValidationError(f"{key} is required")
    return value.strip()


def _sanitize_feedback_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"<[^>]{0,1000}>", " ", text)
    text = re.sub(r"<[^>]*$", " ", text)
    text = text.replace("<", " ").replace(">", " ")
    replacements = (
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[model_key_redacted]"),
        (r"\b(?:AIAK|AKID|ASIA)[A-Za-z0-9]{12,}\b", "[cloud_key_redacted]"),
        (r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [redacted]"),
        (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[jwt_redacted]"),
        (
            r"\b(access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret)\s*[:=]\s*[^,\s;]+",
            r"\1=[redacted]",
        ),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()
