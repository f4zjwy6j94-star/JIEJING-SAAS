"""Production replacement readiness for Jiejing-owned Agents.

This is deliberately stricter than the local demo scorecard. A high local demo
score means the Runtime can run a safe simulation. It does not mean Jiejing can
run production merchant workflows with no external execution substrate. This
evaluator tracks the hard capabilities that must exist before the self-owned
Agent team can independently carry live SaaS work.
"""

from __future__ import annotations

from typing import Any, Protocol

from .capabilities import RuntimeCapabilityProfile
from .model_clients import model_client_status_from_env
from .provider_job_contracts import build_provider_job_contract_catalog
from .saas_snapshot import build_saas_snapshot


READINESS_VERSION = "2026-05-15.1"


class RuntimeRepositoryView(Protocol):
    db_path: Any

    def list_runs(self) -> list[dict[str, Any]]: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def get_results(self, run_id: str) -> list[dict[str, Any]]: ...

    def get_confirmations(self, run_id: str) -> list[dict[str, Any]]: ...

    def get_validation_summary(self, run_id: str) -> dict[str, Any]: ...


def build_replacement_readiness(repo: RuntimeRepositoryView | None = None) -> dict[str, Any]:
    """Return an honest self-owned Agent production readiness view.

    The returned `production_replacement_percent` is the number that should be
    used when the question is "can self-owned Jiejing Agents carry live SaaS
    work independently?" It is intentionally lower than local demo readiness.
    """

    capability = RuntimeCapabilityProfile(repo.db_path if repo else None).to_dict()
    capability_by_key = {item.get("key"): item for item in capability.get("capabilities", []) if isinstance(item, dict)}
    providers = capability.get("provider_status", {}) if isinstance(capability.get("provider_status"), dict) else {}
    model_status = model_client_status_from_env()
    latest = _latest_context(repo)
    snapshot = latest.get("snapshot", {})
    owned = snapshot.get("owned_agent", {}) if isinstance(snapshot.get("owned_agent"), dict) else {}
    executions = owned.get("executions", []) if isinstance(owned.get("executions"), list) else []
    validations = latest.get("validation_summary", {}).get("validations", [])
    confirmations = latest.get("confirmations", [])
    memory = capability.get("long_term_memory", {}) if isinstance(capability.get("long_term_memory"), dict) else {}
    provider_job_contracts = build_provider_job_contract_catalog()
    provider_job_keys = {
        item.get("key")
        for item in provider_job_contracts.get("contracts", [])
        if isinstance(item, dict)
    }

    dimensions = [
        _dimension(
            key="task_protocol_and_contracts",
            label="任务协议与报告合同",
            max_score=8,
            score=6 if _ready(capability_by_key, "task_protocol") and _ready(capability_by_key, "role_report_contract") else 3,
            status="ready" if _ready(capability_by_key, "task_protocol") and _ready(capability_by_key, "role_report_contract") else "partial",
            evidence=[
                "JiejingTask、11 段流程、报告必填段落和校验器已经存在。",
                f"最近一次链路岗位校验 {len(validations)} 条。",
            ],
            remaining=[],
        ),
        _dimension(
            key="owned_agent_roles",
            label="自研 7 岗位执行",
            max_score=10,
            score=5 if owned.get("role_count", 0) >= 7 and owned.get("all_results_have_owned_execution") else 4,
            status="local_ready" if owned.get("role_count", 0) >= 7 else "partial",
            evidence=[
                f"最近一次链路看到 {owned.get('role_count', 0)}/7 个岗位。",
                f"{owned.get('execution_count', 0)} 段结果带自研执行标记。",
            ],
            remaining=["还需要连续同题对跑 Hermes，证明报告质量、缺口识别和稳定性不低于 Hermes。"],
        ),
        _dimension(
            key="live_model_execution",
            label="真实大模型调用",
            max_score=9,
            score=_model_score(model_status, executions),
            status="configured_not_exercised" if model_status.get("configured") and not _live_model_count(executions) else "ready" if _live_model_count(executions) else "fallback_only",
            evidence=[
                f"模型配置状态：{bool(model_status.get('configured'))}。",
                f"最近一次链路实时模型段数：{_live_model_count(executions)}。",
            ],
            remaining=["生产替代必须让市场、刊登、客服、财务等关键岗位稳定使用模型，而不是只靠规则兜底。"],
        ),
        _dimension(
            key="public_search_and_market_tools",
            label="全网搜索与市场调研工具",
            max_score=10,
            score=4 if _truthy(providers.get("public_search_tavily", {}).get("configured")) else 2,
            status="provider_configured" if _truthy(providers.get("public_search_tavily", {}).get("configured")) else "contract_only",
            evidence=[
                f"Tavily configured={providers.get('public_search_tavily', {}).get('configured')}",
                "Runtime 已有 market_data_packet 和 public_search_probe 边界。",
            ],
            remaining=["还要做稳定查询模板、反超时拆分、来源去重、价格区间抽取、竞品 TopN 结构化。"],
        ),
        _dimension(
            key="ebay_read_and_listing_metadata",
            label="eBay 只读与刊登元数据",
            max_score=10,
            score=5 if _ebay_ready(providers.get("ebay", {})) else 3,
            status="credential_ready" if _ebay_ready(providers.get("ebay", {})) else "needs_token_refresh",
            evidence=[
                f"eBay credential_present={providers.get('ebay', {}).get('credential_present')}",
                f"eBay access_token_status={providers.get('ebay', {}).get('access_token_status')}",
            ],
            remaining=["还要把 Browse、Taxonomy、Account policies、订单和费用读取做成稳定任务链，并与店铺权限隔离。"],
        ),
        _dimension(
            key="sourcing_and_logistics_tools",
            label="1688/货源与物流工具",
            max_score=11,
            score=3 if {"sourcing.1688_availability", "logistics.orange_connex_quote"}.issubset(provider_job_keys) else 2,
            status="provider_job_contract_ready" if {"sourcing.1688_availability", "logistics.orange_connex_quote"}.issubset(provider_job_keys) else "adapter_shell_only",
            evidence=[
                "当前能整理手动/样例货源、包装资料和物流估算。",
                "1688 和橙联/SpeedPAK 已有队列作业合同；真实读取、报价和下单仍未生产化。",
            ],
            remaining=["必须接真实货源读取、供应商候选去重、价格/库存/发货地校验、物流实时报价和费用留痕。"],
        ),
        _dimension(
            key="media_generation_pipeline",
            label="图片视频生成流水线",
            max_score=8,
            score=4 if _truthy(providers.get("media_fal", {}).get("configured")) else 2 if "media.fal_asset_generation" in provider_job_keys else 1,
            status="provider_configured" if _truthy(providers.get("media_fal", {}).get("configured")) else "contract_only",
            evidence=[
                f"FAL configured={providers.get('media_fal', {}).get('configured')}",
                "素材 Agent 可以接收 manifest；媒体生成已有队列作业合同，并把素材结果写回报告正文。",
            ],
            remaining=["还要做真实生成队列、费用控制、失败重试、版权/肖像/商品事实校验、视频质量验收。"],
        ),
        _dimension(
            key="long_term_memory",
            label="长期记忆与经验沉淀",
            max_score=8,
            score=3 if int(memory.get("record_count") or 0) > 0 else 2,
            status="local_memory_ready" if int(memory.get("record_count") or 0) > 0 else "empty_ready",
            evidence=[
                f"本地长期记忆记录数：{memory.get('record_count', 0)}。",
                "敏感凭证、买家隐私和执行权限不进入长期记忆。",
            ],
            remaining=["生产替代需要按商家/店铺/商品/岗位检索记忆，并把失败经验自动沉淀成可审阅规则。"],
        ),
        _dimension(
            key="queue_retry_and_observability",
            label="队列、重试、超时和可观测性",
            max_score=8,
            score=3 if provider_job_contracts.get("contract_count", 0) >= 6 else 2,
            status="provider_job_contract_ready" if provider_job_contracts.get("contract_count", 0) >= 6 else "local_queue_only",
            evidence=[
                "本地 TaskQueue、timeout_seconds、retry_policy 和 ToolOrchestrator 超时记录已经存在。",
                f"{provider_job_contracts.get('contract_count', 0)} 个 Provider 作业合同已定义队列、超时、重试和商家可见失败。",
            ],
            remaining=["正式替代需要 Redis/Postgres/云队列、任务状态轮询、死信队列、重试策略和操作员告警。"],
        ),
        _dimension(
            key="confirmation_and_execution_boundary",
            label="确认中心与执行边界",
            max_score=8,
            score=4 if confirmations else 3,
            status="safe_boundary_ready",
            evidence=[
                f"最近一次确认项：{len(confirmations)}。",
                "真实发布、退款、付款、广告、政策修改仍被拦截。",
            ],
            remaining=["还要接正式 ExecutionService、审计日志、二次确认、权限检查和真实平台回滚/失败处理。"],
        ),
        _dimension(
            key="production_saas_backend",
            label="正式 SaaS 后端与多租户",
            max_score=10,
            score=1,
            status="local_api_only",
            evidence=["当前是本地 API + SQLite + 高保真前端演示。"],
            remaining=["还没有正式登录、公司/店铺数据隔离、Vault、云数据库、云部署、计费和生产运维。"],
        ),
    ]

    total = sum(item["score"] for item in dimensions)
    max_total = sum(item["max_score"] for item in dimensions)
    percent = round(total / max(1, max_total) * 100)
    hard_blockers = [
        "真实 1688/货源读取和橙联/SpeedPAK 报价还没有稳定生产适配器。",
        "图片视频真实生成还没有稳定队列、费用控制和商用验收。",
        "自研 Agent 还没有连续同题多轮证明质量不低于 Hermes。",
        "正式 SaaS 后端、多租户权限、Vault、云队列和审计运维还没有生产化。",
        "真实 eBay 写入仍必须通过确认中心和 ExecutionService，不能由 Agent 直接执行。",
    ]
    return {
        "readiness_version": READINESS_VERSION,
        "mode": "production_replacement_readiness",
        "production_replacement_percent": percent,
        "local_low_risk_takeover_percent": _local_low_risk_takeover_percent(dimensions, providers, owned),
        "can_replace_hermes_in_production": False,
        "recommended_current_position": "Jiejing Runtime is the default independent worker for local and low-risk SaaS workflows. Production-grade live provider replacement is still blocked by real adapters, cloud queue, Vault/KMS, and validation.",
        "dimensions": dimensions,
        "hard_blockers": hard_blockers,
        "next_three_engineering_moves": [
            "Make same-topic independent Agent quality scoring a required smoke-test gate.",
            "Turn search/eBay/sourcing/logistics/media providers into retryable tool jobs with source records.",
            "Add a cloud-ready backend queue contract before any real multi-user SaaS deployment.",
        ],
        "secret_exposed": False,
    }


