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
PLAN_MEDIA_POINTS_INCLUDED = {"free": 0, "starter": 1000, "operator": 3000, "team": 0}


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


def grant_plan_media_points(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str | None,
    plan_key: str,
    order_id: str,
    expires_at: str,
) -> dict[str, Any]:
    """Idempotently grant one verified paid plan's expiring media points."""

    normalized_plan = str(plan_key or "").strip().lower()
    points = int(PLAN_MEDIA_POINTS_INCLUDED.get(normalized_plan, 0))
    if points <= 0:
        return {
            "status": "not_included",
            "plan_key": normalized_plan,
            "points_granted": 0,
            "duplicate_request": False,
            "secret_exposed": False,
        }
    normalized_order = str(order_id or "").strip()
    normalized_expiry = str(expires_at or "").strip()
    if not normalized_order or not normalized_expiry:
        raise ValueError("paid plan media-point grant evidence is incomplete")
    result = repository.apply_media_credit_operation(
        company_id=company_id,
        user_id=user_id,
        operation_type="grant",
        points=points,
        idempotency_key=f"paid-plan:{normalized_order}:included-media-points:v1",
        reference_type="billing_order",
        reference_id=normalized_order,
        details={
            "credit_source": "plan_included",
            "source_reference_id": normalized_order,
            "plan_key": normalized_plan,
            "expires_at": normalized_expiry,
        },
    )
    return {
        **result,
        "status": "granted",
        "plan_key": normalized_plan,
        "points_granted": points,
        "secret_exposed": False,
    }


def revoke_plan_media_points(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str | None,
    order_id: str,
) -> dict[str, Any]:
    normalized_order = str(order_id or "").strip()
    if not normalized_order:
        raise ValueError("paid plan media-point revocation evidence is incomplete")
    return repository.revoke_media_credit_source(
        company_id=company_id,
        user_id=user_id,
        source_type="plan_included",
        source_reference_id=normalized_order,
        idempotency_key=f"paid-plan:{normalized_order}:included-media-points-refund:v1",
        reason="verified_subscription_refund",
    )


def estimate_media_points(inputs: dict[str, Any]) -> dict[str, Any]:
    """Quote a provider-neutral upper bound before a media job is queued."""

    image_count = min(max(int(inputs.get("image_count") or 0), 0), 12)
    raw_tier = str(
        inputs.get("generation_tier")
        or inputs.get("image_quality")
        or inputs.get("quality")
        or "standard"
    ).strip().lower()
    generation_tier = {
        "draft": "draft",
        "low": "draft",
        "standard": "standard",
        "medium": "standard",
        "high_quality": "high_quality",
        "high": "high_quality",
    }.get(raw_tier, "standard")
    image_unit = {"draft": 20, "standard": 80, "high_quality": 250}[generation_tier]
    provider_quality = {"draft": "low", "standard": "medium", "high_quality": "high"}[generation_tier]
    video_requested = bool(inputs.get("video_requested") or inputs.get("generate_video"))
    creative = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    video_requested = video_requested or bool(creative.get("video_requested"))
    video_seconds = min(max(int(inputs.get("video_duration_seconds") or creative.get("video_duration_seconds") or 5), 3), 30)
    video_points = (video_seconds * 60) if video_requested else 0
    estimated = max(20, image_count * image_unit + video_points)
    chargeable = not video_requested
    return {
        "contract_version": "2026-08-23-media-points-quote-v2",
        "estimated_points": estimated,
        "image_count": image_count,
        "generation_tier": generation_tier,
        "quality": provider_quality,
        "points_per_image": image_unit,
        "video_requested": video_requested,
        "video_duration_seconds": video_seconds if video_requested else 0,
        "chargeable": chargeable,
        "blocked_by": [] if chargeable else ["video_media_points_pricing_not_approved"],
        "reserve_before_queue": True,
        "provider_neutral": True,
        "secret_exposed": False,
    }


def actual_media_points_from_output(
    quote: dict[str, Any],
    provider_output: dict[str, Any],
) -> tuple[int, str]:
    """Settle reported usage or successful image outputs, capped by the approved quote."""

    reserved_points = max(0, int(quote.get("estimated_points") or 0))
    output_packet = provider_output.get("output_packet") if isinstance(provider_output.get("output_packet"), dict) else {}
    for usage in (
        provider_output.get("usage") if isinstance(provider_output.get("usage"), dict) else {},
        output_packet.get("usage") if isinstance(output_packet.get("usage"), dict) else {},
    ):
        for key in ("media_points", "actual_points", "billed_media_points"):
            try:
                reported = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                reported = 0
            if reported > 0:
                return min(reserved_points, reported), "provider_usage"
    manifest = output_packet.get("asset_manifest") if isinstance(output_packet.get("asset_manifest"), list) else []
    successful_images = sum(
        1
        for item in manifest
        if isinstance(item, dict)
        and (
            "image" in str(item.get("asset_type") or item.get("media_type") or item.get("type") or "").lower()
            or str(item.get("mime_type") or "").lower().startswith("image/")
        )
    )
    points_per_image = max(0, int(quote.get("points_per_image") or 0))
    if successful_images > 0 and points_per_image > 0 and quote.get("video_requested") is not True:
        return min(reserved_points, successful_images * points_per_image), "successful_asset_count"
    return reserved_points, "reserved_quote"


def build_media_credit_summary(repository: SaaSRepository, *, company_id: str, limit: int = 30) -> dict[str, Any]:
    account = repository.get_media_credit_account(company_id=company_id)
    ledger = repository.list_media_credit_ledger(company_id=company_id, limit=limit)
    purchase_requested = media_credit_purchase_enabled()
    from .billing_wechat_pay import build_wechat_pay_native_contract

    payment_contract = build_wechat_pay_native_contract()
    payment_ready = payment_contract.get("charge_now_allowed") is True
    purchase_enabled = purchase_requested and payment_ready
    return {
        "contract_version": "2026-08-23-media-points-entitlement-v2",
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
