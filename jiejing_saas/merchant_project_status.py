"""Merchant-safe, backend-authoritative status for one Listing project.

The status is derived from immutable workflow evidence.  It is not an editable
progress record and never falls back to the globally newest product artifact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SNAPSHOT_VERSION = "merchant_project_status_v1"
STAGE_DEFINITIONS = (
    ("intake", "资料"),
    ("research", "调研"),
    ("facts", "事实"),
    ("media", "素材"),
    ("listing", "Listing"),
    ("ebay_draft", "未发布草稿"),
    ("publish", "正式发布"),
    ("records", "记录"),
)
SUCCESSFUL_DRAFT_STATUSES = {"saved_to_ebay_draft", "draft_saved", "completed"}
SUCCESSFUL_PUBLISH_STATUSES = {"published_to_ebay", "published", "completed"}
APPROVED_MEDIA_STATUSES = {"approved_for_listing", "approved_for_listing_draft"}
FAILED_MEDIA_STATUSES = {"failed", "blocked", "validation_failed", "needs_rework"}
RESTRICTED_ACCOUNT_STATUSES = {"restricted", "suspended", "blocked", "account_review_required"}


def build_merchant_project_status(
    *,
    repository: Any,
    company_id: str,
    store_id: str,
    project_id: str,
    account_health: dict[str, Any] | None = None,
    evidence_cutoff: str | None = None,
) -> dict[str, Any]:
    """Derive one merchant-facing progress snapshot from tenant-scoped evidence."""

    cutoff = str(evidence_cutoff or _now_iso()).strip()
    clean_project_id = _safe_identifier(project_id, limit=160)
    health = account_health if isinstance(account_health, dict) else {}
    if not clean_project_id:
        return _snapshot(
            cutoff=cutoff,
            project_id="",
            canonical_identity={},
            product_name="",
            sku="",
            offer_id="",
            listing_id="",
            stage_statuses={"intake": "blocked"},
            current_stage="intake",
            blocker=_blocker("project_id_missing", "还没有选择商品项目", "先从 AI CEO 或 Listing 选择一个商品项目。"),
            next_action=_next_action("select_listing_project", "选择商品项目", "cockpit"),
            overall_status="blocked",
        )

    tasks = _before_cutoff(
        repository.list_tasks(company_id=company_id, store_id=store_id, limit=500),
        cutoff,
    )
    store_task_ids = {str(item.get("task_id") or "") for item in tasks if item.get("task_id")}
    reports = [
        item
        for item in _before_cutoff(repository.list_reports(company_id=company_id, limit=500), cutoff)
        if str(item.get("task_id") or "") in store_task_ids
    ]
    confirmations = [
        item
        for item in _before_cutoff(repository.list_confirmations(company_id=company_id, limit=500), cutoff)
        if str(item.get("store_id") or "") == store_id
    ]
    media_jobs = _before_cutoff(
        repository.list_media_asset_jobs(company_id=company_id, store_id=store_id, limit=200),
        cutoff,
    )
    confirmation_ids = {str(item.get("confirmation_id") or "") for item in confirmations}
    executions = [
        item
        for item in _before_cutoff(repository.list_execution_results(company_id=company_id, limit=500), cutoff)
        if str(item.get("confirmation_id") or "") in confirmation_ids
    ]

    identity_records = [*tasks, *reports, *media_jobs, *confirmations]
    project_identities = [
        identity
        for identity in (_artifact_identity(item) for item in identity_records)
        if identity.get("key") == clean_project_id
    ]
    canonical_identity, identity_conflict = _merge_identities(clean_project_id, project_identities)

    matching_tasks = [item for item in tasks if _identity_matches(_artifact_identity(item), canonical_identity)]
    matching_task_ids = {str(item.get("task_id") or "") for item in matching_tasks}
    matching_reports = [
        item
        for item in reports
        if _identity_matches(_artifact_identity(item), canonical_identity)
        or (
            str(item.get("task_id") or "") in matching_task_ids
            and str(item.get("report_id") or "") == canonical_identity.get("source_report_id")
        )
    ]
    matching_media = [item for item in media_jobs if _identity_matches(_artifact_identity(item), canonical_identity)]
    matching_confirmations = [
        item for item in confirmations if _identity_matches(_artifact_identity(item), canonical_identity)
    ]
    matching_confirmation_ids = {str(item.get("confirmation_id") or "") for item in matching_confirmations}
    matching_executions = [
        item for item in executions if str(item.get("confirmation_id") or "") in matching_confirmation_ids
    ]

    product_name = _project_product_name(matching_reports, matching_tasks)
    skus = _unique_values(
        _project_value_candidates(
            reports=matching_reports,
            confirmations=matching_confirmations,
            executions=matching_executions,
            field="sku",
        )
    )
    offer_ids = _unique_values(
        _project_value_candidates(
            reports=matching_reports,
            confirmations=matching_confirmations,
            executions=matching_executions,
            field="offer_id",
        )
    )
    listing_ids = _unique_values(
        _project_value_candidates(
            reports=matching_reports,
            confirmations=matching_confirmations,
            executions=matching_executions,
            field="listing_id",
        )
    )
    platform_binding_conflict = len(skus) > 1 or len(offer_ids) > 1 or len(listing_ids) > 1
    sku = skus[0] if len(skus) == 1 else ""
    offer_id = offer_ids[0] if len(offer_ids) == 1 else ""
    listing_id = listing_ids[0] if len(listing_ids) == 1 else ""

    fact_reports = [item for item in matching_reports if str(item.get("report_type") or "") == "merchant.product_facts"]
    latest_fact_report = _latest(fact_reports)
    fact_packet = _fact_packet(latest_fact_report)
    unknown_facts = _string_list(fact_packet.get("unknown_facts"))
    fact_blockers = _string_list(fact_packet.get("blocked_by"))
    research_ready = any(
        str(item.get("report_type") or "") in {"ai_ceo.market_research", "market.report", "market.data_packet"}
        for item in matching_reports
    ) or any(str(item.get("report_id") or "") == canonical_identity.get("source_report_id") for item in reports)
    facts_ready = bool(latest_fact_report and not unknown_facts and not fact_blockers)
    media_ready = any(_media_job_approved(item) for item in matching_media)
    # A successful reviewed rework is the terminal evidence for this stage.
    # Historical failed versions remain visible in the audit trail, but must
    # not permanently re-block a project after a later asset is approved.
    media_failed = not media_ready and any(
        str(item.get("status") or "").lower() in FAILED_MEDIA_STATUSES for item in matching_media
    )
    listing_ready = any(
        str(item.get("report_type") or "") in {"listing.package", "product.listing"}
        for item in matching_reports
    ) or any(_confirmation_has_listing(item) for item in matching_confirmations)
    draft_execution = next((item for item in matching_executions if _is_successful_draft_execution(item)), None)
    publish_execution = next((item for item in matching_executions if _is_successful_publish_execution(item)), None)
    draft_ready = draft_execution is not None
    publish_ready = publish_execution is not None

    if draft_ready:
        platform = _platform_result(draft_execution)
        offer_id = _safe_identifier(platform.get("offer_id"), limit=80) or offer_id
        sku = _safe_identifier(platform.get("sku"), limit=100) or sku
    if publish_ready:
        platform = _platform_result(publish_execution)
        listing_id = _safe_identifier(platform.get("listing_id") or platform.get("item_id"), limit=120) or listing_id
        offer_id = _safe_identifier(platform.get("offer_id"), limit=80) or offer_id
        sku = _safe_identifier(platform.get("sku"), limit=100) or sku

    stage_statuses: dict[str, str] = {
        "intake": "completed" if matching_tasks else "blocked",
        "research": "completed" if research_ready else "waiting",
        "facts": "completed" if facts_ready else "blocked" if latest_fact_report and (unknown_facts or fact_blockers) else "waiting",
        "media": "completed" if media_ready else "blocked" if media_failed else "waiting",
        "listing": "completed" if listing_ready else "waiting",
        "ebay_draft": "completed" if draft_ready else "waiting",
        "publish": "completed" if publish_ready else "waiting",
        "records": "completed" if publish_ready else "waiting",
    }

    blocker = _blocker("none", "当前没有新增阻断", "按下一步继续。")
    current_stage = _first_incomplete_stage(stage_statuses)
    overall_status = "published" if publish_ready else "in_progress"
    next_action = _stage_next_action(current_stage)

    if identity_conflict:
        current_stage = "intake"
        stage_statuses["intake"] = "blocked"
        blocker = _blocker(
            "listing_project_identity_conflict",
            "商品项目身份不一致",
            "同一项目出现不同来源报告或候选商品，捷境已停止自动归并。",
        )
        next_action = _next_action("review_project_identity", "核对当前商品项目", "product")
        overall_status = "blocked"
    elif platform_binding_conflict:
        current_stage = "ebay_draft"
        stage_statuses["ebay_draft"] = "blocked"
        blocker = _blocker(
            "project_platform_binding_conflict",
            "SKU 或 Offer 绑定不一致",
            "当前项目出现多个 SKU、Offer 或 Listing，捷境不会自动重绑。",
        )
        next_action = _next_action("review_platform_binding", "核对 SKU 与 Offer", "product")
        overall_status = "blocked"
    elif not matching_tasks:
        blocker = _blocker(
            "project_evidence_missing",
            "还没有找到这个商品项目的后端记录",
            "请从 AI CEO 或 Listing 重新打开该商品项目。",
        )
        next_action = _next_action("open_listing_project", "打开商品项目", "product")
        overall_status = "blocked"
    elif latest_fact_report and (unknown_facts or fact_blockers):
        current_stage = "facts"
        blocker = _blocker(
            "product_facts_missing",
            "商品事实还没有补齐",
            f"还有 {max(len(unknown_facts), len(fact_blockers))} 项商品资料待商家确认。",
        )
        next_action = _next_action("complete_product_facts", "补齐商品资料", "product")
        overall_status = "blocked"
    elif media_failed:
        current_stage = "media"
        blocker = _blocker(
            "media_review_or_generation_failed",
            "当前素材没有通过审核",
            "保留原始商品事实，修复素材后从当前步骤重试。",
        )
        next_action = _next_action("review_or_regenerate_media", "处理当前素材", "media")
        overall_status = "blocked"
    elif draft_ready and not publish_ready and _account_restricted(health):
        current_stage = "publish"
        blocker = _blocker(
            "ebay_account_restricted",
            "eBay 账号仍在审核或受限",
            "捷境流程已经停在正式发布前；账号恢复后从当前 Offer 继续。",
        )
        next_action = _next_action("wait_for_ebay_account_review", "等待 eBay 账号审核", "connect")
        overall_status = "blocked"
    elif not publish_ready:
        pending_publish = any(
            str(item.get("action_type") or "") == "publish_listing"
            and str(item.get("status") or "") in {"pending", "approved", "approved_waiting_execution"}
            for item in matching_confirmations
        )
        if pending_publish:
            next_action = _next_action("review_publish_confirmation", "处理正式发布确认", "confirm")

    stage_details = {
        "intake": "商品项目已锁定" if matching_tasks else "等待商品项目记录",
        "research": "市场调研已归档" if research_ready else "等待市场调研",
        "facts": "商品事实已补齐" if facts_ready else f"{len(unknown_facts) or len(fact_blockers)} 项待补" if latest_fact_report else "等待商品事实",
        "media": "素材已通过商家审核" if media_ready else "当前素材需要处理" if media_failed else "等待素材生成与审核",
        "listing": "Listing 草稿已形成" if listing_ready else "等待 Listing 草稿",
        "ebay_draft": f"未发布 Offer {offer_id} 已保存" if draft_ready and offer_id else "等待保存未发布草稿",
        "publish": f"eBay Listing {listing_id} 已发布" if publish_ready and listing_id else "等待正式发布",
        "records": "发布执行记录已归档" if publish_ready else "发布后自动留存记录",
    }

    return _snapshot(
        cutoff=cutoff,
        project_id=clean_project_id,
        canonical_identity=canonical_identity,
        product_name=product_name,
        sku=sku,
        offer_id=offer_id,
        listing_id=listing_id,
        stage_statuses=stage_statuses,
        stage_details=stage_details,
        current_stage=current_stage,
        blocker=blocker,
        next_action=next_action,
        overall_status=overall_status,
    )


def _snapshot(
    *,
    cutoff: str,
    project_id: str,
    canonical_identity: dict[str, str],
    product_name: str,
    sku: str,
    offer_id: str,
    listing_id: str,
    stage_statuses: dict[str, str],
    current_stage: str,
    blocker: dict[str, str],
    next_action: dict[str, str],
    overall_status: str,
    stage_details: dict[str, str] | None = None,
) -> dict[str, Any]:
    details = stage_details or {}
    stages = [
        {
            "key": key,
            "label": label,
            "status": stage_statuses.get(key, "waiting"),
            "detail": details.get(key, "等待当前项目证据"),
            "is_current": key == current_stage,
        }
        for key, label in STAGE_DEFINITIONS
    ]
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "evidence_cutoff": cutoff,
        "project": {
            "project_id": project_id,
            "listing_project_identity": {
                "key": canonical_identity.get("key", project_id),
                "source_report_id": canonical_identity.get("source_report_id", ""),
                "candidate_id": canonical_identity.get("candidate_id", ""),
            },
            "product_name": _safe_text(product_name, limit=160),
            "sku": _safe_identifier(sku, limit=100),
            "offer_id": _safe_identifier(offer_id, limit=80),
            "listing_id": _safe_identifier(listing_id, limit=120),
        },
        "overall_status": overall_status,
        "current_stage": current_stage,
        "stages": stages,
        "blocker": blocker,
        "next_action": next_action,
        "source": "tenant_scoped_backend_evidence",
        "frontend_can_write_progress": False,
        "secret_exposed": False,
    }


def _artifact_identity(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        return {}
    candidates = [
        item.get("listing_project_identity"),
        _nested(item, "input", "listing_project_identity"),
        _nested(item, "output", "listing_project_identity"),
        _nested(item, "report", "listing_project_identity"),
        _nested(item, "item", "listing_project_identity"),
        _nested(item, "job", "listing_project_identity"),
        _nested(item, "job", "job_spec", "listing_project_identity"),
        _nested(item, "job", "job_spec", "inputs", "product_facts", "listing_project_identity"),
    ]
    for candidate in candidates:
        identity = _normalize_identity(candidate)
        if identity:
            return identity
    return {}


def _normalize_identity(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    key = _safe_identifier(value.get("key"), limit=160)
    if not key:
        return {}
    return {
        "key": key,
        "source_report_id": _safe_identifier(value.get("source_report_id") or value.get("source_id"), limit=160),
        "candidate_id": _safe_identifier(value.get("candidate_id"), limit=120),
    }


def _merge_identities(project_id: str, identities: list[dict[str, str]]) -> tuple[dict[str, str], bool]:
    canonical = {"key": project_id, "source_report_id": "", "candidate_id": ""}
    conflict = False
    for identity in identities:
        for field in ("source_report_id", "candidate_id"):
            incoming = identity.get(field, "")
            if incoming and canonical[field] and incoming != canonical[field]:
                conflict = True
            elif incoming:
                canonical[field] = incoming
    return canonical, conflict


def _identity_matches(identity: dict[str, str], canonical: dict[str, str]) -> bool:
    if not identity or identity.get("key") != canonical.get("key"):
        return False
    return all(
        not canonical.get(field) or identity.get(field) == canonical.get(field)
        for field in ("source_report_id", "candidate_id")
    )


def _project_value_candidates(
    *,
    reports: list[dict[str, Any]],
    confirmations: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    field: str,
) -> list[str]:
    values: list[Any] = []
    for report in reports:
        payload = report.get("report") if isinstance(report.get("report"), dict) else {}
        packet = payload.get("merchant_product_fact_packet") if isinstance(payload.get("merchant_product_fact_packet"), dict) else {}
        for facts_key in ("merchant_confirmed_facts", "source_confirmed_facts", "derived_listing_suggestions"):
            facts = packet.get(facts_key) if isinstance(packet.get(facts_key), dict) else {}
            values.append(facts.get(field))
        sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
        values.append(sections.get(field))
    for confirmation in confirmations:
        item = confirmation.get("item") if isinstance(confirmation.get("item"), dict) else {}
        existing = item.get("existing_ebay_draft") if isinstance(item.get("existing_ebay_draft"), dict) else {}
        listing = _nested(item, "publish_payload", "listing")
        values.extend([existing.get(field), listing.get(field) if isinstance(listing, dict) else None])
    for execution in executions:
        values.append(_platform_result(execution).get(field))
    return [_safe_identifier(value, limit=120) for value in values if _safe_identifier(value, limit=120)]


def _project_product_name(reports: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> str:
    for report in sorted(reports, key=_timestamp_order, reverse=True):
        payload = report.get("report") if isinstance(report.get("report"), dict) else {}
        packet = payload.get("merchant_product_fact_packet") if isinstance(payload.get("merchant_product_fact_packet"), dict) else {}
        value = packet.get("product_name") or payload.get("product")
        if _safe_text(value, limit=160):
            return _safe_text(value, limit=160)
    for task in sorted(tasks, key=_timestamp_order, reverse=True):
        value = _nested(task, "input", "product") or task.get("title")
        if _safe_text(value, limit=160):
            return _safe_text(value, limit=160)
    return ""


def _fact_packet(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    payload = report.get("report") if isinstance(report.get("report"), dict) else {}
    packet = payload.get("merchant_product_fact_packet")
    return packet if isinstance(packet, dict) else {}


def _media_job_approved(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    review = item.get("asset_review") if isinstance(item.get("asset_review"), dict) else {}
    merchant = item.get("merchant_review") if isinstance(item.get("merchant_review"), dict) else {}
    return bool(
        status in APPROVED_MEDIA_STATUSES
        or str(review.get("status") or "").lower() in APPROVED_MEDIA_STATUSES
        or str(merchant.get("decision") or "").lower() == "approve_for_listing_draft"
    )


def _confirmation_has_listing(item: dict[str, Any]) -> bool:
    body = item.get("item") if isinstance(item.get("item"), dict) else {}
    listing = _nested(body, "publish_payload", "listing")
    return bool(isinstance(listing, dict) and (_safe_identifier(listing.get("sku"), limit=100) or _safe_text(listing.get("title"), limit=160)))


def _is_successful_draft_execution(item: dict[str, Any]) -> bool:
    if str(item.get("action_type") or "") != "save_ebay_listing_draft":
        return False
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    platform = _platform_result(item)
    status = str(item.get("status") or result.get("status") or "").lower()
    return bool(
        status in SUCCESSFUL_DRAFT_STATUSES
        and _safe_identifier(platform.get("offer_id"), limit=80)
        and str(platform.get("offer_status") or "").upper() == "UNPUBLISHED"
        and platform.get("public_listing_created") is False
        and platform.get("published_to_ebay") is False
    )


def _is_successful_publish_execution(item: dict[str, Any]) -> bool:
    if str(item.get("action_type") or "") != "publish_listing":
        return False
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    platform = _platform_result(item)
    status = str(item.get("status") or result.get("status") or "").lower()
    listing_id = _safe_identifier(platform.get("listing_id") or platform.get("item_id"), limit=120)
    return bool(
        status in SUCCESSFUL_PUBLISH_STATUSES
        and listing_id
        and platform.get("published_to_ebay") is True
        and platform.get("public_listing_created") is True
    )


def _platform_result(execution: dict[str, Any]) -> dict[str, Any]:
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    platform = result.get("platform_result")
    return platform if isinstance(platform, dict) else {}


def _account_restricted(health: dict[str, Any]) -> bool:
    status = str(health.get("status") or "").lower()
    stage = str(health.get("onboarding_stage") or "").lower()
    return status in RESTRICTED_ACCOUNT_STATUSES or stage in RESTRICTED_ACCOUNT_STATUSES


def _stage_next_action(stage: str) -> dict[str, str]:
    mapping = {
        "intake": ("open_listing_project", "打开商品项目", "product"),
        "research": ("run_market_research", "完成市场调研", "cockpit"),
        "facts": ("complete_product_facts", "补齐商品资料", "product"),
        "media": ("create_or_review_media", "生成并审核素材", "media"),
        "listing": ("generate_listing_draft", "生成 Listing 草稿", "product"),
        "ebay_draft": ("save_unpublished_ebay_draft", "保存未发布 eBay 草稿", "confirm"),
        "publish": ("prepare_publish_confirmation", "准备正式发布确认", "confirm"),
        "records": ("review_execution_record", "查看发布记录", "activity"),
    }
    action, label, view = mapping.get(stage, mapping["intake"])
    return _next_action(action, label, view)


def _first_incomplete_stage(statuses: dict[str, str]) -> str:
    for key, _label in STAGE_DEFINITIONS:
        if statuses.get(key) != "completed":
            return key
    return "records"


def _blocker(key: str, title: str, detail: str) -> dict[str, str]:
    return {"key": key, "title": title, "detail": detail}


def _next_action(action: str, label: str, view: str) -> dict[str, str]:
    return {"action": action, "label": label, "view": view}


def _before_cutoff(items: Any, cutoff: str) -> list[dict[str, Any]]:
    safe_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    cutoff_instant = _parse_instant(cutoff)
    selected: list[dict[str, Any]] = []
    for item in safe_items:
        timestamp = _timestamp(item)
        if not timestamp:
            selected.append(item)
            continue
        item_instant = _parse_instant(timestamp)
        if cutoff_instant is not None and item_instant is not None:
            if item_instant <= cutoff_instant:
                selected.append(item)
            continue
        if timestamp <= cutoff:
            selected.append(item)
    return selected


def _latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(items, key=_timestamp_order) if items else None


def _timestamp(item: dict[str, Any]) -> str:
    return str(item.get("updated_at") or item.get("created_at") or "")


def _timestamp_order(item: dict[str, Any]) -> tuple[int, float, str]:
    timestamp = _timestamp(item)
    instant = _parse_instant(timestamp)
    return (1, instant.timestamp(), timestamp) if instant is not None else (0, 0.0, timestamp)


def _parse_instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _string_list(value: Any) -> list[str]:
    return [_safe_text(item, limit=160) for item in value if _safe_text(item, limit=160)] if isinstance(value, list) else []


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_identifier(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()[:limit]
    return text if text and all(character.isalnum() or character in "._:-" for character in text) else ""


def _safe_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
