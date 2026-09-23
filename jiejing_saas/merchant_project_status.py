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
    user_id: str = "",
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

    evidence = repository.list_merchant_project_evidence(
        company_id=company_id, store_id=store_id, project_id=clean_project_id,
        user_id=user_id, evidence_cutoff=cutoff,
    )
    tasks = _before_cutoff(evidence.get("tasks"), cutoff)
    reports = _before_cutoff(evidence.get("reports"), cutoff)
    confirmations = _before_cutoff(evidence.get("confirmations"), cutoff)
    media_jobs = _before_cutoff(evidence.get("media_jobs"), cutoff)
    executions = _before_cutoff(evidence.get("executions"), cutoff)
    chat_turns = _before_cutoff(evidence.get("chat_turns"), cutoff)

    identity_records = [*tasks, *reports, *media_jobs, *confirmations, *chat_turns]
    project_identities = [
        identity
        for identity in (_artifact_identity(item) for item in identity_records)
        if identity.get("key") == clean_project_id
    ]
    canonical_identity, identity_conflict = _merge_identities(clean_project_id, project_identities)

    # The immutable source report is an exact project reference, not a page
    # position. Keep it (and its owning task) even after this same project has
    # produced more versions than the bounded recent-evidence windows.
    source_report_id = str(canonical_identity.get("source_report_id") or "")
    if source_report_id and not identity_conflict and not any(
        str(item.get("report_id") or "") == source_report_id for item in reports
    ):
        source_report = repository.get_report_for_company(company_id=company_id, report_id=source_report_id)
        if source_report and str(source_report.get("store_id") or "") == store_id:
            source_task = repository.get_task(company_id=company_id, task_id=str(source_report.get("task_id") or ""))
            source_identity = _artifact_identity(source_report)
            # An exact reference may recover legacy/unbound source evidence,
            # but never override an explicit identity belonging elsewhere.
            source_conflict = any(
                identity.get(field) and canonical_identity.get(field)
                and identity[field] != canonical_identity[field]
                for identity in (source_identity, _artifact_identity(source_task))
                for field in ("key", "source_report_id", "candidate_id")
            )
            if (source_task and str(source_task.get("store_id") or "") == store_id
                    and not source_conflict
                    and _before_cutoff([source_report], cutoff) and _before_cutoff([source_task], cutoff)):
                reports.append(source_report)
                if not any(item.get("task_id") == source_task.get("task_id") for item in tasks):
                    tasks.append(source_task)
                if source_identity.get("key") == clean_project_id:
                    canonical_identity, identity_conflict = _merge_identities(
                        clean_project_id, [*project_identities, source_identity],
                    )

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
    # A brand-new AI CEO market-research turn cannot bind its task to a project
    # identity that is minted only when the source report is saved.  Recover
    # that one source task from the authoritative, fully-bound market report;
    # other matching report types must not pull their unbound tasks into the
    # project's audit trail.
    source_report_id = str(canonical_identity.get("source_report_id") or "")
    source_candidate_id = str(canonical_identity.get("candidate_id") or "")
    authoritative_source_task_ids: set[str] = set()
    if source_report_id and source_candidate_id:
        for item in matching_reports:
            report_identity = _artifact_identity(item)
            if (
                str(item.get("report_type") or "") == "ai_ceo.market_research"
                and str(item.get("report_id") or "") == source_report_id
                and report_identity.get("identity_contract") != "legacy_compatible"
                and all(
                    report_identity.get(field) == canonical_identity.get(field)
                    for field in ("key", "source_report_id", "candidate_id")
                )
                and item.get("task_id")
            ):
                authoritative_source_task_ids.add(str(item["task_id"]))
    if authoritative_source_task_ids:
        matching_tasks = [
            item
            for item in tasks
            if _identity_matches(_artifact_identity(item), canonical_identity)
            or str(item.get("task_id") or "") in authoritative_source_task_ids
        ]
        matching_task_ids = {str(item.get("task_id") or "") for item in matching_tasks}
    matching_media = [item for item in media_jobs if _identity_matches(_artifact_identity(item), canonical_identity)]
    matching_confirmations = [
        item for item in confirmations if _identity_matches(_artifact_identity(item), canonical_identity)
    ]
    matching_confirmation_ids = {str(item.get("confirmation_id") or "") for item in matching_confirmations}
    matching_executions = [
        item for item in executions if str(item.get("confirmation_id") or "") in matching_confirmation_ids
    ]
    matching_chat_turns = [
        item for item in chat_turns if _identity_matches(_artifact_identity(item), canonical_identity)
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
    # Count distinct missing fields, not review rules. Source attestation may
    # have both a field blocker and a rule blocker; simulation is not a field.
    fact_gap_keys = set(unknown_facts)
    for reason in fact_blockers:
        for prefix in ("merchant_product_fact_missing:", "product_fact_missing:"):
            if reason.startswith(prefix) and reason[len(prefix):].strip():
                fact_gap_keys.add(reason[len(prefix):].strip())
    fact_gap_count = len(fact_gap_keys)
    facts_simulation_only = "simulation_only_product_facts" in fact_blockers
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

    downstream_platform_ready = draft_ready or publish_ready
    if downstream_platform_ready:
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
    if draft_ready:
        # A project-bound, successfully saved eBay draft is stronger evidence
        # than stale prerequisite snapshots created earlier in the workflow.
        # Preserve those snapshots in audit history, but keep merchant progress
        # monotonic after the platform has accepted the unpublished Offer.
        for completed_stage in ("intake", "research", "facts", "media", "listing", "ebay_draft"):
            stage_statuses[completed_stage] = "completed"

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
    elif not downstream_platform_ready and latest_fact_report and (unknown_facts or fact_blockers):
        current_stage = "facts"
        blocker = _blocker(
            "product_facts_missing",
            "商品事实还没有补齐" if fact_gap_count else "演练商品不能用于发布" if facts_simulation_only else "商品资料仍需核对",
            f"还有 {fact_gap_count} 项商品资料待商家确认。" if fact_gap_count else
            "资料已填写，但当前商品仅供演练。真实上架请使用可销售商品并核对来源。" if facts_simulation_only else
            "资料已填写，但来源、内容或审核条件尚未满足。请检查商品资料中的提示。",
        )
        next_action = _next_action("complete_product_facts", "补齐商品资料" if fact_gap_count else "核对商品资料", "product")
        overall_status = "blocked"
    elif not downstream_platform_ready and media_failed:
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
        "facts": (
            "商品事实已补齐"
            if facts_ready
            else "未发布草稿已保存，早期事实快照保留在记录中"
            if downstream_platform_ready
            else (f"{fact_gap_count} 项待补" if fact_gap_count else "仅供演练" if facts_simulation_only else "资料待核对")
            if latest_fact_report
            else "等待商品事实"
        ),
        "media": (
            "素材已通过商家审核"
            if media_ready
            else "未发布草稿已保存，早期素材版本保留在记录中"
            if downstream_platform_ready
            else "当前素材需要处理"
            if media_failed
            else "等待素材生成与审核"
        ),
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
        work_record_index=_build_work_record_index(
            chats=matching_chat_turns,
            tasks=matching_tasks,
            reports=matching_reports,
            media=matching_media,
            confirmations=matching_confirmations,
            executions=matching_executions,
        ),
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
    work_record_index: dict[str, Any] | None = None,
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
        "work_record_index": work_record_index or _empty_work_record_index(),
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
    legacy_keys = [
        item.get("listing_project_key"),
        _nested(item, "input", "listing_project_key"),
        _nested(item, "output", "listing_project_key"),
        _nested(item, "report", "listing_project_key"),
        _nested(item, "item", "listing_project_key"),
        _nested(item, "job", "listing_project_key"),
        _nested(item, "job", "job_spec", "listing_project_key"),
        _nested(item, "job", "job_spec", "inputs", "product_facts", "listing_project_key"),
    ]
    for candidate in legacy_keys:
        key = _safe_identifier(candidate, limit=160)
        if key and _legacy_identity_compatible(item):
            return {
                "key": key,
                "source_report_id": "",
                "candidate_id": "",
                "identity_contract": "legacy_compatible",
            }
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
    if identity.get("identity_contract") == "legacy_compatible":
        return True
    return all(
        identity.get(field) == canonical.get(field)
        for field in ("source_report_id", "candidate_id")
    )


def _legacy_identity_compatible(item: dict[str, Any]) -> bool:
    candidates = (
        item.get("legacy_project_identity_compatible"),
        _nested(item, "input", "legacy_project_identity_compatible"),
        _nested(item, "output", "legacy_project_identity_compatible"),
        _nested(item, "report", "legacy_project_identity_compatible"),
        _nested(item, "item", "legacy_project_identity_compatible"),
        _nested(item, "job", "legacy_project_identity_compatible"),
    )
    return any(value is True for value in candidates)


def _empty_work_record_index() -> dict[str, Any]:
    return {
        "contract_version": "merchant_project_work_record_index_v1",
        "current_project_only": True,
        "items": [],
        "counts": {},
        "secret_exposed": False,
    }


def _build_work_record_index(
    *,
    chats: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    media: list[dict[str, Any]],
    confirmations: list[dict[str, Any]],
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []

    def add(
        record_id: Any,
        *,
        record_type: str,
        status: Any,
        title: Any,
        summary: Any,
        occurred_at: Any,
        target_view: str,
    ) -> None:
        safe_id = _safe_identifier(record_id, limit=160)
        if not safe_id:
            return
        rows.append(
            {
                "record_id": safe_id,
                "record_type": record_type,
                "status": _safe_text(status, limit=60),
                "title": _safe_text(title, limit=180),
                "summary": _safe_text(summary, limit=320),
                "occurred_at": str(occurred_at or "")[:80],
                "target_view": target_view,
            }
        )

    for item in chats:
        add(
            item.get("assistant_id"),
            record_type="ai_ceo_chat",
            status=item.get("status"),
            title=item.get("user_text") or "AI CEO 对话",
            summary=item.get("assistant_text") or "",
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view="cockpit",
        )
    for item in tasks:
        task_type = str(item.get("task_type") or "task")
        add(
            item.get("task_id"),
            record_type="customer_task" if "customer" in task_type else "task",
            status=item.get("status"),
            title=_work_record_task_title(task_type, item.get("title")),
            summary=_work_record_task_summary(task_type),
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view="service" if "customer" in task_type else "activity",
        )
    for item in reports:
        report_type = str(item.get("report_type") or "report")
        record_type, target_view = _work_record_report_route(report_type)
        payload = item.get("report") if isinstance(item.get("report"), dict) else {}
        add(
            item.get("report_id"),
            record_type=record_type,
            status=item.get("status"),
            title=item.get("title") or _work_record_report_title(report_type),
            summary=(
                _nested(payload, "merchant_product_fact_packet", "product_name")
                or _nested(payload, "sections", "title")
                or payload.get("summary")
                or "已保存到当前商品项目。"
            ),
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view=target_view,
        )
    for item in media:
        add(
            item.get("media_job_id"),
            record_type="media_job",
            status=item.get("status"),
            title="商品素材任务",
            summary="素材生成与商家审核记录。",
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view="media",
        )
    for item in confirmations:
        add(
            item.get("confirmation_id"),
            record_type="confirmation",
            status=item.get("status"),
            title=_work_record_action_title(item.get("action_type")),
            summary="高风险动作确认记录。",
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view="confirm",
        )
    for item in executions:
        add(
            item.get("execution_id"),
            record_type="execution",
            status=item.get("status"),
            title=_work_record_action_title(item.get("action_type")),
            summary="平台执行结果已归档。",
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target_view="activity",
        )

    rows.sort(key=lambda item: (_parse_instant(item["occurred_at"]) or datetime.min.replace(tzinfo=timezone.utc), item["record_id"]), reverse=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["record_type"]] = counts.get(row["record_type"], 0) + 1
    return {
        "contract_version": "merchant_project_work_record_index_v1",
        "current_project_only": True,
        "items": rows[:80],
        "counts": counts,
        "secret_exposed": False,
    }


def _work_record_task_title(task_type: str, raw_title: Any) -> str:
    return {
        "merchant_ceo_chat_attempt": "AI CEO 处理记录",
        "merchant_ceo_chat": "AI CEO 分析",
        "merchant_product_facts": "商品资料",
        "listing_draft_generation": "AI Listing 草稿生成",
        "ebay_draft_save_intake": "保存 eBay 未发布草稿准备",
        "existing_ebay_draft_publish_intake": "eBay 正式发布确认准备",
    }.get(task_type, _safe_text(raw_title, limit=180) or "工作任务")


def _work_record_task_summary(task_type: str) -> str:
    return {
        "merchant_ceo_chat_attempt": "AI CEO 本轮处理留痕。",
        "merchant_ceo_chat": "AI CEO 已完成本轮分析。",
        "merchant_product_facts": "商品资料已保存。",
        "listing_draft_generation": "AI Listing 草稿生成任务。",
        "ebay_draft_save_intake": "未发布草稿保存准备记录。",
        "existing_ebay_draft_publish_intake": "正式发布前的确认与预检记录。",
    }.get(task_type, "当前商品项目的工作任务。")


def _work_record_report_route(report_type: str) -> tuple[str, str]:
    if report_type == "merchant.product_facts":
        return "product_facts", "product"
    if report_type in {"listing.package", "product.listing"}:
        return "listing_draft", "product"
    if "customer" in report_type:
        return "customer_report", "service"
    return "report", "activity"


def _work_record_report_title(report_type: str) -> str:
    return {
        "merchant.product_facts": "商品资料",
        "listing.package": "Listing 草稿",
        "product.listing": "Listing 草稿",
        "ai_ceo.market_research": "市场调研报告",
    }.get(report_type, "项目报告")


def _work_record_action_title(action_type: Any) -> str:
    return {
        "save_ebay_listing_draft": "保存 eBay 未发布草稿",
        "publish_listing": "正式发布 eBay Listing",
        "send_customer_reply": "发送客服回复",
    }.get(str(action_type or ""), "受控执行动作")


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
        candidates = (
            packet.get("product_name"),
            payload.get("product"),
            _nested(payload, "selected_product_candidate", "name"),
            _nested(payload, "listing_project_identity", "product"),
        )
        for value in candidates:
            if _safe_text(value, limit=160):
                return _safe_text(value, limit=160)
    for task in sorted(tasks, key=_timestamp_order, reverse=True):
        # Task titles describe technical work (model attempt, retry, publish
        # intake), not merchant products.  They remain useful audit records but
        # must never relabel the current Listing project.  Only explicit product
        # fields carried by project-bound evidence are eligible here.
        candidates = (
            _nested(task, "input", "merchant_product_fact_packet", "product_name"),
            _nested(task, "input", "listing_project_identity", "product"),
            _nested(task, "input", "product_name"),
            _nested(task, "input", "product"),
            _nested(task, "output", "merchant_product_fact_packet", "product_name"),
            _nested(task, "output", "listing_project_identity", "product"),
            _nested(task, "output", "product_name"),
            _nested(task, "output", "product"),
        )
        for value in candidates:
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
