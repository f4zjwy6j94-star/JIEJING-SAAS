"""Provider-neutral media point contracts for merchant-visible billing."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .media_asset_pipeline import (
    media_asset_is_image,
    media_asset_is_settlement_eligible,
    media_manifest_matches_approved_quote,
)
from .repository import CONTROLLED_MEDIA_CREDIT_SOURCE, OWNER_MEDIA_TESTING_SOURCE, SaaSRepository


MEDIA_CREDIT_PACKS = [
    {"key": "media_points_1000", "label": "1,000 素材点", "points": 1000, "amount_minor": 1000, "currency": "CNY"},
    {"key": "media_points_5000", "label": "5,000 素材点", "points": 5000, "amount_minor": 5000, "currency": "CNY"},
    {"key": "media_points_10000", "label": "10,000 素材点", "points": 10000, "amount_minor": 10000, "currency": "CNY"},
]
_MEDIA_CREDIT_PACKS_BY_KEY = {str(item["key"]): dict(item) for item in MEDIA_CREDIT_PACKS}
PLAN_MEDIA_POINTS_INCLUDED = {"free": 0, "starter": 1000, "operator": 3000, "team": 0}
CONTROLLED_MEDIA_ACCEPTANCE_POINTS = 320
CONTROLLED_MEDIA_ACCEPTANCE_TTL_HOURS = 24
CONTROLLED_MEDIA_ACCEPTANCE_APPROVAL = "I_APPROVE_CONTROLLED_MEDIA_ACCEPTANCE_POINTS"
CONTROLLED_MEDIA_ACCEPTANCE_SOURCE_REFERENCE_PREFIX = "controlled-media-acceptance-v1"
OWNER_MEDIA_TESTING_POINTS = 1000
OWNER_MEDIA_TESTING_TTL_DAYS = 30
OWNER_MEDIA_TESTING_SOURCE_REFERENCE_PREFIX = "owner-media-testing-v1"
_MEDIA_GENERATION_TIER_ALIASES = {
    "draft": "draft",
    "low": "draft",
    "standard": "standard",
    "medium": "standard",
    "high_quality": "high_quality",
    "high": "high_quality",
}
def _media_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def media_live_provider_requested(inputs: dict[str, Any], job_body: dict[str, Any] | None = None) -> bool:
    body = job_body if isinstance(job_body, dict) else {}
    return bool(
        _media_truthy(inputs.get("live_provider_requested"))
        or _media_truthy(body.get("live_provider_requested"))
        or str(body.get("run_mode") or "").strip() == "live_provider_now"
    )


def media_video_requested(inputs: dict[str, Any]) -> bool:
    creative = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    return any(
        _media_truthy(value)
        for value in (
            inputs.get("video_requested"),
            inputs.get("generate_video"),
            inputs.get("video_generation_requested"),
            creative.get("video_requested"),
            creative.get("generate_video"),
            creative.get("video_generation_requested"),
        )
    )


def normalize_media_generation_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Return one canonical quote/execution contract and reject conflicting tier aliases."""

    normalized = dict(inputs or {})
    creative = dict(normalized.get("creative_job_spec")) if isinstance(normalized.get("creative_job_spec"), dict) else {}
    raw_tiers = [
        normalized.get("generation_tier"),
        creative.get("generation_tier"),
        normalized.get("image_quality"),
        normalized.get("quality"),
    ]
    tier_candidates = [
        _MEDIA_GENERATION_TIER_ALIASES.get(str(value).strip().lower(), "standard")
        for value in raw_tiers
        if str(value or "").strip()
    ]
    if len(set(tier_candidates)) > 1:
        raise ValueError("conflicting media generation tier fields")
    generation_tier = tier_candidates[0] if tier_candidates else "standard"
    try:
        requested_count = int(normalized.get("image_count"))
    except (TypeError, ValueError):
        requested_count = 1
    image_count = min(max(requested_count, 1), 4)
    video_requested = media_video_requested(normalized)
    normalized["image_count"] = image_count
    normalized["generation_tier"] = generation_tier
    normalized["video_requested"] = video_requested
    normalized["video_generation_requested"] = video_requested
    creative["generation_tier"] = generation_tier
    normalized["creative_job_spec"] = creative
    return normalized


def controlled_media_acceptance_enabled() -> bool:
    return _env_bool("JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_ENABLED")


def controlled_media_acceptance_company_allowed(company_id: str) -> bool:
    normalized_company = str(company_id or "").strip()
    if not normalized_company:
        return False
    raw = os.environ.get("JIEJING_CONTROLLED_MEDIA_ACCEPTANCE_COMPANY_ALLOWLIST", "")
    allowed = {
        item.strip()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    }
    return normalized_company in allowed