def _latest_context(repo: RuntimeRepositoryView | None) -> dict[str, Any]:
    if repo is None:
        return {"run": {}, "results": [], "confirmations": [], "validation_summary": {}, "snapshot": {}}
    runs = repo.list_runs()
    if not runs:
        return {"run": {}, "results": [], "confirmations": [], "validation_summary": {}, "snapshot": {}}
    run_id = str(runs[0].get("run_id") or "")
    run = repo.get_run(run_id) or runs[0]
    results = repo.get_results(run_id)
    confirmations = repo.get_confirmations(run_id)
    validation_summary = repo.get_validation_summary(run_id)
    snapshot = build_saas_snapshot(run, results, confirmations, validation_summary)
    return {
        "run": run,
        "results": results,
        "confirmations": confirmations,
        "validation_summary": validation_summary,
        "snapshot": snapshot,
    }


def _dimension(
    *,
    key: str,
    label: str,
    max_score: int,
    score: int,
    status: str,
    evidence: list[str],
    remaining: list[str],
) -> dict[str, Any]:
    score = max(0, min(max_score, int(score)))
    return {
        "key": key,
        "label": label,
        "score": score,
        "max_score": max_score,
        "percent": round(score / max(1, max_score) * 100),
        "status": status,
        "evidence": evidence,
        "remaining": remaining,
    }


