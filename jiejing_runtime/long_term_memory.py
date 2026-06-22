"""Long-term memory records for Jiejing Runtime.

The static knowledge pack teaches the Runtime project rules and SOPs. Long-term
memory is different: it stores merchant, store, product, workflow, and agent
lessons discovered while running real or simulated commerce tasks.

This module deliberately stores only sanitized, reviewable memory records. It
must not become a credential vault, buyer-data dump, or hidden execution path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .knowledge import sanitize_text
from .models import now_iso


MEMORY_VERSION = "2026-05-15.1"

ALLOWED_SCOPE_TYPES = {"global", "company", "store", "product", "workflow", "role"}

BLOCKED_MEMORY_TERMS = re.compile(
    r"(?i)(access[_-]?token|refresh[_-]?token|authorization|cookie|password|client[_-]?secret|"
    r"buyer email|buyer address|credit card|银行卡|密码|令牌|密钥)"
)


@dataclass(slots=True)
class LongTermMemoryRecord:
    memory_id: str
    scope_type: str
    scope_id: str
    title: str
    content: str
    user_id: str = ""
    company_id: str = ""
    store_id: str = ""
    product: str = ""
    role: str = ""
    task_type: str = ""
    tags: list[str] = field(default_factory=list)
    source_run_id: str = ""
    source_task_id: str = ""
    confidence: str = "medium"
    priority: int = 50
    memory_status: str = "active"
    visibility: str = "internal_runtime"
    sensitivity_level: str = "sanitized"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_memory_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
    safe = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:46]
    return f"mem_{safe}_{digest}" if safe else f"mem_{digest}"


def build_memory_record(
    *,
    scope_type: str,
    scope_id: str,
    title: str,
    content: str,
    user_id: str = "",
    company_id: str = "",
    store_id: str = "",
    product: str = "",
    role: str = "",
    task_type: str = "",
    tags: list[str] | None = None,
    source_run_id: str = "",
    source_task_id: str = "",
    confidence: str = "medium",
    priority: int = 50,
    memory_status: str = "active",
) -> LongTermMemoryRecord | None:
    """Create one sanitized memory record, or None if the content is unsafe."""

    scope_type = scope_type if scope_type in ALLOWED_SCOPE_TYPES else "workflow"
    raw_title = str(title or "").strip()
    raw_content = str(content or "").strip()
    if BLOCKED_MEMORY_TERMS.search(raw_title) or BLOCKED_MEMORY_TERMS.search(raw_content):
        return None
    sanitized_title, _ = sanitize_text(raw_title)
    sanitized_content, _ = sanitize_text(raw_content)
    if not sanitized_title or not sanitized_content:
        return None
    if BLOCKED_MEMORY_TERMS.search(sanitized_title) or BLOCKED_MEMORY_TERMS.search(sanitized_content):
        return None
    normalized_tags = sorted({re.sub(r"[^a-z0-9_.:-]+", "-", str(tag).lower()).strip("-") for tag in (tags or []) if str(tag).strip()})
    memory_id = make_memory_id(scope_type, scope_id, task_type, role, sanitized_title, source_run_id, source_task_id)
    now = now_iso()
    return LongTermMemoryRecord(
        memory_id=memory_id,
        scope_type=scope_type,
        scope_id=str(scope_id or "runtime"),
        title=sanitized_title[:180],
        content=sanitized_content[:4000],
        user_id=str(user_id or ""),
        company_id=str(company_id or ""),
        store_id=str(store_id or ""),
        product=str(product or ""),
        role=str(role or ""),
        task_type=str(task_type or ""),
        tags=normalized_tags,
        source_run_id=str(source_run_id or ""),
        source_task_id=str(source_task_id or ""),
        confidence=confidence if confidence in {"low", "medium", "high"} else "medium",
        priority=max(0, min(100, int(priority))),
        memory_status=memory_status if memory_status in {"active", "pending_review", "archived"} else "active",
        created_at=now,
        updated_at=now,
    )


def memory_candidates_from_result(run_id: str, result: dict[str, Any]) -> list[LongTermMemoryRecord]:
    """Extract safe long-term memory candidates from one Runtime result."""

    task_type = str(result.get("task_type") or "")
    task_id = str(result.get("task_id") or "")
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    merchant_profile = report.get("merchant_profile") if isinstance(report.get("merchant_profile"), dict) else {}
    product = _guess_product(result, report)
    role = str((report.get("owned_agent_execution") or {}).get("role") or report.get("agent_role") or "")
    common = {
        "user_id": str(merchant_profile.get("user_id") or ""),
        "company_id": str(merchant_profile.get("company_id") or ""),
        "store_id": str(merchant_profile.get("store_id") or ""),
        "product": product,
        "role": role,
        "task_type": task_type,
        "source_run_id": run_id,
        "source_task_id": task_id,
    }

    candidates: list[LongTermMemoryRecord] = []
    summary = str(result.get("summary") or report.get("merchant_readable_summary") or "").strip()
    if summary:
        record = build_memory_record(
            scope_type="workflow",
            scope_id=run_id,
            title=f"{_task_label(task_type)} summary",
            content=summary,
            tags=["runtime-summary", task_type.replace(".", "-")],
            priority=55,
            **common,
        )
        if record:
            candidates.append(record)

    if task_type == "market.report":
        candidates.extend(_section_records(common, run_id, sections, ["recommendation", "price_bands", "risk_signal", "next_step"], "market-learning", 70))
    elif task_type == "listing.package":
        candidates.extend(_section_records(common, run_id, sections, ["listing_fields", "item_specifics", "publish_blockers", "supplier_questions"], "listing-learning", 75))
    elif task_type == "asset.brief":
        candidates.extend(_section_records(common, run_id, sections, ["image_plan", "detail_page_plan", "video_plan", "asset_settings"], "asset-learning", 70))
    elif task_type == "customer.learn_product":
        candidates.extend(_section_records(common, run_id, sections, ["service_boundaries", "safe_reply_rules", "handoff_triggers"], "service-learning", 70))
    elif task_type == "finance.review":
        candidates.extend(_section_records(common, run_id, sections, ["profit_assumptions", "logistics_risk", "stop_conditions"], "finance-learning", 70))
    elif task_type == "confirmation.package":
        candidates.extend(_section_records(common, run_id, sections, ["must_confirm_actions", "safe_auto_actions", "blocked_actions"], "confirmation-learning", 80))

    return candidates


def summarize_memory_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_scope: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_task: dict[str, int] = {}
    for item in records:
        by_scope[item.get("scope_type") or "unknown"] = by_scope.get(item.get("scope_type") or "unknown", 0) + 1
        by_role[item.get("role") or "unknown"] = by_role.get(item.get("role") or "unknown", 0) + 1
        by_task[item.get("task_type") or "unknown"] = by_task.get(item.get("task_type") or "unknown", 0) + 1
    return {
        "memory_version": MEMORY_VERSION,
        "record_count": len(records),
        "by_scope": by_scope,
        "by_role": by_role,
        "by_task_type": by_task,
        "safety_boundary": "Sanitized runtime memory only; credentials, buyer private data, and real execution authority are not stored here.",
    }


def _section_records(
    common: dict[str, Any],
    run_id: str,
    sections: dict[str, Any],
    keys: list[str],
    tag: str,
    priority: int,
) -> list[LongTermMemoryRecord]:
    records: list[LongTermMemoryRecord] = []
    for key in keys:
        if key not in sections:
            continue
        value = sections[key]
        content = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)
        record = build_memory_record(
            scope_type="product" if common.get("product") else "workflow",
            scope_id=common.get("product") or run_id,
            title=f"{_task_label(str(common.get('task_type') or ''))}: {key}",
            content=content,
            tags=[tag, str(common.get("task_type") or "").replace(".", "-"), key],
            priority=priority,
            **common,
        )
        if record:
            records.append(record)
    return records


def _guess_product(result: dict[str, Any], report: dict[str, Any]) -> str:
    input_data = result.get("input") if isinstance(result.get("input"), dict) else {}
    for value in [
        input_data.get("product"),
        report.get("product"),
        (report.get("sections") or {}).get("product"),
    ]:
        if value:
            return str(value)
    summary = str(result.get("summary") or "")
    match = re.search(r"for\s+(.+?)(?:;|\.|$)", summary)
    return match.group(1).strip()[:120] if match else ""


def _task_label(task_type: str) -> str:
    return {
        "ceo.intake": "AI CEO intake",
        "market.data_packet": "Market data packet",
        "market.report": "Market report",
        "source.match": "Source match",
        "listing.package": "Listing package",
        "asset.brief": "Asset brief",
        "customer.learn_product": "Customer learning",
        "finance.review": "Finance review",
        "confirmation.package": "Confirmation package",
        "ceo.final_report": "CEO final report",
        "owner.review": "Owner review",
    }.get(task_type, task_type or "Runtime")
