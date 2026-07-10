"""Controlled-staging security gate for Jiejing SaaS.

This gate is intentionally narrower than paid-production readiness. It answers
one question for the current phase: can a merchant safely run the real staging
test loop without tenant leakage, raw-secret exposure, simulated merchant data,
or real platform writes?
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import SaaSSettings
from .model_provider_catalog import public_model_settings_from_secret_refs
from .repository import SaaSRepository


CONTROLLED_STAGING_VERSION = "2026-05-20-controlled-staging-security"

REQUIRED_TENANT_TABLES = {
    "stores": ("company_id",),
    "team_members": ("company_id", "user_id"),
    "secret_refs": ("company_id",),
    "platform_connections": ("company_id", "store_id"),
    "oauth_authorization_requests": ("company_id", "store_id"),
    "platform_data_packets": ("company_id", "store_id"),
    "tasks": ("company_id", "store_id"),
    "queue_jobs": ("company_id",),
    "task_steps": ("company_id", "store_id"),
    "confirmations": ("company_id", "store_id"),
    "merchant_memory": ("company_id",),
    "audit_logs": ("company_id",),
}

STORE_SCOPED_SECRET_PURPOSES = {
    "ebay_refresh_token",
    "public_search_api_key",
    "media_generation_api_key",
    "sourcing_api_secret",
    "logistics_api_secret",
    "storefront_api_secret",
}

DANGEROUS_SECRET_KEYS = {
    "access_token",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "refresh_token",
    "secret_value",
    "token",
}

DANGEROUS_SECRET_KEY_SUFFIXES = ("_api_key", "api_key", "apikey")

LEGACY_REAL_MODE_MARKERS = (
    "测试草稿",
    "倒流香炉",
    "Backflow Incense",
    "旅行压缩收纳袋",
)

MERCHANT_REAL_SCOPE_FUNCTIONS = (
    "renderSaasProductListingCenter",
    "renderSaasMerchantWorkbenchPanel",
    "renderSaasMerchantTruthPanel",
    "renderGlobalLoopWorkbench",
)


def build_controlled_staging_security_gate(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    project_root: Path | None = None,
    company_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    counts = repository.system_counts()
    secret_refs = repository.list_secret_refs(company_id=company_id, store_id=store_id) if company_id else []
    data_packets = (
        repository.list_platform_data_packets(company_id=company_id, store_id=store_id, platform="ebay", limit=5)
        if company_id and store_id
        else []
    )
    model_settings = public_model_settings_from_secret_refs(secret_refs) if secret_refs else {}

    checks = [
        _environment_check(settings),
        _session_secret_check(settings),
        _demo_session_check(settings),
        _real_write_check(settings),
        _tenant_schema_check(repository),
        _store_scoped_secret_ref_check(secret_refs),
        _database_secret_scan_check(repository),
        _model_key_boundary_check(model_settings),
        _packet_boundary_check(data_packets),
        _audit_memory_check(counts, company_id=company_id, store_id=store_id),
        _merchant_surface_check(project_root),
    ]
    blockers = [check for check in checks if check["severity"] == "blocker" and check["status"] != "ready"]
    warnings = [check for check in checks if check["severity"] == "warning" and check["status"] != "ready"]
    controlled_ready = not blockers
    return {
        "gate": "controlled_staging_security",
        "version": CONTROLLED_STAGING_VERSION,
        "environment": settings.environment,
        "status": "ready_for_controlled_staging_test" if controlled_ready else "blocked",
        "controlled_staging_test_ready": controlled_ready,
        "production_grade_saas_security": False,
        "can_accept_real_customers": False,
        "real_platform_writes_enabled": settings.effective_real_platform_writes_enabled,
        "requested_real_platform_writes": settings.requested_real_platform_writes,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "checks": checks,
        "scope": {
            "company_id": company_id or None,
            "store_id": store_id or None,
            "store_scoped": bool(company_id and store_id),
        },
        "evidence": {
            "counts": counts,
            "model_configured": bool(model_settings.get("configured")) if model_settings else False,
            "model_mode": model_settings.get("mode") if model_settings else "not_loaded",
            "latest_packet_id": data_packets[0].get("packet_id") if data_packets else "",
            "latest_packet_source_mode": data_packets[0].get("source_mode") if data_packets else "",
        },
        "next_allowed_test_loop": [
            "merchant_login",
            "verify_official_ebay_packet",
            "save_byok_model_secret_ref",
            "run_model_backed_market_report",
            "run_model_backed_listing_package",
            "review_confirmation_center",
        ],
        "blocked_actions": [
            "auto_publish_listing",
            "change_price_or_inventory",
            "send_customer_reply",
            "refund_or_payment",
            "raw_secret_to_frontend",
            "cross_tenant_data_access",
        ],
        "secret_exposed": False,
    }


def _environment_check(settings: SaaSSettings) -> dict[str, Any]:
    if settings.environment in {"staging", "local_dev", "test"}:
        return _check(
            "environment",
            "受控测试环境",
            "ready",
            "info",
            f"当前环境是 {settings.environment}；允许受控测试，但不声明生产级 SaaS。",
            "真实商家公开收费前再切 production 并过付费基础设施门禁。",
        )
    if settings.environment == "production":
        return _check(
            "environment",
            "受控测试环境",
            "production_requires_full_gate",
            "blocker",
            "当前环境是 production，不能只按 staging 安全底线放行。",
            "改回 staging 做测试，或先完成生产级 Postgres/Vault/KMS/WAF/备份/监控门禁。",
        )
    return _check(
        "environment",
        "受控测试环境",
        "unknown_environment",
        "warning",
        f"未知环境 {settings.environment}，按非生产保守处理。",
        "明确设置 JIEJING_SAAS_ENV=staging。",
    )


def _session_secret_check(settings: SaaSSettings) -> dict[str, Any]:
    if settings.is_production_like and (not settings.session_secret_configured or settings.session_secret_is_default):
        return _check(
            "session_secret",
            "登录会话签名",
            "blocked_default_or_missing_session_secret",
            "blocker",
            "生产相近环境不能使用默认 session secret，否则 bearer token 签名边界不可靠。",
            "配置足够长的 JIEJING_SAAS_SESSION_SECRET 后重启后端。",
        )
    return _check(
        "session_secret",
        "登录会话签名",
        "ready",
        "info",
        "会话 token 使用后端签名；当前环境没有使用默认生产相近密钥。",
        "上线前接入托管身份、MFA 和短会话策略。",
    )


def _demo_session_check(settings: SaaSSettings) -> dict[str, Any]:
    enabled = _env_bool("JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP", default=False)
    if settings.is_production_like and enabled:
        return _check(
            "demo_session",
            "demo-session 入口",
            "blocked_demo_session_enabled",
            "blocker",
            "staging/production 页面不能自动创建 demo-session。",
            "设置 JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP=false 并重启后端。",
        )
    return _check(
        "demo_session",
        "demo-session 入口",
        "ready",
        "info",
        "demo-session 没有在生产相近环境公开启用。",
        "保留真实注册登录路径做测试。",
    )


def _real_write_check(settings: SaaSSettings) -> dict[str, Any]:
    if settings.requested_real_platform_writes or settings.effective_real_platform_writes_enabled:
        return _check(
            "real_platform_writes",
            "真实平台写入",
            "blocked_real_write_requested",
            "blocker",
            "当前阶段不能启用真实发布、改价、改库存、退款、广告或采购付款。",
            "保持 JIEJING_ENABLE_REAL_PLATFORM_WRITES=false。",
        )
    return _check(
        "real_platform_writes",
        "真实平台写入",
        "ready",
        "info",
        "真实平台写入关闭；执行服务仍是 demo_no_platform_write。",
        "只允许只读 packet、报告、Listing Package 和确认中心输出。",
    )


def _tenant_schema_check(repository: SaaSRepository) -> dict[str, Any]:
    columns_by_table = _columns_by_table(repository)
    missing: list[str] = []
    for table, required_columns in REQUIRED_TENANT_TABLES.items():
        columns = columns_by_table.get(table, set())
        for column in required_columns:
            if column not in columns:
                missing.append(f"{table}.{column}")
    if missing:
        return _check(
            "tenant_schema",
            "账号/店铺隔离字段",
            "blocked_missing_tenant_columns",
            "blocker",
            "关键数据表缺少租户隔离字段：" + ", ".join(missing[:8]),
            "补齐 company_id/store_id 字段和查询过滤后再继续测试。",
        )
    return _check(
        "tenant_schema",
        "账号/店铺隔离字段",
        "ready",
        "info",
        "关键账号、店铺、secret_ref、packet、任务、报告、确认、记忆和审计表都带租户边界。",
        "继续用 API 级回归测试防止跨账号读取。",
    )


def _store_scoped_secret_ref_check(secret_refs: list[dict[str, Any]]) -> dict[str, Any]:
    if not secret_refs:
        return _check(
            "secret_ref_scope",
            "密钥引用归属",
            "not_configured_yet",
            "warning",
            "当前账号还没有加载店铺级 secret_ref；保存 BYOK 或 eBay 授权后会重新检查。",
            "真实测试时先保存 BYOK key 或读取 eBay official packet。",
        )
    missing_store = [
        item.get("secret_ref")
        for item in secret_refs
        if str(item.get("purpose") or "") in STORE_SCOPED_SECRET_PURPOSES and not item.get("store_id")
    ]
    if missing_store:
        return _check(
            "secret_ref_scope",
            "密钥引用归属",
            "blocked_store_scope_missing",
            "blocker",
            "店铺级密钥引用缺少 store_id：" + ", ".join(str(item) for item in missing_store[:5]),
            "重新写入 secret_ref，确保 company_id/store_id/provider/purpose 都在同一条记录。",
        )
    return _check(
        "secret_ref_scope",
        "密钥引用归属",
        "ready",
        "info",
        "当前加载的 eBay/BYOK secret_ref 都按账号和店铺归属。",
        "继续保持前端只显示 secret_ref 状态，不回显原始 key。",
    )


def _database_secret_scan_check(repository: SaaSRepository) -> dict[str, Any]:
    scan = _scan_sqlite_for_raw_secret_values(repository)
    if scan["status"] == "not_supported":
        return _check(
            "database_secret_scan",
            "数据库明文密钥扫描",
            "not_supported_for_engine",
            "warning",
            "当前数据库引擎不支持本地扫描；只依据 API 合同检查 secret_ref 边界。",
            "Postgres cutover 后补 SQL 级扫描或只读审计视图。",
        )
    if scan["findings"]:
        return _check(
            "database_secret_scan",
            "数据库明文密钥扫描",
            "blocked_raw_secret_like_value_found",
            "blocker",
            "数据库 JSON 字段疑似保存了明文密钥：" + "; ".join(scan["findings"][:5]),
            "删除明文值，改为 secret_ref + 外部 Vault/KMS 存储。",
        )
    return _check(
        "database_secret_scan",
        "数据库明文密钥扫描",
        "ready",
        "info",
        f"已扫描 {scan['record_count']} 条数据库 JSON/metadata 记录，未发现危险明文密钥字段。",
        "继续禁止 access_token/refresh_token/client_secret/api_key 进入报告、记忆或审计。",
    )


def _model_key_boundary_check(model_settings: dict[str, Any]) -> dict[str, Any]:
    if not model_settings or model_settings.get("configured") is not True:
        return _check(
            "byok_model_key_boundary",
            "BYOK 模型密钥边界",
            "not_configured_yet",
            "warning",
            "当前店铺还没有加载 BYOK 模型配置。",
            "保存商家模型 key 后确认只返回 secret_ref 和 provider/model 状态。",
        )
    if (
        model_settings.get("frontend_gets_raw_key_after_save") is False
        and model_settings.get("runtime_gets_raw_key") is False
        and model_settings.get("reports_get_raw_key") is False
    ):
        return _check(
            "byok_model_key_boundary",
            "BYOK 模型密钥边界",
            "ready",
            "info",
            "BYOK 设置只返回 secret_ref/provider/model 状态；前端、Runtime、报告都不拿原始 key。",
            "继续用后端模型客户端解析 secret_ref。",
        )
    return _check(
        "byok_model_key_boundary",
        "BYOK 模型密钥边界",
        "blocked_raw_model_key_boundary",
        "blocker",
        "BYOK 公共设置没有明确关闭原始 key 回显。",
        "修正 model settings 输出，禁止前端、Runtime、报告拿原始模型 key。",
    )


def _packet_boundary_check(data_packets: list[dict[str, Any]]) -> dict[str, Any]:
    if not data_packets:
        return _check(
            "official_packet_boundary",
            "eBay 标准数据包",
            "not_loaded_yet",
            "warning",
            "当前店铺没有加载 eBay packet；安全门禁先检查代码边界。",
            "真实测试时读取 official eBay packet 后再跑 Market Report 和 Listing Package。",
        )
    latest = data_packets[0]
    packet = latest.get("packet") if isinstance(latest.get("packet"), dict) else {}
    if latest.get("source_mode") != "official_api" and packet.get("source_label") != "official_api":
        return _check(
            "official_packet_boundary",
            "eBay 标准数据包",
            "blocked_non_official_packet",
            "blocker",
            "当前最新 packet 不是 official_api 来源，真实测试不能靠本地样例补空白。",
            "先确认 eBay 只读授权和 official packet。",
        )
    if packet.get("secret_exposed") is True or packet.get("safe_for_real_platform_write") is not False:
        return _check(
            "official_packet_boundary",
            "eBay 标准数据包",
            "blocked_packet_boundary",
            "blocker",
            "最新 packet 没有保持 secret_exposed=false 且 safe_for_real_platform_write=false。",
            "重新生成标准数据包，只交清洗后的只读数据给 Runtime。",
        )
    return _check(
        "official_packet_boundary",
        "eBay 标准数据包",
        "ready",
        "info",
        f"最新 packet {latest.get('packet_id') or '-'} 来自 official_api，且标记为不可真实写入。",
        "用它跑 live model-backed Market Report + Listing Package。",
    )


def _audit_memory_check(counts: dict[str, int], *, company_id: str | None, store_id: str | None) -> dict[str, Any]:
    if not company_id:
        return _check(
            "audit_memory",
            "审计和商家记忆",
            "not_store_scoped",
            "warning",
            "未传入账号/店铺范围，只能检查全局表结构。",
            "登录后从店铺设置页查看 store-scoped 安全总闸。",
        )
    if counts.get("audit_logs", 0) < 1:
        return _check(
            "audit_memory",
            "审计和商家记忆",
            "audit_not_started",
            "warning",
            "当前账号还没有审计日志；注册、建店、保存密钥、跑任务后应写入审计。",
            "跑一遍真实测试链路并刷新审计。",
        )
    return _check(
        "audit_memory",
        "审计和商家记忆",
        "ready",
        "info",
        "审计表已开始记录账号操作；Merchant Memory 也走 company_id/store_id 边界。",
        "继续把报告、确认、模型输出沉淀为账号独立记忆。",
    )


def _merchant_surface_check(project_root: Path | None) -> dict[str, Any]:
    if not project_root:
        return _check(
            "merchant_surface_real_mode",
            "真实模式页面",
            "not_checked",
            "warning",
            "未提供项目目录，无法静态检查前端真实模式是否混入样例商品。",
            "部署前运行 merchant surface guard。",
        )
    app_js = project_root / "app.js"
    if not app_js.exists():
        return _check(
            "merchant_surface_real_mode",
            "真实模式页面",
            "not_checked",
            "warning",
            "找不到 app.js，跳过前端真实模式扫描。",
            "确认部署包包含最新前端。",
        )
    source = app_js.read_text(encoding="utf-8")
    findings = []
    for function_name in MERCHANT_REAL_SCOPE_FUNCTIONS:
        scope = _function_scope(source, function_name)
        if not scope:
            continue
        for marker in LEGACY_REAL_MODE_MARKERS:
            if marker in scope:
                findings.append(f"{function_name}:{marker}")
    if findings:
        return _check(
            "merchant_surface_real_mode",
            "真实模式页面",
            "blocked_legacy_sample_visible_in_real_mode",
            "blocker",
            "真实工作台渲染路径仍混入旧样例：" + ", ".join(findings[:5]),
            "把旧样例移到非真实演示路径，真实模式只读后端 packet/report/confirmation。",
        )
    return _check(
        "merchant_surface_real_mode",
        "真实模式页面",
        "ready",
        "info",
        "真实 Listing/工作台渲染路径没有发现旧测试草稿或倒流香炉样例。",
        "继续用静态 guard 防止回归。",
    )


def _check(key: str, label: str, status: str, severity: str, detail: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "severity": severity,
        "detail": detail,
        "next_action": next_action,
        "secret_exposed": False,
    }


def _columns_by_table(repository: SaaSRepository) -> dict[str, set[str]]:
    columns: dict[str, set[str]] = {}
    try:
        repository.initialize()
        with repository._connect() as conn:  # package-local inspection; no mutation.
            if repository.database_engine == "postgres":
                rows = conn.execute(
                    """
                    select table_name, column_name
                    from information_schema.columns
                    where table_schema = 'public'
                    order by table_name, ordinal_position
                    """
                ).fetchall()
                for row in rows:
                    table = str(row["table_name"])
                    columns.setdefault(table, set()).add(str(row["column_name"]))
                return columns
            rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
            for row in rows:
                table = str(row["name"])
                columns[table] = {str(item["name"]) for item in conn.execute(f"pragma table_info({table})").fetchall()}
    except Exception:
        return {}
    return columns


def _scan_sqlite_for_raw_secret_values(repository: SaaSRepository) -> dict[str, Any]:
    targets = {
        "secret_refs": ("metadata_json",),
        "platform_connections": ("metadata_json",),
        "oauth_authorization_requests": ("request_json",),
        "platform_data_packets": ("packet_json",),
        "tasks": ("input_json", "output_json"),
        "queue_jobs": ("job_json",),
        "task_steps": ("step_json",),
        "reports": ("report_json",),
        "confirmations": ("item_json",),
        "merchant_memory": ("memory_json",),
        "execution_results": ("result_json",),
        "audit_logs": ("audit_json",),
    }
    findings: list[str] = []
    record_count = 0
    try:
        repository.initialize()
        with repository._connect() as conn:  # package-local inspection; no mutation.
            columns_by_table = _columns_by_table(repository)
            for table, columns in targets.items():
                existing = columns_by_table.get(table, set())
                selected = [column for column in columns if column in existing]
                if not selected:
                    continue
                rows = conn.execute(f"select {', '.join(selected)} from {table}").fetchall()
                for row in rows:
                    for column in selected:
                        raw = row[column]
                        if raw in (None, ""):
                            continue
                        record_count += 1
                        try:
                            value = json.loads(raw)
                        except Exception:
                            value = raw
                        findings.extend(f"{table}.{column}.{item}" for item in _find_raw_secret_values(value))
    except Exception as exc:
        return {"status": "scan_failed", "findings": [f"scan_failed:{exc.__class__.__name__}"], "record_count": record_count}
    return {"status": "scanned", "findings": sorted(set(findings)), "record_count": record_count}


def _find_raw_secret_values(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _dangerous_secret_key(key_text) and _looks_like_raw_secret_value(item):
                findings.append(child_path)
            findings.extend(_find_raw_secret_values(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_raw_secret_values(item, f"{path}[{index}]"))
    return findings


def _dangerous_secret_key(key: str) -> bool:
    lower = key.lower()
    if lower in {"secret_ref", "secret_refs", "secret_exposed", "secret_ref_only"}:
        return False
    if lower in DANGEROUS_SECRET_KEYS:
        return True
    return any(lower.endswith(suffix) for suffix in DANGEROUS_SECRET_KEY_SUFFIXES)


def _looks_like_raw_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text in {"[REDACTED]", "***", "redacted", "true", "false"}:
        return False
    if text.startswith("secret_") or text.startswith("ref_"):
        return False
    if len(text) < 8:
        return False
    return True


def _function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        return ""
    next_start = source.find("\nfunction ", start + len(marker))
    return source[start:] if next_start < 0 else source[start:next_start]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
