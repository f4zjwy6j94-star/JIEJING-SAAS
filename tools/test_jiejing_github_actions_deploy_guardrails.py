#!/usr/bin/env python3
"""Validate GitHub self-hosted staging deploy stays manual and data-safe."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-deploy.yml"
ROLLBACK_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-rollback.yml"
DEPLOY_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-deploy.sh"
ROLLBACK_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-rollback.sh"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def main() -> int:
    try:
        deploy_workflow = read(DEPLOY_WORKFLOW)
        rollback_workflow = read(ROLLBACK_WORKFLOW)
        deploy_script = read(DEPLOY_SCRIPT)
        rollback_script = read(ROLLBACK_SCRIPT)
        runbook = read(RUNBOOK)
    except FileNotFoundError as exc:
        return fail(f"missing deploy guardrail file: {exc}")

    required_deploy_workflow = [
        "workflow_dispatch:",
        "deploy_mode:",
        "preflight_only",
        "dry_run",
        "apply",
        "confirm_staging_deploy",
        "deploy app.jiejing.shop staging",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: false",
        "github.ref == 'refs/heads/main'",
        "python tools/jiejing_secret_scan.py",
        "node --check app.js",
        "python tools/test_jiejing_github_actions_deploy_guardrails.py",
        "python tools/jiejing_precloud_deployment_gate.py",
        "runs-on: [self-hosted, jiejing-staging]",
        "Set up Node for frontend syntax check",
        "node-version: \"20\"",
        "JIEJING_DEPLOY_DRY_RUN",
        "JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN: ${{ secrets.JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN }}",
        "JIEJING_EBAY_CLIENT_SECRET: ${{ secrets.JIEJING_EBAY_CLIENT_SECRET }}",
        "bash deploy/github-actions/jiejing-stn��kh��춻�q�^tis wrong: {traffic}")
    daily_trend = traffic.get("daily_trend", [])
    if len(daily_trend) != 30 or daily_trend[-1].get("visitors") != 1 or daily_trend[-1].get("page_views") != 1:
        return fail(f"traffic daily trend is incomplete: {daily_trend}")
    page_breakdown = {item.get("page_key"): item for item in traffic.get("page_breakdown", [])}
    if page_breakdown.get("landing", {}).get("pricing_views") != 1:
        return fail(f"landing traffic breakdown is wrong: {page_breakdown}")
    if page_breakdown.get("register", {}).get("signup_completed") != 1:
        return fail(f"registration funnel breakdown is wrong: {page_breakdown}")
    if traffic.get("automated_browser_collection_enabled") is not False:
        return fail(f"automated browser traffic must be excluded from first-party analytics: {traffic}")
    performance = overview.get("performance_analytics", {})
    if performance.get("sample_count") != 6 or performance.get("page_load", {}).get("p75", {}).get("lcp_ms") != 300:
        return fail(f"performance P75 aggregation is wrong: {performance}")
    settings_performance = performance.get("settings_module", {})
    if settings_performance.get("success_count") != 1 or settings_performance.get("error_count") != 1:
        return fail(f"settings performance aggregation is wrong: {settings_performance}")
    if performance.get("raw_url_stored") is not False or performance.get("prompt_or_response_stored") is not False:
        return fail(f"performance privacy boundary is wrong: {performance}")
    model_cost = overview.get("model_cost_analytics", {})
    if model_cost.get("byok_tokens_are_merchant_billed") is not True or model_cost.get("platform_trial_tokens") != 150:
        return fail(f"model cost boundary is misleading: {model_cost}")
    if overview.get("provider_cost_analytics", {}).get("media_cost_minor") != 34:
        return fail(f"provider cost aggregate is wrong: {overview}")
    reliability = overview.get("provider_reliability_analytics", {})
    if reliability.get("model", {}).get("p75_duration_ms") != 240:
        return fail(f"model reliability aggregate is wrong: {reliability}")
    if reliability.get("public_search", {}).get("timeout_count") != 1:
        return fail(f"public search reliability aggregate is wrong: {reliability}")
    if reliability.get("media_generation", {}).get("success_count") != 1:
        return fail(f"media reliability aggregate is wrong: {reliability}")
    if reliability.get("payment", {}).get("success_count") != 1:
        return fail(f"payment reliability aggregate is wrong: {reliability}")
    if reliability.get("prompts_stored") is not False or reliability.get("raw_errors_stored") is not False:
        return fail(f"provider reliability privacy boundary is wrong: {reliability}")
    reliability_alerts = reliability.get("alerts", {})
    if reliability_alerts.get("status") != "insufficient_data" or reliability_alerts.get("alert_required") is not False:
        return fail(f"low-volume reliability telemetry must not raise a false alert: {reliability_alerts}")
    if reliability_alerts.get("critical_count") != 0 or reliability_alerts.get("attention_count") != 0:
        return fail(f"low-volume reliability alert counters are wrong: {reliability_alerts}")
    if reliability_alerts.get("queries_stored") is not False or reliability_alerts.get("raw_errors_stored") is not False:
        return fail(f"reliability alert privacy boundary is wrong: {reliability_alerts}")
    reliability_lifecycle = reliability.get("lifecycle", {})
    if reliability_lifecycle.get("status") != "ready_no_evaluations":
        return fail(f"GET overview must not advance an unevaluated lifecycle: {reliability_lifecycle}")
    if reliability_lifecycle.get("merchant_navigation_visible") is not False:
        return fail(f"reliability lifecycle must stay internal-only: {reliability_lifecycle}")
    subscriptions = overview.get("subscriptions", [])
    if subscriptions != [{"plan_key": "starter", "status": "active", "count": 1}]:
        return fail(f"commercial subscription aggregate is wrong: {subscriptions}")
    if overview.get("accounts", {}).get("active_merchant_companies") != 1:
        return fail(f"period active merchant aggregate is wrong: {overview.get('accounts')}")
    payments = overview.get("domestic_payments", [])
    if payments != [{"status": "paid", "count": 1, "amount_minor": 9900, "currency": "CNY"}]:
        return fail(f"commercial payment aggregate is wrong: {payments}")
    unit_economics = overview.get("unit_economics", {})
    if (
        unit_economics.get("paid_company_count") != 1
        or unit_economics.get("active_subscriber_company_count") != 1
        or unit_economics.get("normalized_mrr_minor") != 9900
        or unit_economics.get("mrr_status") != "ready"
    ):
        return fail(f"paid-company or MRR aggregate is wrong: {unit_economics}")
    if unit_economics.get("contribution_margin_minor") is not None or unit_economics.get("status") != "partial":
        return fail(f"unknown historical costs must keep contribution margin incomplete: {unit_economics}")
    if (
        unit_economics.get("current_metering_health") != "ready"
        or unit_economics.get("legacy_unmetered_model_tasks") != 1
        or unit_economics.get("current_unmetered_model_tasks") != 0
        or not unit_economics.get("metering_started_at")
    ):
        return fail(f"historical and current model metering are not separated: {unit_economics}")
    data_quality = overview.get("data_quality", {})
    if data_quality.get("synthetic_test_accounts_excluded") != 1:
        return fail(f"synthetic account exclusion is wrong: {data_quality}")
    if data_quality.get("acceptance_orders_excluded") != 1 or data_quality.get("test_subscriptions_excluded") != 2:
        return fail(f"non-commercial billing exclusion is wrong: {data_quality}")
    one_day = repo.platform_operations_overview(period_days=1)
    if one_day.get("subscriptions") != subscriptions:
        return fail(f"current subscriptions must not disappear when the revenue period changes: {one_day}")
    if one_day.get("unit_economics", {}).get("normalized_mrr_minor") != 9900:
        return fail(f"MRR must use current subscription evidence, not period revenue only: {one_day}")
    serialized = json.dumps(overview, ensure_ascii=False).lower()
    for forbidden in ("api_key", "client_secret", "refresh_token", "private_key", "visitor-one", "session-one", "\"fal\"", "raw provider timeout detail"):
        if forbidden in serialized:
            return fail(f"operations overview leaked secret or replaceable provider detail: {forbidden}")

    rehearsal_task = repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="model_value_rehearsal",
        title="Excluded rehearsal telemetry",
        input_data={"rehearsal": True},
    )
    repo.record_model_usage(
        company_id=company_id,
        user_id=user_id,
        task_id=rehearsal_task["task_id"],
        usage_owner="jiejing_platform_trial",
        model_family="provider_neutral",
        model_label="rehearsal-model",
        request_count=8,
        input_tokens=800,
        output_tokens=80,
        total_tokens=880,
        cost_minor=999,
        currency="CNY",
        cost_status="configured_estimate",
        idempotency_key="excluded-model-rehearsal",
        details={
            "reliability": {
                "request_count": 8,
                "success_count": 0,
                "timeout_count": 8,
                "p75_duration_ms": 120_000,
            }
        },
    )
    repo.record_provider_cost(
        company_id=synthetic_company_id,
        user_id=synthetic_user_id,
        task_id=None,
        reference_type="public_search_request",
        reference_id="excluded-synthetic-search",
        cost_category="public_search",
        resource_type="request",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-synthetic-search",
        details={"telemetry": {"scope": "public_search", "outcome": "timeout", "duration_ms": 120_000}},
    )
    with repo._connect() as conn:
        conn.execute(
            "update users set default_company_id = ? where user_id = ?",
            (company_id, synthetic_user_id),
        )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=synthetic_user_id,
        task_id=None,
        reference_type="public_search_request",
        reference_id="excluded-synthetic-actor-in-merchant-company",
        cost_category="public_search",
        resource_type="request",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-synthetic-actor-in-merchant-company",
        details={"telemetry": {"scope": "public_search", "outcome": "timeout", "duration_ms": 120_000}},
    )
    repo.record_provider_cost(
        company_id=company_id,
        user_id=user_id,
        task_id=None,
        reference_type="payment_provider_call",
        reference_id="acceptance-order-one",
        cost_category="payment_processing",
        resource_type="checkout_create",
        unit_count=1,
        media_points=0,
        cost_minor=999,
        currency="CNY",
        cost_status="actual",
        idempotency_key="excluded-payment-acceptance",
        details={"telemetry": {"scope": "payment", "outcome": "timeout", "duration_ms": 120_000}},
    )
    excluded_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc))
    excluded_reliability = excluded_snapshot.get("reliability", {})
    if excluded_reliability.get("model", {}).get("request_count") != 1:
        return fail(f"provider monitor counted rehearsal model traffic: {excluded_snapshot}")
    if excluded_reliability.get("public_search", {}).get("request_count") != 1:
        return fail(f"provider monitor counted synthetic search traffic: {excluded_snapshot}")
    if excluded_reliability.get("payment", {}).get("request_count") != 1:
        return fail(f"provider monitor counted controlled acceptance payment traffic: {excluded_snapshot}")
    if excluded_snapshot.get("cost_total_minor") != 54:
        return fail(f"provider monitor counted non-business costs: {excluded_snapshot}")

    repo.create_task(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        task_type="merchant_ceo_chat",
        title="Current unmetered model task",
        input_data={"test_fixture": True},
    )
    incomplete_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc))
    if incomplete_snapshot.get("cost_coverage_complete") is not False:
        return fail(f"current unmetered model work must make cost coverage incomplete: {incomplete_snapshot}")
    if incomplete_snapshot.get("current_unmetered_model_tasks") != 1:
        return fail(f"focused provider monitor lost current unmetered model count: {incomplete_snapshot}")

    shifted_now = datetime.now(timezone.utc) + timedelta(minutes=31)
    shifted_snapshot = repo.provider_monitoring_snapshot(now_utc=shifted_now)
    if shifted_snapshot.get("reliability", {}).get("alerts", {}).get("evaluated_count") != 0:
        return fail(f"30-minute reliability window did not expire independently: {shifted_snapshot}")
    if shifted_snapshot.get("cost_total_minor") != 54:
        return fail(f"24-hour cost window expired with the 30-minute reliability window: {shifted_snapshot}")
    expired_snapshot = repo.provider_monitoring_snapshot(now_utc=datetime.now(timezone.utc) + timedelta(hours=25))
    if expired_snapshot.get("cost_total_minor") != 0 or expired_snapshot.get("cost_coverage_complete") is not True:
        return fail(f"24-hour cost window did not expire cleanly: {expired_snapshot}")

    frontend = (ROOT / "app.js").read_text(encoding="utf-8")
    for marker in ("访问趋势", "页面与转化", "saas-owner-traffic-trend", "saas-owner-traffic-pages"):
        if marker not in frontend:
            return fail(f"owner traffic analytics UI marker is missing: {marker}")

    server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    route_start = server.index('if path == "owner/operations-overview":')
    route_end = server.index("\n\n", route_start)
    route = server[route_start:route_end]
    if "_require_platform_internal_admin" not in route:
        return fail("operations overview endpoint is missing the internal-admin gate")
    for owner_route in (
        'if path == "owner/operations-reliability-alerts/reconcile":',
        'if path == "owner/operations-reliability-alerts/acknowledge":',
    ):
        route_start = server.index(owner_route)
        route = server[route_start : route_start + 1800]
        if "_require_platform_internal_admin" not in route:
            return fail(f"reliability duty endpoint is missing the internal-admin gate: {owner_route}")
        if '"external_provider_action_triggered": False' not in route:
            return fail(f"reliability duty endpoint is missing the no-external-action boundary: {owner_route}")

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    for marker in (
        "saasOperationsOverview",
        '"/owner/operations-overview"',
        "function renderSaasOwnerOperationsOverviewPanel",
        "renderSaasOwnerOperationsOverviewPanel(),",
        "家已授权店铺",
        "笔支付验收单",
        "merchant_navigation_visible=false",
        "当前计量正常",
        "历史对话成本不可追溯",
        "模型响应 P75",
        "联网搜索 P75",
        "素材生成 P75",
        "可靠性告警",
        "样本不足，继续采样",
        "至少 5 次请求后判级",
        "providerReliability.alerts",
        "providerReliability.lifecycle",
        "paymentReliability",
        'reliabilityTone("payment")',
        'reliabilityDetail(paymentReliability, "payment")',
        "function reconcileSaasOwnerReliabilityAlerts",
        "function acknowledgeSaasOwnerReliabilityAlert",
        "内部可靠性值班",
        "评估当前告警",
        "没有触发支付、eBay 或供应商动作",
    ):
        if marker not in app_js:
            return fail(f"internal operations frontend is missing marker: {marker}")
    owner_tab_start = app_js.index('id: "owner_ops"')
    owner_tab_end = app_js.index("tabs.push", owner_tab_start + 20) if "tabs.push" in app_js[owner_tab_start + 20 :] else len(app_js)
    owner_tab = app_js[owner_tab_start:owner_tab_end]
    if "renderSaasOwnerOperationsOverviewPanel()," not in owner_tab:
        return fail("operations overview is not confined to the internal owner tab")

    print("PASS jiejing_platform_operations_overview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