def _ready(capability_by_key: dict[str, dict[str, Any]], key: str) -> bool:
    item = capability_by_key.get(key) or {}
    return str(item.get("status") or "") in {"ready", "configured", "credential_ready", "local_ready", "ready_contract", "empty_ready"}


def _model_score(model_status: dict[str, Any], executions: list[dict[str, Any]]) -> int:
    live_count = _live_model_count(executions)
    if live_count >= 4:
        return 5
    if live_count:
        return 4
    if model_status.get("configured"):
        return 2
    return 1


def _live_model_count(executions: list[dict[str, Any]]) -> int:
    return len([item for item in executions if item.get("uses_live_model")])


def _ebay_ready(status: dict[str, Any]) -> bool:
    if not isinstance(status, dict):
        return False
    token_ready = str(status.get("access_token_status") or "").lower() in {"ready", "valid", "fresh"}
    return bool(status.get("credential_present")) and (token_ready or status.get("refresh_required") is False)


def _local_low_risk_takeover_percent(dimensions: list[dict[str, Any]], providers: dict[str, Any], owned: dict[str, Any]) -> int:
    base = 48
    base += min(14, int(owned.get("role_count") or 0) * 2)
    base += 8 if _truthy(providers.get("public_search_tavily", {}).get("configured")) else 0
    base += 8 if _truthy(providers.get("media_fal", {}).get("configured")) else 0
    base += 8 if _ebay_ready(providers.get("ebay", {})) else 0
    base += min(14, sum(1 for item in dimensions if item["score"] >= item["max_score"] * 0.6))
    return min(82, base)


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on", "ready", "configured"}