def controlled_media_acceptance_source_reference(company_id: str) -> str:
    normalized_company = str(company_id or "").strip()
    if not normalized_company:
        raise ValueError("controlled acceptance company is required")
    return f"{CONTROLLED_MEDIA_ACCEPTANCE_SOURCE_REFERENCE_PREFIX}:{normalized_company}"


def owner_media_testing_enabled() -> bool:
    return _env_bool("JIEJING_OWNER_MEDIA_TESTING_ENABLED")


def owner_media_testing_company_allowed(company_id: str) -> bool:
    normalized_company = str(company_id or "").strip()
    if not normalized_company:
        return False
    raw = os.environ.get("JIEJING_OWNER_MEDIA_TESTING_COMPANY_ALLOWLIST", "")
    return normalized_company in {
        item.strip()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    }


def owner_media_testing_source_reference(company_id: str, *, now: datetime | None = None) -> str:
    normalized_company = str(company_id or "").strip()
    if not normalized_company:
        raise ValueError("owner media testing company is required")
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{OWNER_MEDIA_TESTING_SOURCE_REFERENCE_PREFIX}:{normalized_company}:{observed_at:%Y-%m}"


def grant_owner_media_testing_points(
    repository: SaaSRepository,
    *,
    account_email: str,
    expected_company_id: str,
) -> dict[str, Any]:
    """Grant one monthly, private owner-testing allowance without calling a provider."""

    if not owner_media_testing_enabled():
        return _owner_testing_blocked("owner_media_testing_disabled")
    normalized_email = str(account_email or "").strip().lower()
    normalized_expected_company = str(expected_company_id or "").strip()
    user = repository.get_user_by_email(normalized_email) if normalized_email else None
    if not user:
        return _owner_testing_blocked("owner_media_testing_account_not_found")
    company_id = str(user.get("default_company_id") or "").strip()
    if not normalized_expected_company or company_id != normalized_expected_company:
        return _owner_testing_blocked("owner_media_testing_account_company_mismatch")
    if not owner_media_testing_company_allowed(company_id):
        return _owner_testing_blocked("owner_media_testing_company_not_allowlisted")
    if str(user.get("status") or "").strip().lower() != "active":
        return _owner_testing_blocked("owner_media_testing_account_not_active")

    now = datetime.now(timezone.utc)
    source_reference_id = owner_media_testing_source_reference(company_id, now=now)
    expires_at = (now + timedelta(days=OWNER_MEDIA_TESTING_TTL_DAYS)).isoformat()
    result = repository.apply_media_credit_operation(
        company_id=company_id,
        user_id=str(user.get("user_id") or "") or None,
        operation_type="grant",
        points=OWNER_MEDIA_TESTING_POINTS,
        idempotency_key=f"{source_reference_id}:grant",
        reference_type=OWNER_MEDIA_TESTING_SOURCE,
        reference_id=source_reference_id,
        details={
            "credit_source": OWNER_MEDIA_TESTING_SOURCE,
            "source_reference_id": source_reference_id,
            "expires_at": expires_at,
            "ttl_days": OWNER_MEDIA_TESTING_TTL_DAYS,
            "external_provider_action_triggered": False,
            "real_platform_write_performed": False,
            "secret_exposed": False,
        },
    )
    bucket = repository.get_media_credit_source(
        company_id=company_id,
        source_type=OWNER_MEDIA_TESTING_SOURCE,
        source_reference_id=source_reference_id,
    )
    if not bucket:
        raise RuntimeError("owner media testing bucket was not persisted")
    existing_audit = repository.find_latest_audit_log_by_target(
        company_id=company_id,
        store_id=None,
        action_type="media_credit.owner_testing.granted",
        target_type="media_credit_bucket",
        target_id=source_reference_id,
    )
    if not existing_audit:
        repository.write_audit(
            company_id=company_id,
            user_id=str(user.get("user_id") or "") or None,
            actor_type="platform_internal_admin",
            action_type="media_credit.owner_testing.granted",
            target_type="media_credit_bucket",
            target_id=source_reference_id,
            summary="Private owner media-testing allowance granted to one allowlisted company.",
            details={
                "contract_version": "2026-08-25-owner-media-testing-v1",
                "credit_source": OWNER_MEDIA_TESTING_SOURCE,
                "points": OWNER_MEDIA_TESTING_POINTS,
                "ttl_days": OWNER_MEDIA_TESTING_TTL_DAYS,
                "expires_at": str(bucket.get("expires_at") or ""),
                "external_provider_action_triggered": False,
                "real_platform_write_performed": False,
                "public_charging_allowed": False,
                "secret_exposed": False,
            },
        )
    return {
        "ok": True,
        "status": "granted",
        "reason": "",
        "company_id": company_id,
        "credit_source": OWNER_MEDIA_TESTING_SOURCE,
        "source_reference_id": source_reference_id,
        "points_granted": OWNER_MEDIA_TESTING_POINTS,
        "ttl_days": OWNER_MEDIA_TESTING_TTL_DAYS,
        "expires_at": str(bucket.get("expires_at") or ""),
        "duplicate_request": bool(result.get("duplicate_request")),
        "external_provider_action_triggered": False,
        "real_platform_write_performed": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


def _owner_testing_blocked(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "reason": str(reason or "owner_media_testing_blocked"),
        "points_granted": 0,
        "external_provider_action_triggered": False,
        "real_platform_write_performed": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


def grant_controlled_media_acceptance_points(
    repository: SaaSRepository,
    *,
    account_email: str,
    expected_company_id: str,
    owner_confirmation_phrase: str,
) -> dict[str, Any]:
    """Grant the single owner-controlled, expiring media acceptance bucket."""

    if str(owner_confirmation_phrase or "") != CONTROLLED_MEDIA_ACCEPTANCE_APPROVAL:
        return _controlled_acceptance_blocked(
            "controlled_acceptance_owner_approval_required",
            required_approval=CONTROLLED_MEDIA_ACCEPTANCE_APPROVAL,
        )
    if not controlled_media_acceptance_enabled():
        return _controlled_acceptance_blocked("controlled_acceptance_disabled")
    normalized_email = str(account_email or "").strip().lower()
    normalized_expected_company = str(expected_company_id or "").strip()
    user = repository.get_user_by_email(normalized_email) if normalized_email else None
    if not user:
        return _controlled_acceptance_blocked("controlled_acceptance_account_not_found")
    company_id = str(user.get("default_company_id") or "").strip()
    if not normalized_expected_company or company_id != normalized_expected_company:
        return _controlled_acceptance_blocked("controlled_acceptance_account_company_mismatch")
    if not controlled_media_acceptance_company_allowed(company_id):
        return _controlled_acceptance_blocked("controlled_acceptance_company_not_allowlisted")
    if str(user.get("status") or "").strip().lower() != "active":
        return _controlled_acceptance_blocked("controlled_acceptance_account_not_active")

    source_reference_id = controlled_media_acceptance_source_reference(company_id)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=CONTROLLED_MEDIA_ACCEPTANCE_TTL_HOURS)).isoformat()
    result = repository.apply_media_credit_operation(
        company_id=company_id,
        user_id=str(user.get("user_id") or "") or None,
        operation_type="grant",
        points=CONTROLLED_MEDIA_ACCEPTANCE_POINTS,
        idempotency_key=f"{source_reference_id}:grant",
        reference_type=CONTROLLED_MEDIA_CREDIT_SOURCE,
        reference_id=source_reference_id,
        details={
            "credit_source": CONTROLLED_MEDIA_CREDIT_SOURCE,
            "source_reference_id": source_reference_id,
            "expires_at": expires_at,
            "ttl_hours": CONTROLLED_MEDIA_ACCEPTANCE_TTL_HOURS,
            "external_provider_action_triggered": False,
            "real_platform_write_performed": False,
            "secret_exposed": False,
        },
    )
    bucket = repository.get_media_credit_source(
        company_id=company_id,
        source_type=CONTROLLED_MEDIA_CREDIT_SOURCE,
        source_reference_id=source_reference_id,
    )
    if not bucket:
        raise RuntimeError("controlled acceptance media-credit bucket was not persisted")
    existing_audit = repository.find_latest_audit_log_by_target(
        company_id=company_id,
        store_id=None,
        action_type="media_credit.controlled_acceptance.granted",
        target_type="media_credit_bucket",
        target_id=source_reference_id,
    )
    if not existing_audit:
        repository.write_audit(
            company_id=company_id,
            user_id=str(user.get("user_id") or "") or None,
            actor_type="platform_internal_admin",
            action_type="media_credit.controlled_acceptance.granted",
            target_type="media_credit_bucket",
            target_id=source_reference_id,
            summary="Controlled media acceptance points granted to one allowlisted merchant company.",
            details={
                "contract_version": "2026-08-23-controlled-media-acceptance-points-v1",
                "credit_source": CONTROLLED_MEDIA_CREDIT_SOURCE,
                "points": CONTROLLED_MEDIA_ACCEPTANCE_POINTS,
                "ttl_hours": CONTROLLED_MEDIA_ACCEPTANCE_TTL_HOURS,
                "expires_at": str(bucket.get("expires_at") or ""),
                "external_provider_action_triggered": False,
                "real_platform_write_performed": False,
                "public_charging_allowed": False,
                "secret_exposed": False,
            },
        )
    return {
        "ok": True,
        "status": "granted",
        "reason": "",
        "company_id": company_id,
        "account_email": normalized_email,
        "credit_source": CONTROLLED_MEDIA_CREDIT_SOURCE,
        "source_reference_id": source_reference_id,
        "points_granted": CONTROLLED_MEDIA_ACCEPTANCE_POINTS,
        "ttl_hours": CONTROLLED_MEDIA_ACCEPTANCE_TTL_HOURS,
        "expires_at": str(bucket.get("expires_at") or ""),
        "duplicate_request": bool(result.get("duplicate_request")),
        "external_provider_action_triggered": False,
        "real_platform_write_performed": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


def _controlled_acceptance_blocked(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "reason": str(reason or "controlled_acceptance_blocked"),
        **extra,
        "points_granted": 0,
        "external_provider_action_triggered": False,
        "real_platform_write_performed": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


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

    normalized = normalize_media_generation_inputs(inputs)
    image_count = int(normalized["image_count"])
    generation_tier = str(normalized["generation_tier"])
    image_unit = {"draft": 20, "standard": 80, "high_quality": 250}[generation_tier]
    provider_quality = {"draft": "low", "standard": "medium", "high_quality": "high"}[generation_tier]
    video_requested = bool(normalized["video_requested"])
    creative = normalized.get("creative_job_spec") if isinstance(normalized.get("creative_job_spec"), dict) else {}
    video_seconds = min(max(int(normalized.get("video_duration_seconds") or creative.get("video_duration_seconds") or 5), 3), 30)
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
    manifest = output_packet.get("asset_manifest") if isinstance(output_packet.get("asset_manifest"), list) else []
    if not media_manifest_matches_approved_quote(quote, manifest):
        return 0, "unpriced_video_output"
    successful_images = sum(
        1
        for item in manifest
        if isinstance(item, dict)
        and media_asset_is_settlement_eligible(item, require_https=True)
        and media_asset_is_image(item)
    )
    points_per_image = max(0, int(quote.get("points_per_image") or 0))
    if successful_images > 0 and points_per_image > 0 and quote.get("video_requested") is not True:
        return min(reserved_points, successful_images * points_per_image), "successful_asset_count"
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


def build_merchant_media_credit_summary(
    repository: SaaSRepository,
    *,
    company_id: str,
    limit: int = 30,
    include_usage: bool = False,
) -> dict[str, Any]:
    """Return a merchant-safe media-points summary from positive allowlists.

    Controlled acceptance and owner-testing buckets are operational evidence,
    not merchant entitlement.  The merchant contract therefore derives its
    total only from plan, purchase and explicitly merchant-facing promotional
    buckets. Usage is a separate sanitized projection, never raw ledger rows.
    """

    account = repository.get_media_credit_account(company_id=company_id)

    def safe_points(key: str) -> int:
        value = account.get(key)
        return value if type(value) is int and value >= 0 else 0

    included_points = safe_points("included_points")
    purchased_points = safe_points("purchased_points")
    promotional_points = safe_points("promotional_points")
    available_points = included_points + purchased_points + promotional_points

    purchase_requested = media_credit_purchase_enabled()
    from .billing_wechat_pay import build_wechat_pay_native_contract

    payment_contract = build_wechat_pay_native_contract()
    payment_ready = payment_contract.get("charge_now_allowed") is True
    purchase_enabled = purchase_requested and payment_ready
    return {
        "contract_version": "2026-08-27-merchant-media-points-v1",
        "display_name": "素材点",
        "total_points": available_points,
        "available_points": available_points,
        "included_points": included_points,
        "purchased_points": purchased_points,
        "promotional_points": promotional_points,
        **({"usage": repository.get_merchant_media_credit_usage(company_id=company_id, limit=limit)} if include_usage else {}),
        "packs": [dict(item) for item in MEDIA_CREDIT_PACKS],
        "purchase": {
            "status": "available" if purchase_enabled else "not_open",
            "purchase_enabled": purchase_enabled,
            "unavailable_reason": "" if purchase_enabled else ("not_open" if not purchase_requested else "payment_unavailable"),
            "backend_payment_confirmation_required": True,
            "frontend_can_grant_points": False,
            "triggers_real_charge": False,
            "charge_now_allowed": purchase_enabled,
        },
        "provider_neutral": True,
        "merchant_visible": True,
        "secret_exposed": False,
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}
