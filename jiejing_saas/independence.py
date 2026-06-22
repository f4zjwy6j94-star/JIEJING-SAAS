"""Independent Jiejing SaaS status.

This is the top-level view for running Jiejing without Hermes as a required
dependency. It separates what the self-owned SaaS/Runtime already controls from
what is still a blocker before real merchants and real platform writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jiejing_runtime.agent_provider_plan import build_agent_provider_execution_plan
from jiejing_runtime.media_generation import MediaGenerationAdapter
from jiejing_runtime.model_clients import model_client_status_from_env
from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog
from jiejing_runtime.public_search import PublicSearchProbeAdapter
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

from .config import SaaSSettings
from .ebay_write_adapter import build_ebay_write_adapter_contract
from .repository import SaaSRepository


def build_independence_status(
    *,
    settings: SaaSSettings,
    repository: SaaSRepository,
    project_root: Path,
) -> dict[str, Any]:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="independence status sample",
            merchant_goal="Check that Jiejing can run without Hermes.",
            project_id="independence-status",
            source_mode="manual_or_1688",
        )
    )
    provider_catalog = build_provider_job_contract_catalog()
    agent_provider_plan = build_agent_provider_execution_plan(tasks)
    counts = repository.system_counts()
    deploy_files = _deployment_files(project_root)
    model_status = model_client_status_from_env()
    search_status = PublicSearchProbeAdapter().provider_status("tavily")
    media_status = MediaGenerationAdapter().provider_status("fal")
    ebay_write = build_ebay_write_adapter_contract(settings)

    issue_cards = [
        _card(
            key="production_deployment",
            label="正式云端部署",
            status="skeleton_ready" if all(item["exists"] for item in deploy_files) else "missing_deploy_skeleton",
            solved=[
                "已准备独立 SaaS 后端启动方式、容器骨架、环境变量样例和部署说明。",
                "后端启动时会拒绝不安全生产配置，不会把本地 SQLite/本地队列伪装成生产系统。",
            ],
            unresolved=[
                "还没有真正部署到腾讯云或阿里云公网环境。",
                "Postgres、Redis、KMS 的生产驱动仍是合同层，未完成云端实连。",
            ],
            next_action="先跑 staging 容器和 readiness，不直接开放真实商家。",
        ),
        _card(
            key="ebay_real_write",
            label="真实 eBay 写入",
            status="confirmation_gated_contract_ready",
            solved=[
                "发布、改价、改库存、退款、广告和政策修改已经进入 ExecutionService 与确认中心边界。",
                "执行服务已有预检、幂等键、payload hash 和重复执行防护。",
            ],
            unresolved=[
                "真实 eBay 写入 HTTP adapter 仍未实现。",
                "上线前必须先跑 Sandbox 或小范围人工确认写入测试。",
            ],
            next_action="先完成 eBay 只读真实读取、政策读取和类目校验，再做 publish_listing sandbox adapter。",
        ),
        _card(
            key="ebay_credentials",
            label="eBay 凭证闭环",
            status="contract_ready" if settings.ebay_client_id and settings.ebay_ru_name else "blocked_missing_oauth_config",
            solved=[
                "OAuth 计划、token refresh 计划、只读数据包、access token 不进前端/Runtime 的边界已经存在。",
                "自研 SaaS 不再依赖 Hermes 保存 eBay 凭证，只认后端 Vault/KMS 和 secret_ref。",
            ],
            unresolved=[
                "当前配置未证明完整 eBay client_id / RuName / client_secret / refresh token 已由 SaaS 后端接管。",
                "本地 secret_ref_only 模式不会读取真实 refresh token。",
            ],
            next_action="把 eBay app 凭证和 seller refresh token 写入云端 KMS/Vault，并启用后端 token refresh。",
        ),
        _card(
            key="sourcing_logistics",
            label="1688 / 货源 / 物流",
            status="provider_contract_ready",
            solved=[
                "1688 货源、手动链接、物流报价都已进入 Provider Job 合同，能显示缺资料、超时和失败。",
                "采购下单、付款、地址写入、tracking 写入仍被确认中心拦截。",
            ],
            unresolved=[
                "1688 授权读取、供应商筛选、真实库存/价格/发货地读取还没生产化。",
                "橙联/SpeedPAK 实时报价和买标未接生产 adapter。",
            ],
            next_action="先做只读货源候选和物流报价 adapter，不做自动付款。",
        ),
        _card(
            key="media_generation",
            label="图片视频生成",
            status="provider_configured" if media_status.get("configured") else "contract_ready_provider_pending",
            solved=[
                "素材生成已变成 Provider Job，可接 FAL/媒体 provider、manifest、费用和失败状态。",
                "素材 Agent 可以把图片、详情页、视频结果写回报告，不再只放静态演示图。",
            ],
            unresolved=[
                "还没有生产级媒体队列、成本上限、商用验收、版权和商品事实检查。",
                "如果媒体 provider 没配置，系统只能生成任务包，不能生成真实素材。",
            ],
            next_action="把媒体生成改成独立队列：限额、失败重试、人工验收，再回写 Listing。",
        ),
        _card(
            key="owned_agents",
            label="自研 Agent 团队",
            status="independent_runtime_ready" if not settings.allow_hermes_adapters else "hermes_adapter_allowed",
            solved=[
                "默认只允许 mock、jiejing-local、jiejing-llm、jiejing-deepseek，不再允许 Hermes adapter。",
                "7 个自研岗位、报告合同、质量门、Provider Job 映射和长期记忆边界已经具备。",
            ],
            unresolved=[
                "自研 Agent 质量还需要用大量真实商品持续验证。",
                "还没把所有真实工具稳定接进自研 Agent。",
            ],
            next_action="继续用真实商品跑同流程测试，低风险任务逐步由自研 Runtime 独立承担。",
        ),
        _card(
            key="frontend_runtime_data",
            label="前端与 Runtime 实时数据",
            status="partially_dynamic",
            solved=[
                "前端已能读取后端 readiness、任务、队列、报告、确认、Provider 预检、密钥授权和执行状态。",
                "工作台已经开始从静态演示转向 SaaS 后端状态驱动。",
            ],
            unresolved=[
                "部分官网/工作流内容仍是高保真演示数据，不是每个模块都完全由 Runtime 实时结果生成。",
                "批量铺货、素材、刊登等模块还需要更深的数据绑定。",
            ],
            next_action="把每个模块的核心卡片改成读取 task/report/provider 输出，而不是只读前端常量。",
        ),
    ]
    return {
        "status_version": "2026-05-15-independent-jiejing",
        "product": "Jiejing SaaS",
        "goal": "Run Jiejing without Hermes as a required dependency.",
        "runtime_independent_from_hermes": not settings.allow_hermes_adapters,
        "hermes_adapters_allowed": settings.allow_hermes_adapters,
        "current_position": "Jiejing-owned Runtime is the default execution path. Hermes is not required for local SaaS workflow execution.",
        "issue_count": len(issue_cards),
        "solved_count": len([item for item in issue_cards if item["status"] not in {"missing_deploy_skeleton", "blocked_missing_oauth_config"}]),
        "blocking_count": len([item for item in issue_cards if item["status"].startswith("blocked") or item["status"].startswith("missing")]),
        "issue_cards": issue_cards,
        "provider_summary": {
            "provider_job_count": provider_catalog.get("contract_count"),
            "provider_families": provider_catalog.get("provider_families", []),
            "agent_provider_job_count": agent_provider_plan.get("provider_job_count"),
            "model_configured": bool(model_status.get("configured")),
            "search_configured": bool(search_status.get("configured")),
            "media_configured": bool(media_status.get("configured")),
            "ebay_write_enabled": bool(ebay_write.get("enabled")),
            "real_platform_writes_enabled": False,
        },
        "deployment_files": deploy_files,
        "counts": counts,
        "rules": {
            "frontend_never_calls_hermes": True,
            "saas_backend_owns_runtime_dispatch": True,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "agents_cannot_execute_platform_writes": True,
            "high_risk_actions_require_confirmation": True,
        },
        "next_order": [
            "云端 staging 部署骨架跑通",
            "Vault/KMS 接真实 secret_ref",
            "eBay 只读真实读取",
            "Provider Jobs 接搜索/1688/物流/媒体真实 adapter",
            "前端模块读取 Runtime 输出",
            "eBay sandbox 写入",
            "小范围真实发布确认测试",
        ],
        "secret_exposed": False,
    }


def _card(
    *,
    key: str,
    label: str,
    status: str,
    solved: list[str],
    unresolved: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "solved": solved,
        "unresolved": unresolved,
        "next_action": next_action,
        "secret_exposed": False,
    }


def _deployment_files(project_root: Path) -> list[dict[str, Any]]:
    files = [
        "Dockerfile.saas",
        "deploy/jiejing-saas.env.example",
        "deploy/docker-compose.staging.yml",
        "docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md",
    ]
    return [{"path": file, "exists": (project_root / file).exists()} for file in files]
