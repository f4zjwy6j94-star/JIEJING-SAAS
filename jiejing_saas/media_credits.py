"""Provider-neutral media point contracts for merchant-visible billing."""

from __future__ import annotations

import os
from typing import Any

from .repository import SaaSRepository


MEDIA_CREDIT_PACKS = [
    {"key": "media_points_1000", "label": "1,000 素材点", "points": 1000, "amount_minor": 1000, "currency": "CNY"},
    {"key": "media_points_5000", "label": "5,000 素材点", "points": 5000, "amount_minor": 5000, "currency": "CNY"},
    {"key": "media_points_10000", "label": "10,000 素材点", "points": 10000, "amount_minor": 10000, "currency": "CNY"},
]
_MEDIA_CREDIT_PACKS_BY_KEY = {str(item["key"]): dict(item) for item in MEDIA_CREDIT_PACKS}


def media_credit_purchase_enabled() -> bool:
    return _env_bool("JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED")


def media_credit_pack_terms(pack_key: str) -> dict[str, Any] | None:
    pack = _MEDIA_CREDIT_PACKS_BY_KEY.get(str(pack_key or "").strip().lower())
    if not pack:
        return None
    return {
        **pack,
        "purchase_type": "media_points",
        "duration_days": 0,
        "display_name": f"捷境{pack['label']}",
    }


def estimate_media_points(inputs: dict[str, Any]) -> dict[str, Any]:
    """Quote a provider-neutral upper bound before a media job is queued."""

    image_count = min(max(int(inputs.get("image_count") or 0), 0), 12)
    quality = str(inputs.get("image_quality") or inputs.get("quality") or "standard").strip().lower()
    image_unit = {"draft": 15, "low": 20, "standard": 40, "high": 80}.get(quality, 40)
    video_requested = bool(inputs.get("video_requested") or inputs.get("generate_video"))
    creative = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    video_requested = video_requested or bool(creative.get("video_requested"))
    video_seconds = min(max(int(inputs.get("video_duration_seconds") or creative.get("video_duration_seconds") or 5), 3), 30)
    video_points = (video_seconds * 60) if video_requested else 0
    estimated = max(20, image_count * image_unit + video_points)
    return {
        "contract_version": "2026-07-14-media-points-quote-v1",
        "estimated_points": estimated,
        "image_count": image_count,
        "quality": quality if quality in {"draft", "low", "standard", "high"} else "standard",
        "video_requested": video_requested,
        "video_duration_seconds": video_seconds if video_requested else 0,
        "reserve_before_queue": True,
        "provider_neutral": True,
        "secret_exposed": False,
    }


def build_media_credit_summary(repository: SaaSRepository, *, company_id: str, limit: int = 30) -> dict[str, Any]:
    account = repository.get_media_credit_account(company_id=company_id)
    ledger = repository.list_media_credit_ledger(company_id=company_id, limit=limit)
    purchase_requested = media_credit_purchase_enabled()
    from .billing_wechat_pay import build_wechat_pay_native_contract

    payment_contract = build_wechat_pay_native_contract()
    payment_ready = payment_contract.get("charge_now_allowed") is True
    purchase_enabled = purchase_requested and payment_ready
    return {
        "contract_version": "2026-07-14-media-points-v1",
        "display_name": "素材点",
        "account": account,
        "packs": [dict(item) for item in MEDIA_CREDIT_PACKS],
        "recent_activity": ledger,
        "purchase": {
            "status": "available" if purchase_enabled else "not_open",
            "purchase_enabled": purchase_enabled,
            "media_purchase_approved": purchase_requested,
            "payment_checkout_ready": payment_ready,
            "blocked_by": []
            if purchase_enabled
            else (["media_point_purchase_not_approved"] if not purchase_requested else ["payment_checkout_not_ready"]),
            "backend_payment_confirmation_required": True,
            "frontend_can_grant_points": False,
            "triggers_real_charge": False,
            "charge_now_allowed": purchase_enabled,
        },
        "settlement": {
            "reserve_before_generation": True,
            "settle_actual_points_after_success": True,
            "release_on_provider_failure": True,
            "release_on_fact_or_rights_gate_failure": True,
            "double_charge_allowed": False,
        },
        "provider_neutral": True,
        "merchant_visible": True,
        "secret_exposed": False,
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}
