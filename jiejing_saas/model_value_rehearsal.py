"""Model-backed Agent value rehearsal over sanitized platform packets."""

from __future__ import annotations

import re
from typing import Any

from jiejing_runtime.adapters import JiejingAgentAdapter
from jiejing_runtime.model_clients import ModelClient, model_client_from_env, model_client_status_from_env
from jiejing_runtime.models import JiejingTask, now_iso
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

from .config import SaaSSettings
from .platform_data_packet_handoff import build_runtime_handoff_from_platform_packet, merge_runtime_handoff_input
from .repository import SaaSRepository


CORE_VALUE_TASKS = {"market.report", "listing.package"}


def run_model_value_rehearsal(
    *,
    settings: SaaSSettings,
    repository: SaaSRepository,
    company_id: str,
    store_id: str,
    user_id: str,
    packet_id: str | None = None,
    product: str = "",
    merchant_goal: str = "",
    allow_live_model: bool = False,
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    """Run a controlled model-backed value proof without platform writes.

    The Runtime receives only the sanitized platform data packet handoff. It
    never receives eBay tokens, raw platform responses, or model credentials.
    """

    packet_record = _select_packet(repository, company_id=company_id, store_id=store_id, packet_id=packet_id)
    model_status = model_client_status_from_env()
    blockers = _blockers(packet_record=packet_record, model_status=model_status, allow_live_model=allow_live_model, injected_model=model_client)
    if blockers:
        return _blocked_response(
            settings=settings,
            packet_record=packet_record,
            product=product,
            merchant_goal=merchant_goal,
            model_status=model_status,
            blockers=blockers,
        )

    client = model_client or model_client_from_env()
    handoff = build_runtime_handoff_from_platform_packet(packet_record)
    product_hint = _product_hint(packet_record)
    workflow_input = merge_runtime_handoff_input(
        {
            "product": _safe_requested_product(product=product, packet_record=packet_record, product_hint=product_hint),
            "merchant_goal": merchant_goal
            or "基于最新 eBay 官方只读标准数据包，生成商家能直接看懂的中文 Market Report 和 Listing Package；未知事实写成待补资料，不使用测试口吻。",
            "project_id": f"model-value-{_safe_id(packet_record.get('packet_id') or 'packet')}-{now_iso()[:10].replace('-', '')}",
            "stage": "store_opened",
            "platform": "ebay",
            "user_id": user_id,
            "company_id": company_id,
            "store_id": store_id,
            "marketplace": _marketplace(packet_record),
            "source_mode": str((packet_record.get("packet") or {}).get("source_mode") or packet_record.get("source_mode") or "platform_data_packet"),
            "notes": "C-class model value rehearsal. Merchant-facing output must be Chinese and production-toned. Uses sanitized packet only; no eBay token, no raw secret, no platform write.",
        },
        handoff,
    )
    request = ProductWorkflowRequest(
        product=str(workflow_input["product"]),
        merchant_goal=str(workflow_input["merchant_goal"]),
        project_id=str(workflow_input["project_id"]),
        stage=str(workflow_input["stage"]),
        platform="ebay",
        user_id=user_id,
        company_id=company_id,
        store_id=store_id,
        marketplace=str(workflow_input["marketplace"]),
        source_mode=str(workflow_input["source_mode"]),
        notes=str(workflow_input["notes"]),
        market_probe_inputs=workflow_input.get("market_probe_inputs") if isinstance(workflow_input.get("market_probe_inputs"), dict) else None,
        listing_metadata_probe=workflow_input.get("listing_metadata_probe") if isinstance(workflow_input.get("listing_metadata_probe"), dict) else None,
    )

    task = repository.create_task(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        task_type="model_value_rehearsal",
        title=f"模型价值证明：{request.product}",
        input_data={
            "product": request.product,
            "merchant_goal": request.merchant_goal,
            "packet_id": packet_record.get("packet_id"),
            "model_client": getattr(client, "name", "model_client"),
            "core_value_tasks": sorted(CORE_VALUE_TASKS),
            "runtime_gets_sanitized_packet_only": True,
            "runtime_gets_raw_ebay_token": False,
            "frontend_gets_model_api_key": False,
            "real_platform_writes_enabled": False,
        },
    )

    adapter = JiejingAgentAdapter(model_client=client)
    results = []
    confirmations = []
    for raw_task in build_product_workflow(request):
        if raw_task.get("task_type") not in CORE_VALUE_TASKS:
            continue
        result = adapter.execute(JiejingTask(raw_task))
        _tag_model_value_result(result, packet_record=packet_record, settings=settings)
        results.append(result)
        for item in result.get("confirmation_items") or []:
            if isinstance(item, dict):
                confirmations.append({**item, "source_task_type": result.get("task_type"), "source_packet_id": packet_record.get("packet_id")})

    run_id = f"model-value-rehearsal-{_safe_id(task['task_id'])}"
    runtime_result = {
        "run_id": run_id,
        "run": {
            "run_id": run_id,
            "run_status": "completed_with_policy_warnings",
            "adapter": "jiejing-agent-model-value-rehearsal",
            "started_at": now_iso(),
            "finished_at": now_iso(),
            "real_execution_allowed": False,
        },
        "results": results,
        "confirmations": confirmations,
        "validation_summary": {
            "core_value_tasks": sorted(CORE_VALUE_TASKS),
            "report_count": len(results),
            "confirmation_count": len(confirmations),
            "runtime_gets_raw_ebay_token": False,
            "frontend_gets_model_api_key": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    }
    task = repository.update_task_status(
        task_id=task["task_id"],
        company_id=company_id,
        status="completed",
        output={
            "status": "completed",
            "run_id": run_id,
            "packet_id": packet_record.get("packet_id"),
            "report_types": [item.get("task_type") for item in results],
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
        audit_summary="Model value rehearsal completed over sanitized platform data packet.",
    )
    saved = repository.save_runtime_outputs(task=task, runtime_result=runtime_result)
    live_report_types = [
        item.get("task_type")
        for item in results
        if ((item.get("report") or {}).get("model_assist") or {}).get("status") == "applied"
    ]
    missing_live_types = sorted(CORE_VALUE_TASKS - set(str(item) for item in live_report_types))
    blockers = _post_run_blockers(results=results, missing_live_types=missing_live_types)
    status = "completed" if not blockers else "blocked_after_model_rehearsal"
    return {
        "status": status,
        "blockers": blockers,
        "task": task,
        "saved_outputs": saved,
        "packet_id": packet_record.get("packet_id"),
        "report_types": [item.get("task_type") for item in results],
        "live_model_report_types": live_report_types,
        "model_client": {
            "client": getattr(client, "name", ""),
            "version": getattr(client, "version", ""),
            "secret_exposed": False,
        },
        "runtime_gets_sanitized_packet_only": True,
        "runtime_gets_raw_ebay_token": False,
        "frontend_gets_model_api_key": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _post_run_blockers(*, results: list[dict[str, Any]], missing_live_types: list[str]) -> list[str]:
    blockers: list[str] = []
    for result in results:
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        model_assist = report.get("model_assist") if isinstance(report.get("model_assist"), dict) else {}
        if model_assist.get("status") == "fallback_error" or report.get("model_error"):
            blockers.append("model_provider_error")
            break
    if missing_live_types:
        blockers.append(f"live_model_report_missing:{','.join(missing_live_types)}")
    return blockers


def _blockers(
    *,
    packet_record: dict[str, Any] | None,
    model_status: dict[str, Any],
    allow_live_model: bool,
    injected_model: ModelClient | None,
) -> list[str]:
    blockers: list[str] = []
    if not packet_record:
        blockers.append("sanitized_platform_data_packet_missing")
    packet = packet_record.get("packet") if isinstance(packet_record, dict) and isinstance(packet_record.get("packet"), dict) else {}
    if packet and packet.get("ready_for_runtime") is False:
        blockers.append("platform_data_packet_not_ready_for_runtime")
    if injected_model is None:
        if not allow_live_model:
            blockers.append("live_model_rehearsal_not_requested")
        if not model_status.get("configured"):
            blockers.append("model_provider_not_configured")
        if model_status.get("live_disabled"):
            blockers.append("model_live_calls_disabled")
    return blockers


def _blocked_response(
    *,
    settings: SaaSSettings,
    packet_record: dict[str, Any] | None,
    product: str,
    merchant_goal: str,
    model_status: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "blocked_before_model_rehearsal",
        "environment": settings.environment,
        "product": product,
        "merchant_goal": merchant_goal,
        "packet_id": packet_record.get("packet_id") if packet_record else "",
        "blockers": blockers,
        "model_client": {
            "client": model_status.get("client"),
            "configured": bool(model_status.get("configured")),
            "model": model_status.get("model"),
            "endpoint_host": model_status.get("endpoint_host"),
            "credential_present": bool(model_status.get("credential_present")),
            "live_disabled": bool(model_status.get("live_disabled")),
            "secret_exposed": False,
        },
        "would_create_reports": False,
        "required_commercial_proof": ["market.report", "listing.package"],
        "runtime_gets_sanitized_packet_only": True,
        "runtime_gets_raw_ebay_token": False,
        "frontend_gets_model_api_key": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _select_packet(
    repository: SaaSRepository,
    *,
    company_id: str,
    store_id: str,
    packet_id: str | None,
) -> dict[str, Any] | None:
    if packet_id:
        packet = repository.get_platform_data_packet(company_id=company_id, packet_id=packet_id)
        if packet and packet.get("store_id") == store_id:
            return packet
        return None
    packets = repository.list_platform_data_packets(company_id=company_id, store_id=store_id, platform="ebay", limit=1)
    return packets[0] if packets else None


def _tag_model_value_result(result: dict[str, Any], *, packet_record: dict[str, Any], settings: SaaSSettings) -> None:
    _ensure_chinese_merchant_visible_result(result, packet_record=packet_record)
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    report["model_value_rehearsal"] = {
        "contract_version": "2026-05-18-c-class-model-value-rehearsal",
        "environment": settings.environment,
        "source_packet_id": packet_record.get("packet_id"),
        "source_packet_mode": packet_record.get("source_mode"),
        "runtime_gets_sanitized_packet_only": True,
        "runtime_gets_raw_ebay_token": False,
        "frontend_gets_model_api_key": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    result["report"] = report
    result["source_packet_id"] = packet_record.get("packet_id")
    result["real_platform_writes_enabled"] = False
    result["secret_exposed"] = False


def _ensure_chinese_merchant_visible_result(result: dict[str, Any], *, packet_record: dict[str, Any]) -> None:
    task_type = str(result.get("task_type") or "")
    product = _product_hint(packet_record)
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    repaired_fields: list[str] = []

    summary = str(report.get("merchant_readable_summary") or result.get("summary") or "").strip()
    if _needs_chinese_repair(summary):
        summary = _chinese_summary(task_type, product)
        repaired_fields.append("summary")
    if summary:
        report["merchant_readable_summary"] = summary
        result["summary"] = summary

    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    repaired_sections: dict[str, Any] = {}
    for section_key, value in sections.items():
        repaired_value, changed = _repair_merchant_value(value, section_key=str(section_key), task_type=task_type, product=product)
        repaired_sections[section_key] = repaired_value
        if changed:
            repaired_fields.append(f"sections.{section_key}")
    if sections:
        report["sections"] = repaired_sections

    for field_name in ("risk_flags", "missing_inputs", "confirmation_items"):
        value = result.get(field_name)
        if isinstance(value, list):
            repaired_value, changed = _repair_merchant_value(value, section_key=field_name, task_type=task_type, product=product)
            result[field_name] = repaired_value
            if changed:
                repaired_fields.append(field_name)

    quality = report.get("merchant_language_quality") if isinstance(report.get("merchant_language_quality"), dict) else {}
    quality.update(
        {
            "merchant_visible_language": "zh-CN",
            "checked_before_persist": True,
            "english_heavy_fields_repaired": sorted(set(repaired_fields)),
            "allowed_english_terms": ["eBay", "SKU", "Listing", "Market Report", "Listing Package"],
        }
    )
    report["merchant_language_quality"] = quality
    result["report"] = report


def _repair_merchant_value(value: Any, *, section_key: str, task_type: str, product: str) -> tuple[Any, bool]:
    if isinstance(value, str):
        if _needs_chinese_repair(value):
            return _chinese_section_text(section_key, task_type, product), True
        return value, False
    if isinstance(value, list):
        changed = False
        repaired_items = []
        for item in value:
            repaired, item_changed = _repair_merchant_value(item, section_key=section_key, task_type=task_type, product=product)
            repaired_items.append(repaired)
            changed = changed or item_changed
        return repaired_items, changed
    if isinstance(value, dict):
        changed = False
        repaired_dict = {}
        for key, item in value.items():
            repaired, item_changed = _repair_merchant_value(item, section_key=f"{section_key}.{key}", task_type=task_type, product=product)
            repaired_dict[key] = repaired
            changed = changed or item_changed
        return repaired_dict, changed
    return value, False


def _needs_chinese_repair(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk_count >= 2:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
    letters = len(re.findall(r"[A-Za-z]", text))
    return len(words) >= 5 and letters >= 28


def _chinese_summary(task_type: str, product: str) -> str:
    if task_type == "market.report":
        return f"市场报告已基于当前官方 eBay packet 生成中文版本；{product} 的机会、风险、来源缺口和下一步已保持可见。"
    if task_type == "listing.package":
        return f"Listing Package 已生成中文刊登资料草稿；{product} 的标题、参数、描述、素材需求和发布前确认项仍需复核。"
    return f"{product} 的捷境工作报告已通过中文质量门禁；缺失事实会显示为待补资料。"


def _chinese_section_text(section_key: str, task_type: str, product: str) -> str:
    key = section_key.split(".")[0]
    market_sections = {
        "category_overview": f"依据当前官方 eBay packet，{product} 的品类机会需要结合真实 Listing、订单、费用和履约数据继续核查；没有来源的数据保持待补资料。",
        "buyer_profile": "买家画像需基于官方订单、公开来源或商家输入确认；当前只保留可解释方向，不编造具体人群规模。",
        "ebay_price_bands": "价格带需要结合 eBay 官方数据、费用和物流成本复核；未接实时行情或外部搜索时不编具体销量结论。",
        "competitor_top5": "竞品列表等待外部搜索或授权数据源补齐；没有来源记录时只显示缺口和下一步。",
        "buyer_pain_points": "买家痛点应围绕尺寸、材质、发货时效、图片真实性和售后风险继续核查。",
        "keywords": "关键词建议需结合官方类目、标题规则和后续搜索来源复核。",
        "differentiation": "差异化建议应建立在已确认商品事实、素材质量和履约能力上。",
        "pricing_direction": "定价方向需要费用、物流、退货预留和平台费用共同验证。",
        "risk_assessment": "风险包括来源不足、利润不可算、履约不稳、IP/合规不明和发布前确认未完成。",
        "conclusion_next_step": "下一步：补齐来源记录、供应商事实、类目字段和确认中心事项，再推进 Listing Package。",
    }
    listing_sections = {
        "sku": "SKU 等待商家规则或官方库存记录确认。",
        "title": f"{product} 的 eBay 标题需控制在平台限制内，并基于真实材质、用途、规格和关键词生成。",
        "subtitle_notice": "eBay subtitle 可能产生额外费用，默认不启用，除非商家在决策中心确认。",
        "category_id": "类目 ID 必须来自 eBay taxonomy 或人工确认；类目不确定时不能真实发布。",
        "condition": "Condition 需要按商品真实状态确认。",
        "format": "刊登形式默认按固定价格草稿处理，真实发布前进入确认中心。",
        "price": "价格需要结合采购成本、运费、平台费用和退货预留复核。",
        "quantity": "库存数量必须来自真实库存或商家输入；不能用旧样例补空白。",
        "item_specifics": "Item Specifics 需要按 eBay 类目必填字段补齐，未知项保持待补资料。",
        "description_html": "描述 HTML 应只写已确认事实，材质、尺寸、包装清单和承诺不明时标为待补资料。",
        "pictures_required": "素材需求至少包含白底主图、场景图、细节图、尺寸图和包装清单图，并保留实物一致性审核。",
        "video_required": "视频需求可先生成 15-30 秒脚本和分镜，真实素材发布前需要来源和授权确认。",
        "package_weight": "包裹重量等待供应商或实测数据确认。",
        "package_dimensions": "包裹尺寸等待供应商或实测数据确认。",
        "business_policies": "发货、付款、退货政策必须来自已授权店铺的官方 policy 记录。",
        "publish_blockers": "发布阻断项：供应商事实、类目字段、政策 ID、价格利润、素材和商家确认未全部完成。",
    }
    if task_type == "market.report":
        return market_sections.get(key, f"{key} 已进入中文质量门禁；没有可靠来源时保持待补资料，并给出下一步。")
    if task_type == "listing.package":
        return listing_sections.get(key, f"{key} 已进入中文刊登资料草稿；真实发布前必须复核来源、字段和确认中心边界。")
    return f"{key} 已改为中文商家可读说明；未知事实保持待补资料。"


def _product_hint(packet_record: dict[str, Any] | None) -> str:
    packet = packet_record.get("packet") if isinstance(packet_record, dict) and isinstance(packet_record.get("packet"), dict) else {}
    sections = packet.get("sections") if isinstance(packet.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        for key in ("listing_title", "title", "sku"):
            if data.get(key):
                return str(data[key])[:120]
        for list_key in ("inventory_items", "offers", "listings", "items"):
            items = data.get(list_key) if isinstance(data.get(list_key), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key in ("listing_title", "title", "sku", "item_id"):
                    if item.get(key):
                        return str(item[key])[:120]
    return "Official eBay packet without selected SKU"


def _packet_has_product_identity(packet_record: dict[str, Any] | None) -> bool:
    return _product_hint(packet_record) != "Official eBay packet without selected SKU"


def _safe_requested_product(*, product: str, packet_record: dict[str, Any] | None, product_hint: str) -> str:
    if _packet_has_product_identity(packet_record):
        return (product or product_hint)[:120]
    # When the official packet only proves store/account readiness, do not let
    # a store or account label become the product name in merchant-facing output.
    return product_hint


def _marketplace(packet_record: dict[str, Any] | None) -> str:
    packet = packet_record.get("packet") if isinstance(packet_record, dict) and isinstance(packet_record.get("packet"), dict) else {}
    return str(packet.get("marketplace") or "EBAY_US")


def _safe_id(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower()).strip("-")[:48] or "value"
