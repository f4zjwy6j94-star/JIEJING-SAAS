"""Evidence-based progress scorecard for Jiejing Runtime.

The user-facing product can say "the loop is ready" only when local evidence
says so. This module keeps percentages tied to actual capabilities, latest
workflow output, provider readiness, and safety gates.
"""

from __future__ import annotations

from typing import Any, Protocol

from .agent_team import JiejingAgentTeam
from .capabilities import RuntimeCapabilityProfile
from .model_clients import model_client_status_from_env
from .owned_agents import OwnedAgentExecutor
from .replacement_readiness import build_replacement_readiness
from .saas_snapshot import build_saas_snapshot
from .tools_registry import ToolRegistry


SCORECARD_VERSION = "2026-05-15.2"
STANDARD_ROLE_COUNT = 7


class RuntimeRepositoryView(Protocol):
    db_path: Any

    def list_runs(self) -> list[dict[str, Any]]: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def get_results(self, run_id: str) -> list[dict[str, Any]]: ...

    def get_confirmations(self, run_id: str) -> list[dict[str, Any]]: ...

    def get_validation_summary(self, run_id: str) -> dict[str, Any]: ...


def build_progress_scorecard(repo: RuntimeRepositoryView | None = None) -> dict[str, Any]:
    """Return a front-end-safe, production-honest project progress scorecard."""

    capability = RuntimeCapabilityProfile(repo.db_path if repo else None).to_dict()
    team = JiejingAgentTeam().to_dict()
    executor = OwnedAgentExecutor().to_dict()
    tools = ToolRegistry().list_tools()
    latest = _latest_run_context(repo)
    provider_status = capability.get("provider_status", {}) if isinstance(capability.get("provider_status"), dict) else {}
    model_status = model_client_status_from_env()
    replacement_readiness = build_replacement_readiness(repo)

    context = {
        "capability": capability,
        "team": team,
        "executor": executor,
        "tools": tools,
        "latest": latest,
        "provider_status": provider_status,
        "model_status": model_status,
        "replacement_readiness": replacement_readiness,
    }
    tracks = [
        _frontend_demo_track(context),
        _runtime_foundation_track(context),
        _owned_agent_team_track(context),
        _replacement_track(context),
        _saas_mock_integration_track(context),
    ]
    local_demo_average = round(sum(item["percent"] for item in tracks) / max(1, len(tracks)))
    production_average = round(sum(item["production_ceiling_percent"] for item in tracks) / max(1, len(tracks)))
    return {
        "scorecard_version": SCORECARD_VERSION,
        "mode": "local_demo_and_runtime_readiness",
        "tracks": tracks,
        "summary": {
            "local_demo_average_percent": local_demo_average,
            "production_ceiling_percent": production_average,
            "can_claim_demo_closed_loop": _can_claim_demo_closed_loop(tracks),
            "can_claim_production_ready": False,
            "why_not_full_production": [
                "正式 SaaS 还需要云端后端、登录权限、租户隔离、数据库、队列、Vault、审计监控和运维。",
                "真实 eBay 发布、改价、库存、退款、广告、政策修改、采购付款仍必须走确认中心和执行服务。",
                "图片视频生成、1688、橙联和跨平台调研还需要稳定 Provider、费用控制、失败重试和合规边界。",
            ],
        },
        "latest_run": {
            "run_id": latest.get("run", {}).get("run_id", ""),
            "run_status": latest.get("run", {}).get("run_status", ""),
            "task_count": latest.get("run", {}).get("task_count", 0),
            "snapshot_percent": latest.get("snapshot", {}).get("readiness", {}).get("saas_simulation_percent", 0),
        },
        "provider_status": _provider_digest(provider_status),
        "secret_exposed": False,
    }


def _latest_run_context(repo: RuntimeRepositoryView | None) -> dict[str, Any]:
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


def _frontend_demo_track(context: dict[str, Any]) -> dict[str, Any]:
    latest = context["latest"]
    snapshot = latest.get("snapshot", {})
    completion = snapshot.get("completion", {}) if isinstance(snapshot.get("completion"), dict) else {}
    modules = snapshot.get("modules", []) if isinstance(snapshot.get("modules"), list) else []
    readiness = snapshot.get("readiness", {}) if isinstance(snapshot.get("readiness"), dict) else {}
    result_coverage = int(completion.get("result_coverage_percent") or 0)
    ready_modules = int(completion.get("ready_module_count") or 0)
    module_count = int(completion.get("module_count") or 0)
    module_result_count = len([item for item in modules if item.get("has_result")])
    confirmations = len(latest.get("confirmations") or [])
    percent = 58
    if latest.get("run"):
        percent += 12
    percent += min(14, round(result_coverage * 0.14))
    percent += min(10, round((module_result_count / max(1, module_count)) * 10))
    if confirmations:
        percent += 4
    if readiness.get("saas_simulation_percent", 0) >= 90:
        percent += 4
    percent = min(96, percent)
    return _track(
        key="saas_frontend_demo_loop",
        label="SaaS 演示网站 / 前端闭环",
        percent=percent,
        production_ceiling=42,
        status="near_demo_ready" if percent >= 92 else "needs_runtime_run",
        evidence=[
            f"最近一次 Runtime 结果覆盖率 {result_coverage}%。",
            f"{module_result_count}/{module_count} 个前端模块已有 Runtime 结果，其中 {ready_modules} 个可继续或进入确认。",
            "确认中心与执行服务边界已接入演示链路。" if confirmations else "还没有最近一次确认中心样本。",
        ],
        remaining=[
            "把所有静态演示卡片进一步改成优先读取 Runtime 返回。",
            "移动端和浏览器视觉回归还需要自动截图验证。",
        ],
    )


def _runtime_foundation_track(context: dict[str, Any]) -> dict[str, Any]:
    capability = context["capability"]
    knowledge = capability.get("knowledge", {}) if isinstance(capability.get("knowledge"), dict) else {}
    tools = capability.get("tools", {}) if isinstance(capability.get("tools"), dict) else {}
    provider = context["provider_status"]
    capability_items = capability.get("capabilities", [])
    ready_capabilities = [
        item
        for item in capability_items
        if str(item.get("status") or "") in {"ready", "configured", "credential_ready", "local_ready", "ready_contract", "empty_ready"}
    ]
    provider_ready = _configured_provider_count(provider, context.get("model_status", {}))
    percent = 48
    percent += min(14, round(int(knowledge.get("item_count") or 0) / 60 * 14))
    percent += min(10, round(int(tools.get("registered_count") or 0) / 12 * 10))
    percent += min(18, round(len(ready_capabilities) / max(1, len(capability_items) or 1) * 18))
    percent += min(16, provider_ready * 4)
    percent += 8 if capability.get("safe_to_demo") is True and capability.get("safe_to_execute_real_platform_actions") is False else 0
    percent = min(98, percent)
    return _track(
        key="jiejing_runtime_foundation",
        label="捷境 Runtime 底座",
        percent=percent,
        production_ceiling=55,
        status="runtime_local_strong" if percent >= 94 else "runtime_local_partial",
        evidence=[
            f"知识包 {knowledge.get('item_count', 0)} 条，工具注册 {tools.get('registered_count', 0)} 个。",
            f"{len(ready_capabilities)}/{len(capability_items)} 项底座能力为 ready/configured/local_ready。",
            f"{provider_ready}/4 个关键 Provider 已可被后端识别。",
        ],
        remaining=[
            "云端队列、Vault、正式数据库、多租户权限和监控仍未生产化。",
            "真实写入执行服务还只保留安全边界，没有打开生产动作。",
        ],
    )


def _owned_agent_team_track(context: dict[str, Any]) -> dict[str, Any]:
    team = context["team"]
    executor = context["executor"]
    latest = context["latest"]
    validations = latest.get("validation_summary", {}).get("validations", [])
    roles = team.get("roles", []) if isinstance(team.get("roles"), list) else []
    roles_with_inputs = [role for role in roles if role.get("input_requirements") and role.get("stop_conditions")]
    snapshot_owned = latest.get("snapshot", {}).get("owned_agent", {})
    all_owned = bool(snapshot_owned.get("all_results_have_owned_execution"))
    percent = 36
    percent += min(20, round(int(team.get("role_count") or 0) / STANDARD_ROLE_COUNT * 20))
    percent += min(18, round(len(roles_with_inputs) / max(1, len(roles) or 1) * 18))
    percent += min(14, round(int(executor.get("agent_count") or 0) / STANDARD_ROLE_COUNT * 14))
    percent += min(14, round(len(validations) / 6 * 14)) if validations else 0
    percent += 8 if all_owned else 0
    percent = min(94, percent)
    return _track(
        key="owned_7_agent_team",
        label="自研 7 个 Agent 岗位体系",
        percent=percent,
        production_ceiling=48,
        status="role_contract_ready" if percent >= 88 else "role_contract_partial",
        evidence=[
            f"{team.get('role_count', 0)}/7 个岗位合同已加载。",
            f"{len(roles_with_inputs)}/{len(roles)} 个岗位有输入要求和停止条件。",
            f"最近一次链路有 {len(validations)} 条岗位输出校验。",
        ],
        remaining=[
            "每个 Agent 还要继续接稳定真实工具、失败重试和长期记忆检索策略。",
            "需要与 Hermes 同题多轮对跑，沉淀谁的报告更好、哪里要改。",
        ],
    )


def _replacement_track(context: dict[str, Any]) -> dict[str, Any]:
    readiness = context.get("replacement_readiness", {}) if isinstance(context.get("replacement_readiness"), dict) else {}
    percent = int(readiness.get("local_low_risk_takeover_percent") or 0)
    production_percent = int(readiness.get("production_replacement_percent") or 0)
    hard_blockers = readiness.get("hard_blockers") if isinstance(readiness.get("hard_blockers"), list) else []
    next_moves = readiness.get("next_three_engineering_moves") if isinstance(readiness.get("next_three_engineering_moves"), list) else []
    track = _track(
        key="replace_internal_runtime_capability",
        label="自研 Agent 低风险接管能力",
        percent=percent,
        production_ceiling=production_percent,
        status="low_risk_tasks_only" if percent >= 62 else "not_ready_to_replace",
        evidence=[
            "这个百分比只代表本地低风险任务接管，不代表已经生产级替代 Hermes。",
            f"生产级替代评估为 {production_percent}%。",
            *(str(item) for item in hard_blockers[:2]),
        ],
        remaining=hard_blockers[:3] + next_moves[:2],
    )
    track["production_equivalent_percent"] = track["production_ceiling_percent"]
    track["honest_note"] = (
        f"低风险接管约 {percent}%，生产级替代约 {production_percent}%；"
        "现在还必须把 Hermes 当主力执行器。"
    )
    return track


def _saas_mock_integration_track(context: dict[str, Any]) -> dict[str, Any]:
    latest = context["latest"]
    run = latest.get("run", {})
    snapshot = latest.get("snapshot", {})
    provider = context["provider_status"]
    result_coverage = int(snapshot.get("completion", {}).get("result_coverage_percent") or 0)
    validation_count = int(latest.get("validation_summary", {}).get("validation_count") or 0)
    confirmations = len(latest.get("confirmations") or [])
    percent = 54
    if run:
        percent += 12
    percent += min(12, round(result_coverage * 0.12))
    percent += min(10, round(validation_count / 6 * 10)) if validation_count else 0
    percent += 7 if confirmations else 0
    percent += min(10, _configured_provider_count(provider, context.get("model_status", {})) * 3)
    percent = min(96, percent)
    return _track(
        key="saas_mock_runtime_integration",
        label="接入 SaaS 模拟端",
        percent=percent,
        production_ceiling=46,
        status="mock_runtime_connected" if percent >= 90 else "mock_runtime_partial",
        evidence=[
            f"最近一次工作流状态：{run.get('run_status', 'none')}。",
            f"Runtime 结果覆盖率 {result_coverage}%，岗位校验 {validation_count} 条。",
            "SaaS 可读取 Runtime provider、岗位、确认中心和快照。" if run else "还需要从 SaaS 触发一次 Runtime 链路。",
        ],
        remaining=[
            "还有页面模块需要从静态样例改成 Runtime payload 驱动。",
            "正式后端、登录、任务状态轮询和权限隔离还未生产化。",
        ],
    )


def _track(
    *,
    key: str,
    label: str,
    percent: int,
    production_ceiling: int,
    status: str,
    evidence: list[str],
    remaining: list[str],
) -> dict[str, Any]:
    percent = max(0, min(100, int(percent)))
    return {
        "key": key,
        "label": label,
        "percent": percent,
        "status": status,
        "production_ceiling_percent": production_ceiling,
        "evidence": evidence,
        "remaining_to_real_100": remaining,
        "can_mark_100_now": False,
    }


def _configured_provider_count(provider_status: dict[str, Any], model_status: dict[str, Any] | None = None) -> int:
    count = 0
    if _truthy(provider_status.get("public_search_tavily", {}).get("configured")):
        count += 1
    if _truthy(provider_status.get("media_fal", {}).get("configured")):
        count += 1
    if _ebay_ready(provider_status.get("ebay", {})):
        count += 1
    model = model_status or {}
    if isinstance(model, dict) and _truthy(model.get("configured")):
        count += 1
    return count


def _ebay_ready(status: dict[str, Any]) -> bool:
    if not isinstance(status, dict):
        return False
    token_ready = str(status.get("access_token_status") or "").lower() in {"ready", "valid", "fresh"}
    return bool(status.get("credential_present")) and (token_ready or status.get("refresh_required") is False)


def _provider_digest(provider_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "public_search_tavily": _safe_provider(provider_status.get("public_search_tavily", {})),
        "media_fal": _safe_provider(provider_status.get("media_fal", {})),
        "ebay": _safe_provider(provider_status.get("ebay", {})),
    }


def _safe_provider(status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(status, dict):
        return {}
    allowed = [
        "provider",
        "configured",
        "credential_present",
        "credential_source",
        "access_token_status",
        "refresh_required",
        "endpoint_host",
        "image_endpoint_host",
        "video_endpoint_host",
        "source",
        "secret_exposed",
    ]
    return {key: status.get(key) for key in allowed if key in status}


def _can_claim_demo_closed_loop(tracks: list[dict[str, Any]]) -> bool:
    required = {"saas_frontend_demo_loop", "jiejing_runtime_foundation", "owned_7_agent_team", "saas_mock_runtime_integration"}
    by_key = {item["key"]: item for item in tracks}
    return all(by_key.get(key, {}).get("percent", 0) >= 88 for key in required)


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on", "ready", "configured"}
