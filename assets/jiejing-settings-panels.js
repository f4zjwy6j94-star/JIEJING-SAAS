(function attachJiejingSettingsPanels(global) {
  function escape(value) {
    const text = String(value ?? "");
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderQueueHealthPanel(state) {
    const operational = state.saasOperationalHealth && typeof state.saasOperationalHealth === "object" ? state.saasOperationalHealth : {};
    const queue = operational.queue_runtime && typeof operational.queue_runtime === "object" ? operational.queue_runtime : state.saasQueueHealth || {};
    const database = operational.database_live_probe && typeof operational.database_live_probe === "object" ? operational.database_live_probe : {};
    const worker = operational.worker_runtime && typeof operational.worker_runtime === "object" ? operational.worker_runtime : {};
    const counts = queue.counts && typeof queue.counts === "object" ? queue.counts : {};
    const status = String(operational.status || queue.status || "waiting");
    const deadLetter = Number(counts.dead_letter || 0);
    const staleRunning = Number(queue.stale_running_count || 0);
    const attention = status === "blocked" || status === "attention_required" || deadLetter > 0 || staleRunning > 0;
    const databaseReady = String(database.status || "") === "ready";
    const workerAttention = String(worker.status || "") !== "ready" && Object.keys(worker).length > 0;
    const restartCount = worker.restart_count === null || worker.restart_count === undefined ? "未接入" : String(worker.restart_count);
    const heartbeatAt = worker.latest_registered_worker_heartbeat_at || worker.latest_job_heartbeat_at || worker.env_heartbeat_at || "";
    const heartbeatSource = worker.latest_registered_worker_heartbeat_at
      ? "worker 进程心跳"
      : worker.latest_job_heartbeat_at
        ? "任务执行心跳"
        : worker.env_heartbeat_at
          ? "环境上报心跳"
          : "等待 worker 心跳";
    const processStarted = worker.registered_process_started_at || "等待上报";
    return `
      <section class="saas-settings-card">
        <div class="saas-settings-card-head">
          <div>
            <span>生产队列与深度健康</span>
            <strong>${attention ? "需要处理运行风险" : "运行状态可见"}</strong>
            <p>上线前必须能看见数据库探针、worker heartbeat、超时恢复和死信队列。失败任务不能藏在日志里，必须能恢复、重试或进入确认后的清理流程。</p>
          </div>
        </div>
        <div class="saas-settings-status-list">
          <article class="${attention ? "is-amber" : "is-green"}">
            <span>整体状态</span>
            <strong>${escape(status)}</strong>
            <small>${escape((operational.blockers || []).slice(0, 2).join(" / ") || (operational.warnings || []).slice(0, 2).join(" / ") || "无阻断项")}</small>
          </article>
          <article class="${databaseReady ? "is-green" : "is-amber"}">
            <span>数据库 live probe</span>
            <strong>${databaseReady ? "通过" : "待检查"}</strong>
            <small>${escape(database.engine || state.saasDatabasePlan?.selected_adapter || "unknown")} / ${escape(database.probe?.status || database.probe || "waiting")}</small>
          </article>
          <article class="${staleRunning ? "is-amber" : "is-green"}">
            <span>超时运行</span>
            <strong>${staleRunning}</strong>
            <small>${Number(queue.stale_after_seconds || 900)} 秒未 heartbeat 进入恢复检查</small>
          </article>
          <article class="${deadLetter ? "is-amber" : "is-green"}">
            <span>死信队列</span>
            <strong>${deadLetter}</strong>
            <small>${queue.dead_letter_visible ? "失败可见，不能静默丢任务" : "等待后端返回死信状态"}</small>
          </article>
          <article class="${workerAttention ? "is-amber" : "is-green"}">
            <span>Worker heartbeat</span>
            <strong>${escape(worker.heartbeat_status || "waiting")}</strong>
            <small>${escape(heartbeatAt || "暂未看到心跳")} / ${escape(heartbeatSource)}${worker.registered_worker_status ? ` / ${escape(worker.registered_worker_status)}` : ""}</small>
          </article>
          <article class="${worker.restart_count_status === "attention_required" ? "is-amber" : "is-green"}">
            <span>Worker 重启估算</span>
            <strong>${escape(restartCount)}</strong>
            <small>${escape(worker.restart_count_source || "not_connected")} / 启动 ${escape(processStarted)} / 阈值 ${Number(worker.restart_count_warning_threshold || 5)}</small>
          </article>
          <article>
            <span>任务分布</span>
            <strong>${Number(counts.queued || 0)} / ${Number(counts.running || 0)}</strong>
            <small>queued / running / failed ${Number(counts.failed || 0)}</small>
          </article>
        </div>
      </section>
    `;
  }

  function renderPublicSecurityStatusPanel(state) {
    const control =
      state.saasOwnerLaunchControl && typeof state.saasOwnerLaunchControl === "object" ? state.saasOwnerLaunchControl : null;
    if (control?.audience !== "platform_internal_admin" || control?.customer_visible !== false) return "";
    const rateLimit = state.saasRateLimitStatus && typeof state.saasRateLimitStatus === "object" ? state.saasRateLimitStatus : {};
    const authLimit = rateLimit.auth_rate_limit && typeof rateLimit.auth_rate_limit === "object" ? rateLimit.auth_rate_limit : {};
    const expensiveLimit =
      rateLimit.expensive_api_rate_limit && typeof rateLimit.expensive_api_rate_limit === "object" ? rateLimit.expensive_api_rate_limit : {};
    const edge = state.saasEdgeCutoverPreflight && typeof state.saasEdgeCutoverPreflight === "object" ? state.saasEdgeCutoverPreflight : {};
    const waf = edge.waf_edge && typeof edge.waf_edge === "object" ? edge.waf_edge : {};
    const origin = edge.origin_lock && typeof edge.origin_lock === "object" ? edge.origin_lock : {};
    const callbacks = edge.callback_cutover && typeof edge.callback_cutover === "object" ? edge.callback_cutover : {};
    const protectedPrefixes = Array.isArray(expensiveLimit.protected_prefixes) ? expensiveLimit.protected_prefixes : [];
    const protectedExact = Array.isArray(expensiveLimit.protected_exact_paths) ? expensiveLimit.protected_exact_paths : [];
    const routeEvidence = Array.isArray(expensiveLimit.route_group_evidence) ? expensiveLimit.route_group_evidence : [];
    const activeBuckets = Array.isArray(expensiveLimit.active_bucket_summary) ? expensiveLimit.active_bucket_summary : [];
    const protectedApiPreview = [...protectedPrefixes.slice(0, 8), ...protectedExact.slice(0, 4)].join(" / ") || "waiting_for_backend_status";
    const routeEvidencePreview = routeEvidence.map((item) => item.route_group).filter(Boolean).slice(0, 8).join(" / ") || protectedApiPreview;
    const activeBucketPreview = activeBuckets.length
      ? activeBuckets.map((item) => `${item.method}:${item.route_group}:${item.active_request_count}`).slice(0, 4).join(" / ")
      : "no active high-cost buckets";
    const cloudflareFreeReady = waf.cloudflare_free_baseline_ready === true;
    const botReady = waf.bot_protection_enabled === true && waf.ai_crawler_control_enabled === true && waf.turnstile_or_managed_challenge_enabled === true;
    const rows = [
      {
        label: "noindex / robots",
        value: "code_ready",
        detail: "robots.txt disallow all; API and edge responses send X-Robots-Tag noindex/noarchive; this is not a data-security boundary.",
        tone: "green",
      },
      {
        label: "source maps",
        value: "blocked",
        detail: "public nginx blocks .map requests with 404 so casual source-map scraping does not expose bundled internals.",
        tone: "green",
      },
      {
        label: "Cloudflare free baseline",
        value: cloudflareFreeReady ? "verified_by_env" : "needs_console_evidence",
        detail: `provider=${waf.provider || "waiting"} / dns_proxied=${Boolean(waf.dns_proxied)} / managed_rules_paid=${Boolean(waf.managed_waf_rules_enabled)}`,
        tone: cloudflareFreeReady ? "green" : "amber",
      },
      {
        label: "Bot / AI crawler controls",
        value: botReady ? "enabled" : "needs_verification",
        detail: `bot=${Boolean(waf.bot_protection_enabled)} / ai_crawler=${Boolean(waf.ai_crawler_control_enabled)} / challenge=${Boolean(waf.turnstile_or_managed_challenge_enabled)}`,
        tone: botReady ? "green" : "amber",
      },
      {
        label: "Auth endpoint rate limit",
        value: authLimit.enabled ? `${authLimit.max_per_ip || "?"}/${authLimit.window_seconds || "?"}s` : "waiting",
        detail: Array.isArray(authLimit.protected_paths) ? authLimit.protected_paths.join(" / ") : "auth/login / auth/register / auth/demo-session",
        tone: authLimit.enabled ? "green" : "amber",
      },
      {
        label: "High-cost API rate limit",
        value: expensiveLimit.enabled ? `${expensiveLimit.max_per_ip_per_route_group || "?"}/${expensiveLimit.window_seconds || "?"}s` : "waiting",
        detail: routeEvidencePreview,
        tone: expensiveLimit.enabled ? "green" : "amber",
      },
      {
        label: "Active high-cost buckets",
        value: String(activeBuckets.length || 0),
        detail: activeBucketPreview,
        tone: activeBuckets.some((item) => Number(item.saturated_client_bucket_count || 0) > 0) ? "amber" : "green",
      },
      {
        label: "Origin direct access",
        value: origin.ready ? "locked" : "needs_probe",
        detail: `edge_only=${Boolean(origin.http_https_edge_only)} / direct_ip_blocked=${Boolean(origin.direct_origin_ip_blocked)} / ssh_operator_only=${Boolean(origin.ssh_operator_only)}`,
        tone: origin.ready ? "green" : "amber",
      },
      {
        label: "Callback allowlist",
        value: callbacks.ready ? "stable_domain_ready" : "not_final",
        detail: "eBay and Stripe callbacks are not anti-scrape controls, but they must stay on stable HTTPS and bypass bot challenges safely.",
        tone: callbacks.ready ? "green" : "amber",
      },
    ];
    return `
      <section class="saas-settings-card saas-owner-public-security-status" aria-label="公网安全状态">
        <div class="saas-settings-card-head">
          <div>
            <span>公网安全状态</span>
            <strong>平台内部安全审计 · 防爬、限流和边缘证据</strong>
            <p>这个区域只对平台管理员开放，用来核对 noindex、接口限流、高成本 API 保护、Cloudflare 免费规则证据和源站直连风险。普通商家不会看到这些工程排查项。</p>
          </div>
        </div>
        <div class="saas-settings-status-list">
          ${rows
            .map(
              (row) => `
                <article class="is-${escape(row.tone)}">
                  <span>${escape(row.label)}</span>
                  <strong>${escape(row.value)}</strong>
                  <small>${escape(row.detail)}</small>
                </article>
              `,
            )
            .join("")}
        </div>
        <div class="saas-settings-row-list">
          <article class="${cloudflareFreeReady && expensiveLimit.enabled ? "is-green" : "is-amber"}">
            <div>
              <span>security_surface_contract</span>
              <strong>${cloudflareFreeReady && expensiveLimit.enabled ? "free_baseline_operational" : "needs_final_edge_evidence"}</strong>
              <small>not_customer_visible=true / platform_internal_admin_only=true / real_secret_boundary=backend_vault</small>
              <small>protects_data_boundary=true / prevents_complete_copy=false / makes_scraping_costly=true</small>
            </div>
            <em>security</em>
          </article>
        </div>
      </section>
    `;
  }

  function renderBillingProviderPanel(state) {
    const plan = state.saasBillingPlan && typeof state.saasBillingPlan === "object" ? state.saasBillingPlan : {};
    const usage = state.saasBillingUsage && typeof state.saasBillingUsage === "object" ? state.saasBillingUsage : {};
    const checkout = state.saasBillingCheckout && typeof state.saasBillingCheckout === "object" ? state.saasBillingCheckout : {};
    const provider = plan.provider && typeof plan.provider === "object" ? plan.provider : {};
    const quota = plan.quota_contract && typeof plan.quota_contract === "object" ? plan.quota_contract : {};
    const checkoutSession = checkout.checkout_sessions && typeof checkout.checkout_sessions === "object" ? checkout.checkout_sessions : {};
    const portal = checkout.customer_portal && typeof checkout.customer_portal === "object" ? checkout.customer_portal : {};
    const subscription = usage.subscription && typeof usage.subscription === "object" ? usage.subscription : {};
    const domestic = state.saasDomesticBillingContract && typeof state.saasDomesticBillingContract === "object" ? state.saasDomesticBillingContract : {};
    const domesticConfigured = domestic.provider === "wechat_pay_native";
    const domesticOnline = domesticConfigured && domestic.real_checkout_ready === true && domestic.charge_now_allowed === true;
    const blockers = Array.isArray(plan.paid_launch_blockers) ? plan.paid_launch_blockers : Array.isArray(plan.blockers) ? plan.blockers : [];
    const shutdownClosure =
      plan.subscription_quota_shutdown_closure && typeof plan.subscription_quota_shutdown_closure === "object"
        ? plan.subscription_quota_shutdown_closure
        : {};
    const shutdownState =
      usage.subscription_quota_shutdown_state && typeof usage.subscription_quota_shutdown_state === "object"
        ? usage.subscription_quota_shutdown_state
        : {};
    const paidReady = Boolean(plan.billing_ready_for_paid_launch);
    const privateBetaReady = Boolean(plan.billing_ready_for_private_beta);
    const paymentReady = Boolean(domesticOnline || provider.external_paid_provider_configured || provider.test_billing_provider_configured || checkoutSession.ready);
    const portalReady = Boolean(portal.ready);
    const quotaReady = Boolean(quota.enabled);
    const shutdownReady = Boolean(shutdownClosure.ready || shutdownState.blocks_metered_work_when_inactive);
    const billingModeLabel = domesticOnline ? "微信扫码付款可用" : paidReady ? "在线付款可用" : privateBetaReady ? "受邀试用中" : "在线付款尚未开放";
    const billingModeDetail = domesticOnline
      ? "商家主动扫码购买 30 天；后端确认到账后开通权益，不会自动续费或自动扣款。"
      : paidReady
      ? "订阅开通、续费、取消和付款异常会按系统账单状态处理；浏览器不保存支付密钥。"
      : privateBetaReady
        ? "当前只支持受邀试用和人工确认，不会在前台发起真实扣费。"
        : "当前只展示套餐、额度和停用规则；不会创建真实付款，也不会自动扣款。";
    const billingAttention = shutdownState.payment_attention_required || blockers.length > 0;
    const subscriptionStatusLabel = subscription.entitlement_active ? "权益可用" : billingAttention ? "需要处理" : "待开通";
    const paymentStatusLabel = billingAttention ? "需要处理" : "正常";
    const billingPauseDetail = billingAttention
      ? "请先处理订阅或联系客服恢复；在恢复前只会暂停高成本任务。"
      : "历史资料、确认记录和账号设置不会因为额度状态被删除。";
    const flowRows = [
      ["01", "先看订阅", subscription.entitlement_active ? "基础权益可用" : "基础权益待开通"],
      ["02", "再看用量", quotaReady ? "AI、联网和素材按额度保护" : "等待额度账本接入"],
      ["03", "异常处理", "欠费、取消或超量只暂停高成本任务"],
      ["04", "恢复使用", "续费或客服确认后刷新用量，不需要重复连接 eBay，也不需要重填 AI 连接"],
    ];
    return `
      <section class="saas-settings-card">
        <div class="saas-settings-card-head">
          <div>
            <span>订阅与付款</span>
            <strong>${escape(billingModeLabel)}</strong>
            <p>${escape(billingModeDetail)}</p>
          </div>
        </div>
        <div class="saas-settings-status-list">
          <article class="${paymentReady ? "is-green" : "is-amber"}">
            <span>当前模式</span>
            <strong>${escape(billingModeLabel)}</strong>
            <small>${domesticOnline ? "商家主动创建订单并微信扫码，页面不展示任何支付密钥。" : paymentReady ? "订阅处理只以支付平台确认结果为准，页面不展示任何支付密钥。" : "在线付款开放前，商家只会看到套餐、额度和下一步说明。"}</small>
          </article>
          <article class="${domesticConfigured || portalReady ? "is-green" : "is-amber"}">
            <span>续费 / 取消</span>
            <strong>${domesticConfigured ? "到期自主续购" : portalReady ? "自助管理可用" : "客服协助"}</strong>
            <small>${domesticConfigured ? "每次单独购买 30 天，不设置自动续费；退款或订单问题进入客服审核。" : portalReady ? "升级、降级、取消和付款方式管理会在支付平台处理。" : "自助入口未开放前，由客服协助处理订阅变更。"}</small>
          </article>
          <article class="${quotaReady ? "is-green" : "is-amber"}">
            <span>AI / 素材用量</span>
            <strong>${quotaReady ? "按额度保护" : "等待额度账本"}</strong>
            <small>店铺数、AI CEO 任务、调研、素材和模型用量会按套餐显示，欠费或超量只暂停高成本任务。</small>
          </article>
          <article class="${subscription.entitlement_active ? "is-green" : "is-amber"}">
            <span>当前权益</span>
            <strong>${escape(subscriptionStatusLabel)}</strong>
            <small>${subscription.entitlement_active ? "当前公司权益有效。" : "当前还没有可用订阅；开通或恢复后会自动更新权益。"}</small>
          </article>
          <article class="${billingAttention ? "is-amber" : "is-green"}">
            <span>付款状态</span>
            <strong>${escape(paymentStatusLabel)}</strong>
            <small>${escape(billingPauseDetail)}</small>
          </article>
          <article class="${shutdownReady ? "is-green" : "is-amber"}">
            <span>欠费保护</span>
            <strong>${shutdownReady ? "已启用" : "待完善"}</strong>
            <small>付款失败或取消后，只暂停模型、联网、素材生成等高成本任务，保留商家历史数据。</small>
          </article>
          <article class="${domesticOnline || paidReady ? "is-green" : "is-amber"}">
            <span>在线付款开放</span>
            <strong>${domesticOnline ? "微信支付可用" : paidReady ? "可开放" : "暂不开放"}</strong>
            <small>${domesticOnline ? "正式公开收费仍需独立上线批准；当前链路不会影响 eBay 或经营确认中心。" : paidReady ? "开放后仍会保留确认中心和操作记录。" : "当前仅展示试用和订阅说明；在线付款开放前不会收取订阅费用。"}</small>
          </article>
        </div>
        <div class="saas-settings-row-list">
          ${flowRows
            .map(
              ([step, title, detail]) => `
                <article class="is-green">
                  <div>
                    <span>${escape(step)}</span>
                    <strong>${escape(title)}</strong>
                    <small>${escape(detail)}</small>
                  </div>
                </article>
              `,
            )
            .join("")}
        </div>
        <div class="saas-settings-safety" hidden aria-hidden="true">
          <span>merchant_billing_copy_public_safe_v1</span>
          <span>ordinary_merchant_gets_internal_provider_copy=false</span>
          <span>ordinary_merchant_gets_rehearsal_controls=false</span>
          <span>domestic_payment_provider=${escape(domesticConfigured ? "wechat_pay_native" : "not_configured")}</span>
          <span>domestic_payment_online=${escape(String(domesticOnline))}</span>
          <span>renewal_mode=${escape(domesticConfigured ? "merchant_confirmed_one_time_30_day" : "provider_subscription")}</span>
          <span>triggers_real_charge=false</span>
          <span>frontend_gets_payment_secret=false</span>
        </div>
      </section>
    `;
  }

  function _renderBillingTestRehearsal(summary, latestEvent, loading) {
    const steps = Array.isArray(summary.steps) ? summary.steps : [];
    const ready = Boolean(summary.ready);
    const buttonDisabled = !ready || loading ? "disabled" : "";
    const latest = latestEvent && typeof latestEvent === "object" ? latestEvent : null;
    const latestEventShape = latest && latest.event && typeof latest.event === "object" ? latest.event : {};
    const latestStatus = latest
      ? latest.ok === false
        ? "blocked"
        : latestEventShape.subscription_status || latest.status || "applied"
      : "waiting";
    return `
      <div class="saas-settings-row-list saas-billing-test-rehearsal">
        <article class="${ready ? "is-green" : "is-amber"}">
          <div>
            <span>no_charge_billing_rehearsal</span>
            <strong>${Number(summary.ready_count || 0)}/${Number(summary.total_count || steps.length || 0)} ready</strong>
            <small>provider=${escape(summary.provider || "not_selected")} / no Stripe account required / public_charging_allowed=false</small>
            <small>creates_real_checkout_session=false / calls_stripe_api=false / triggers_real_charge=false</small>
            <small>Use POST /billing/test-event to rehearse active, invoice paid, payment failed and cancel states.</small>
          </div>
          <em>${ready ? "test-ready" : "blocked"}</em>
        </article>
        <article class="${latest && latest.ok === false ? "is-amber" : latest ? "is-green" : "is-amber"}">
          <div>
            <span>billing_test_event_console</span>
            <strong>${escape(latestStatus)}</strong>
            <small>owner-only no-charge controls: no Stripe account, no card collection, no real customer charge.</small>
            <small>last_action=${escape(latest?.action || "not_run")} / plan=${escape(latest?.event?.plan_key || latest?.plan_key || "operator")}</small>
            <small>calls_stripe_api=${Boolean(latest?.calls_stripe_api)} / charge_now_allowed=${Boolean(latest?.charge_now_allowed)} / frontend_gets_payment_secret=${Boolean(latest?.frontend_gets_payment_secret)}</small>
            ${latest?.message ? `<small>${escape(latest.message)}</small>` : ""}
          </div>
          <div class="saas-billing-test-actions" aria-label="No-charge billing test actions">
            <button class="secondary-action compact-action" type="button" data-saas-action="billing-test-event" data-billing-test-action="activate" data-billing-plan-key="operator" ${buttonDisabled}>Activate</button>
            <button class="secondary-action compact-action" type="button" data-saas-action="billing-test-event" data-billing-test-action="invoice_paid" data-billing-plan-key="operator" ${buttonDisabled}>Invoice paid</button>
            <button class="secondary-action compact-action" type="button" data-saas-action="billing-test-event" data-billing-test-action="payment_failed" data-billing-plan-key="operator" ${buttonDisabled}>Payment failed</button>
            <button class="secondary-action compact-action" type="button" data-saas-action="billing-test-event" data-billing-test-action="cancel" data-billing-plan-key="operator" ${buttonDisabled}>Cancel</button>
          </div>
          <em>${loading ? "running" : latest ? "latest" : "not-run"}</em>
        </article>
        ${steps
          .map(
            (step) => `
              <article class="${step.status === "ready" ? "is-green" : "is-amber"}">
                <div>
                  <span>${escape(step.key || "billing_test_step")}</span>
                  <strong>${escape(step.status || "blocked")}</strong>
                  <small>${escape(step.evidence_summary || "")}</small>
                  <small>${escape(step.next_action || "")}</small>
                </div>
                <em>${escape(step.severity || "info")}</em>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function _renderSubscriptionQuotaShutdownClosure(closure, shutdownState) {
    const steps = Array.isArray(closure.steps) ? closure.steps : [];
    const ready = Boolean(closure.ready);
    const readyCount = Number(closure.ready_count || steps.filter((item) => item && item.status === "ready").length || 0);
    const totalCount = Number(closure.total_count || steps.length || 0);
    const state = shutdownState && typeof shutdownState === "object" ? shutdownState : {};
    const blockedUnits = Array.isArray(state.blocked_units) ? state.blocked_units.slice(0, 6) : [];
    const flags = [
      `public_charging_allowed=${Boolean(closure.public_charging_allowed)}`,
      `creates_checkout_session=${Boolean(closure.creates_checkout_session)}`,
      `calls_stripe_api=${Boolean(closure.calls_stripe_api)}`,
      `triggers_real_charge=${Boolean(closure.triggers_real_charge)}`,
      `charge_now_allowed=${Boolean(closure.charge_now_allowed)}`,
      `frontend_gets_payment_secret=${Boolean(closure.frontend_gets_payment_secret)}`,
      `secret_exposed=${Boolean(closure.secret_exposed)}`,
    ];
    return `
      <div class="saas-settings-row-list saas-subscription-quota-shutdown-closure">
        <article class="${ready ? "is-green" : "is-amber"}">
          <div>
            <span>subscription_quota_shutdown_closure</span>
            <strong>${readyCount}/${totalCount || "?"} ready</strong>
            <small>payment_failed_disables_entitlement / subscription_cancel_disables_entitlement / quota_guardrail_blocks_metered_work / provider_cutover_no_real_charge_safety</small>
            <small>ready_for_no_charge_rehearsal=${Boolean(closure.ready_for_no_charge_rehearsal)} / ready_for_live_cutover=${Boolean(closure.ready_for_live_cutover)}</small>
            <small>${escape(flags.join(" / "))}</small>
          </div>
          <em>${ready ? "closed" : "blocked"}</em>
        </article>
        <article class="${state.entitlement_active ? "is-green" : "is-amber"}">
          <div>
            <span>quota_shutdown_state</span>
            <strong>${escape(state.subscription_status || "subscription_missing")}</strong>
            <small>entitlement_active=${Boolean(state.entitlement_active)} / payment_attention_required=${Boolean(state.payment_attention_required)} / quota_enforcement_enabled=${Boolean(state.quota_enforcement_enabled)}</small>
            <small>blocks_metered_work_when_inactive=${Boolean(state.blocks_metered_work_when_inactive)} / block_reason=${escape(state.block_reason || "none")}</small>
            <small>blocked_units=${escape(blockedUnits.join(" / ") || "none")}${state.blocked_units?.length > blockedUnits.length ? " / ..." : ""}</small>
          </div>
          <em>merchant-state</em>
        </article>
        ${steps
          .map(
            (step) => `
              <article class="${step.status === "ready" ? "is-green" : "is-amber"}">
                <div>
                  <span>${escape(step.key || "subscription_quota_step")}</span>
                  <strong>${escape(step.title || step.status || "blocked")}</strong>
                  <small>${escape(step.evidence_summary || "waiting_for_subscription_quota_evidence")}</small>
                  <small>${escape(step.next_action || "continue_billing_shutdown_drill")}</small>
                  <small>external_resource_required=${Boolean(step.external_resource_required)} / owner_approval_required=${Boolean(step.owner_approval_required)}</small>
                  <small>creates_checkout_session=${Boolean(step.creates_checkout_session)} / calls_stripe_api=${Boolean(step.calls_stripe_api)} / triggers_real_charge=${Boolean(step.triggers_real_charge)}</small>
                </div>
                <em>${escape(step.status || "blocked")}</em>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function _renderBillingDomainCutoverRehearsal(rehearsal) {
    const summary = rehearsal.summary && typeof rehearsal.summary === "object" ? rehearsal.summary : {};
    const stages = Array.isArray(rehearsal.stages) ? rehearsal.stages : [];
    const readyCount = Number(summary.ready_count || stages.filter((item) => item && item.status === "ready").length || 0);
    const totalCount = Number(summary.total_count || stages.length || 0);
    const blockedCount = Number(summary.blocked_count || stages.filter((item) => item && item.status !== "ready").length || 0);
    const allowed = Boolean(rehearsal.ready_for_owner_approval);
    const requiredUrls = rehearsal.required_urls && typeof rehearsal.required_urls === "object" ? rehearsal.required_urls : {};
    const flags = [
      `mode=${rehearsal.mode || "dry_run_no_charge"}`,
      `charge_now_allowed=${Boolean(rehearsal.charge_now_allowed)}`,
      `creates_checkout_session=${Boolean(rehearsal.creates_checkout_session)}`,
      `calls_stripe_api=${Boolean(rehearsal.calls_stripe_api)}`,
      `triggers_ebay_oauth=${Boolean(rehearsal.triggers_ebay_oauth)}`,
      `frontend_gets_payment_secret=${Boolean(rehearsal.frontend_gets_payment_secret)}`,
    ];
    return `
      <div class="saas-settings-row-list saas-billing-domain-cutover-rehearsal">
        <article class="${allowed ? "is-green" : "is-amber"}">
          <div>
            <span>stripe_domain_cutover_rehearsal</span>
            <strong>${readyCount}/${totalCount || "?"} ready</strong>
            <small>${escape(summary.next_step || (blockedCount ? "cutover_evidence_required" : "ready_for_owner_approval"))}</small>
            <small>${escape(summary.next_action || "collect_billing_domain_cutover_evidence")}</small>
            <small>stripe_checkout_return_urls_on_stable_domain / stripe_signed_webhook_on_stable_domain / subscription_state_and_quota_lifecycle_rehearsed</small>
            <small>${escape(flags.join(" / "))}</small>
          </div>
          <em>${allowed ? "approval" : "blocked"}</em>
        </article>
        <article class="${rehearsal.stable_domain ? "is-green" : "is-amber"}">
          <div>
            <span>stable domain URLs</span>
            <strong>${escape(rehearsal.stable_domain || "not_selected")}</strong>
            <small>success=${escape(_urlShape(requiredUrls.stripe_success_url))} / cancel=${escape(_urlShape(requiredUrls.stripe_cancel_url))}</small>
            <small>portal=${escape(_urlShape(requiredUrls.stripe_portal_return_url))} / webhook=${escape(_urlShape(requiredUrls.stripe_webhook_url))}</small>
            <small>eBay callback=${escape(requiredUrls.ebay_oauth_callback_url || "waiting_for_stable_domain")}</small>
          </div>
          <em>urls</em>
        </article>
        ${stages.map((stage) => _renderBillingDomainCutoverStage(stage)).join("")}
      </div>
    `;
  }

  function _urlShape(value) {
    if (!value || typeof value !== "object") return "missing";
    return `${value.scheme || "no-scheme"}://${value.host || "missing"}${value.path || ""}`;
  }

  function _renderBillingDomainCutoverStage(stage) {
    const ready = stage && stage.status === "ready";
    const envKeys = Array.isArray(stage?.environment_keys) ? stage.environment_keys.slice(0, 5) : [];
    const docs = Array.isArray(stage?.docs) ? stage.docs.slice(0, 2) : [];
    const flags = [
      stage?.creates_checkout_session ? "would_create_checkout" : "no_checkout_created",
      stage?.calls_stripe_api ? "would_call_stripe" : "no_stripe_call",
      stage?.triggers_real_charge ? "would_charge" : "no_charge",
      stage?.triggers_ebay_oauth ? "would_oauth" : "no_oauth",
      stage?.repeat_ebay_oauth_allowed ? "repeat_oauth_allowed" : "repeat_oauth_forbidden",
      stage?.triggers_real_platform_write ? "would_write" : "no_platform_write",
      stage?.secret_exposed ? "secret_risk" : "secret_exposed_false",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(stage?.owner || "platform_ops")} / ${escape(stage?.category || "cutover")}</span>
          <strong>${escape(stage?.title || stage?.key || "billing_domain_cutover_stage")}</strong>
          <small>${escape(stage?.evidence_summary || "waiting_for_cutover_evidence")}</small>
          <small>${escape(stage?.next_action || "continue_cutover_rehearsal")}</small>
          <small>${escape(envKeys.join(" / ") || "no_env_keys_required")}${stage?.environment_keys?.length > envKeys.length ? " / ..." : ""}</small>
          <small>${escape(docs.join(" / ") || "project_runbook")}</small>
          <small>${escape(flags.join(" / "))}</small>
        </div>
        <em>${ready ? "ready" : "blocked"}</em>
      </article>
    `;
  }

  function _renderBillingLiveCutoverStep(item) {
    const ready = item && item.status === "ready";
    const envKeys = Array.isArray(item?.environment_keys) ? item.environment_keys.slice(0, 5) : [];
    const verification = Array.isArray(item?.verification) ? item.verification.slice(0, 3) : [];
    const docs = Array.isArray(item?.docs) ? item.docs.slice(0, 2) : [];
    const flags = [
      item?.external_resource_required ? "external_resource" : "internal_contract",
      item?.triggers_real_charge ? "would_charge" : "no_charge",
      item?.charge_now_allowed ? "charge_allowed" : "charge_now_false",
      item?.frontend_gets_payment_secret ? "frontend_secret_risk" : "frontend_no_secret",
      item?.owner_approval_required ? "owner_approval" : "operator_check",
      item?.secret_exposed ? "secret_risk" : "secret_exposed_false",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "platform_ops")} · ${escape(item?.category || "billing_live_cutover")}</span>
          <strong>${escape(item?.title || item?.key || "billing_live_cutover_step")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_billing_evidence")}</small>
          <small>${escape(item?.next_action || "continue_collecting_billing_cutover_evidence")}</small>
          <small>${escape(envKeys.join(" / ") || "no_env_keys_required")}${item?.environment_keys?.length > envKeys.length ? " / ..." : ""}</small>
          <small>${escape(verification.join(" / ") || "manual_verification_required")}</small>
          <small>${escape(docs.join(" / ") || "Stripe go-live docs")}</small>
          <small>${escape(flags.join(" · "))}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function renderEdgeCutoverReadinessPanel(state) {
    const packet = state.saasEdgeCutoverPreflight && typeof state.saasEdgeCutoverPreflight === "object" ? state.saasEdgeCutoverPreflight : {};
    const hasPacket = Object.keys(packet).length > 0;
    const summary = packet.summary && typeof packet.summary === "object" ? packet.summary : {};
    const domain = packet.domain && typeof packet.domain === "object" ? packet.domain : {};
    const waf = packet.waf_edge && typeof packet.waf_edge === "object" ? packet.waf_edge : {};
    const origin = packet.origin_lock && typeof packet.origin_lock === "object" ? packet.origin_lock : {};
    const callbacks = packet.callback_cutover && typeof packet.callback_cutover === "object" ? packet.callback_cutover : {};
    const originPlan = packet.origin_security_group_plan && typeof packet.origin_security_group_plan === "object" ? packet.origin_security_group_plan : {};
    const requiredUrls =
      packet.required_callback_urls && typeof packet.required_callback_urls === "object"
        ? packet.required_callback_urls
        : callbacks.required_urls && typeof callbacks.required_urls === "object"
          ? callbacks.required_urls
          : {};
    const stages = Array.isArray(packet.stages) ? packet.stages : [];
    const sequence = Array.isArray(packet.operator_sequence) ? packet.operator_sequence : [];
    const docs = Array.isArray(packet.docs) ? packet.docs.slice(0, 3) : [];
    const ready = Boolean(packet.ready_for_owner_approval || packet.status === "ready_for_owner_approval");
    const blockedCount = Number(summary.blocked_count || stages.filter((item) => item && item.status !== "ready").length || 0);
    const readyCount = Number(summary.ready_count || stages.filter((item) => item && item.status === "ready").length || 0);
    const totalCount = Number(summary.total_count || stages.length || 4);
    const blockedKeys = Array.isArray(summary.blocked_keys) ? summary.blocked_keys.filter(Boolean) : [];
    const targetHost = packet.target_app_host || domain.target_app_host || domain.stable_domain || "app.jiejing.shop";
    const selectedDomain = packet.selected_root_domain || domain.selected_root_domain || "jiejing.shop";
    const statusCards = [
      {
        label: "stable_domain_purchase_confirmed",
        title: summary.domain_registered ? "域名已进入可接入状态" : "等待域名审核和购买完成",
        detail: `${selectedDomain} / registration=${domain.domain_registration_status || "pending"}`,
        ready: Boolean(summary.domain_registered),
      },
      {
        label: "waf_edge_onboarded",
        title: summary.waf_ready ? "WAF / Edge 已有证据" : "等待 Cloudflare 或腾讯云 WAF 接入",
        detail: `provider=${waf.provider || packet.selected_edge_provider || "not_selected"} / managed_rules=${Boolean(waf.managed_waf_rules_enabled)}`,
        ready: Boolean(summary.waf_ready),
      },
      {
        label: "origin_direct_access_locked",
        title: summary.origin_locked ? "源站直连已锁" : "源站锁等待 WAF 验证后执行",
        detail: `server_ip=${originPlan.server_ip || "43.129.205.244"} / direct_ip_blocked=${Boolean(origin.direct_origin_ip_blocked)}`,
        ready: Boolean(summary.origin_locked),
      },
      {
        label: "ebay_stripe_callbacks_on_stable_domain",
        title: summary.callbacks_ready ? "eBay / Stripe URL 已对齐稳定域名" : "等待 HTTPS 稳定域名后切回调",
        detail: `${targetHost} / stripe_verified=${Boolean(callbacks.stripe_urls_verified_in_dashboard)}`,
        ready: Boolean(summary.callbacks_ready),
      },
    ];
    const safetyFlags = [
      `charge_now_allowed=${Boolean(packet.charge_now_allowed)}`,
      `creates_checkout_session=${Boolean(packet.creates_checkout_session)}`,
      `calls_stripe_api=${Boolean(packet.calls_stripe_api)}`,
      `triggers_ebay_oauth=${Boolean(packet.triggers_ebay_oauth)}`,
      `triggers_real_platform_write=${Boolean(packet.triggers_real_platform_write)}`,
      `frontend_gets_payment_secret=${Boolean(packet.frontend_gets_payment_secret)}`,
      `frontend_gets_ebay_token=${Boolean(packet.frontend_gets_ebay_token)}`,
      `secret_exposed=${Boolean(packet.secret_exposed)}`,
    ];
    return `
      <section class="saas-settings-card saas-edge-cutover-readiness">
        <div class="saas-settings-card-head">
          <div>
            <span>稳定域名 / WAF / 源站锁体检</span>
            <strong>${ready ? "可以进入人工控制台确认，但仍不等于可收费上线" : "域名审核期：只做准备，不做真切换"}</strong>
            <p>这里把正式门牌号、防火墙入口、源站后门锁和 eBay/Stripe 回调放在一张上线体检表里。当前预检不会创建 Checkout、不会重复 eBay OAuth、不会真实写入平台。</p>
          </div>
          <em>${hasPacket ? `${readyCount}/${totalCount} ready` : "waiting"}</em>
        </div>
        <div class="saas-edge-safety-strip">
          ${safetyFlags.map((flag) => `<span>${escape(flag)}</span>`).join("")}
        </div>
        <div class="saas-settings-status-list saas-edge-cutover-grid">
          ${statusCards
            .map(
              (item) => `
                <article class="${item.ready ? "is-green" : "is-amber"}">
                  <span>${escape(item.label)}</span>
                  <strong>${escape(item.title)}</strong>
                  <small>${escape(item.detail)}</small>
                </article>
              `,
            )
            .join("")}
          <article class="${ready ? "is-green" : "is-amber"}">
            <span>edge_cutover_preflight</span>
            <strong>${escape(packet.status || "waiting_for_backend_packet")}</strong>
            <small>${escape(summary.next_step || blockedKeys[0] || "login_then_refresh")}</small>
            <small>${escape(summary.next_action || "等待后端读取稳定域名 / WAF / 源站锁证据")}</small>
          </article>
        </div>
        <div class="saas-settings-row-list saas-edge-stage-list">
          <article class="${blockedCount ? "is-amber" : "is-green"}">
            <div>
              <span>launch infrastructure sequence</span>
              <strong>${readyCount}/${totalCount} ready</strong>
              <small>${escape(blockedKeys.join(" / ") || "edge_waf_origin_callbacks_ready")}</small>
              <small>不要在 WAF 健康检查通过前锁源站；不要在稳定域名确认前切 eBay/Stripe 回调。</small>
            </div>
            <em>${blockedCount ? "blocked" : "ready"}</em>
          </article>
          ${stages.map((stage) => _renderEdgeCutoverStage(stage)).join("")}
        </div>
        <div class="saas-settings-row-list saas-edge-required-urls">
          <article>
            <div>
              <span>required_callback_urls</span>
              <strong>${escape(targetHost)}</strong>
              <small>eBay callback=${escape(requiredUrls.ebay_oauth_callback || "waiting_for_stable_domain")}</small>
              <small>Stripe success=${escape(requiredUrls.stripe_checkout_success || "waiting")} / cancel=${escape(requiredUrls.stripe_checkout_cancel || "waiting")}</small>
              <small>Portal=${escape(requiredUrls.stripe_portal_return || "waiting")} / webhook=${escape(requiredUrls.stripe_webhook || "waiting")}</small>
            </div>
            <em>URLs</em>
          </article>
          <article class="is-amber">
            <div>
              <span>origin_security_group_plan</span>
              <strong>${escape(originPlan.server_ip || "43.129.205.244")}</strong>
              <small>HTTP/HTTPS 只允许当前 edge provider IP ranges；SSH 只允许可信运维入口。</small>
              <small>do_not_lock_before_edge_is_verified=${escape(Boolean(originPlan.do_not_lock_before_edge_is_verified || origin.do_not_apply_before_edge_dns_is_verified))}</small>
            </div>
            <em>origin</em>
          </article>
          ${sequence.slice(0, 6).map((step) => _renderEdgeOperatorStep(step)).join("")}
          ${docs.length
            ? `
              <article>
                <div>
                  <span>primary docs checked</span>
                  <strong>${docs.length} docs</strong>
                  <small>${escape(docs.join(" / "))}</small>
                </div>
                <em>docs</em>
              </article>
            `
            : ""}
        </div>
      </section>
    `;
  }

  function _renderEdgeCutoverStage(stage) {
    const ready = stage && stage.status === "ready";
    const flags = [
      stage?.can_prepare_now ? "can_prepare_now" : "wait_for_prior_gate",
      stage?.external_console_required ? "owner_console" : "backend_evidence",
      stage?.creates_checkout_session ? "would_create_checkout" : "no_checkout_created",
      stage?.triggers_ebay_oauth ? "would_oauth" : "no_oauth",
      stage?.triggers_real_platform_write ? "would_write" : "no_platform_write",
      stage?.secret_exposed ? "secret_risk" : "secret_exposed_false",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(stage?.key || "edge_cutover_stage")}</span>
          <strong>${escape(stage?.title || "上线基础设施检查")}</strong>
          <small>${escape(stage?.evidence_summary || "waiting_for_evidence")}</small>
          <small>${escape(stage?.next_action || "continue_collecting_edge_cutover_evidence")}</small>
          <small>${escape(flags.join(" / "))}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderEdgeOperatorStep(step) {
    return `
      <article class="${step?.can_do_now ? "is-amber" : ""}">
        <div>
          <span>${escape(step?.key || "operator_step")}</span>
          <strong>${escape(step?.title || "等待人工控制台操作")}</strong>
          <small>category=${escape(step?.category || "edge")} / external_console_required=${escape(Boolean(step?.external_console_required))}</small>
        </div>
        <em>${step?.can_do_now ? "now" : "later"}</em>
      </article>
    `;
  }

  function renderCommercialLaunchActionPlanPanel(state) {
    const launchGate = state.saasCommercialLaunchGate && typeof state.saasCommercialLaunchGate === "object" ? state.saasCommercialLaunchGate : {};
    const plan = launchGate.launch_action_plan && typeof launchGate.launch_action_plan === "object" ? launchGate.launch_action_plan : {};
    const summary = plan.summary && typeof plan.summary === "object" ? plan.summary : {};
    const sections = Array.isArray(plan.sections) ? plan.sections : [];
    const drills = Array.isArray(plan.commercial_hardening_drills)
      ? plan.commercial_hardening_drills
      : Array.isArray(launchGate.commercial_hardening_drills)
        ? launchGate.commercial_hardening_drills
        : [];
    const newAccountSmoke = Array.isArray(plan.new_ebay_account_smoke_runbook)
      ? plan.new_ebay_account_smoke_runbook
      : Array.isArray(launchGate.new_ebay_account_smoke_runbook)
        ? launchGate.new_ebay_account_smoke_runbook
        : [];
    const cutover = Array.isArray(plan.paid_launch_cutover_checklist)
      ? plan.paid_launch_cutover_checklist
      : Array.isArray(launchGate.paid_launch_cutover_checklist)
        ? launchGate.paid_launch_cutover_checklist
        : [];
    const cutoverDecision =
      plan.paid_launch_cutover_decision && typeof plan.paid_launch_cutover_decision === "object"
        ? plan.paid_launch_cutover_decision
        : launchGate.paid_launch_cutover_decision && typeof launchGate.paid_launch_cutover_decision === "object"
          ? launchGate.paid_launch_cutover_decision
          : {};
    const deferredStrategy =
      plan.prelaunch_deferred_strategy && typeof plan.prelaunch_deferred_strategy === "object"
        ? plan.prelaunch_deferred_strategy
        : launchGate.prelaunch_deferred_strategy && typeof launchGate.prelaunch_deferred_strategy === "object"
          ? launchGate.prelaunch_deferred_strategy
          : {};
    const approvalPacket =
      state.saasPaidLaunchApprovalPacket && typeof state.saasPaidLaunchApprovalPacket === "object" ? state.saasPaidLaunchApprovalPacket : {};
    const readyCount = Number(summary.ready_count || 0);
    const totalCount = Number(summary.total_count || 0);
    const blockedCount = Number(summary.blocked_count || 0);
    const drillReadyCount = Number(summary.hardening_drill_ready_count || drills.filter((item) => item && item.status === "ready").length || 0);
    const drillTotalCount = Number(summary.hardening_drill_total_count || drills.length || 0);
    const drillBlockedCount = Number(summary.hardening_drill_blocked_count || drills.filter((item) => item && item.status !== "ready").length || 0);
    const newAccountSmokeReadyCount = Number(summary.new_account_smoke_ready_count || newAccountSmoke.filter((item) => item && item.status === "ready").length || 0);
    const newAccountSmokeTotalCount = Number(summary.new_account_smoke_total_count || newAccountSmoke.length || 0);
    const newAccountSmokeBlockedCount = Number(summary.new_account_smoke_blocked_count || newAccountSmoke.filter((item) => item && item.status !== "ready").length || 0);
    const cutoverReadyCount = Number(summary.cutover_ready_count || cutover.filter((item) => item && item.status === "ready").length || 0);
    const cutoverTotalCount = Number(summary.cutover_total_count || cutover.length || 0);
    const cutoverBlockedCount = Number(summary.cutover_blocked_count || cutover.filter((item) => item && item.status !== "ready").length || 0);
    const deferredSummary = deferredStrategy.summary && typeof deferredStrategy.summary === "object" ? deferredStrategy.summary : {};
    const autonomousReadyCount = Number(summary.autonomous_internal_ready_count || deferredSummary.autonomous_internal_ready_count || 0);
    const autonomousTotalCount = Number(summary.autonomous_internal_total_count || deferredSummary.autonomous_internal_total_count || 0);
    const deferredExternalCount = Number(summary.deferred_external_count || deferredSummary.external_deferred_count || 0);
    const paidReady = Boolean(launchGate.paid_commercial_launch_ready || plan.public_paid_launch_ready);
    const topBlockers = Array.isArray(summary.top_blockers) ? summary.top_blockers : [];
    const fallbackSections = sections.length ? sections : _fallbackLaunchSections(launchGate);
    return `
      <section class="saas-settings-card saas-launch-action-plan">
        <div class="saas-settings-card-head">
          <div>
            <span>正式上线行动清单</span>
            <strong>${paidReady ? "付费公开上线门禁通过" : "可以继续私测和硬化，暂不公开收费"}</strong>
            <p>这里把正式上线差口拆成可执行事项：谁负责、证据是什么、下一步做什么。没有证据的项保持阻断，不用口头判断替代门禁。</p>
          </div>
        </div>
        <div class="saas-settings-status-list">
          <article class="${paidReady ? "is-green" : "is-amber"}">
            <span>当前阶段</span>
            <strong>${escape(plan.current_phase || (paidReady ? "paid_public_ready" : "private_beta_hardening"))}</strong>
            <small>${escape(summary.plain_status || (paidReady ? "可公开收费上线" : "仍不能公开收费上线"))}</small>
          </article>
          <article class="${blockedCount ? "is-amber" : "is-green"}">
            <span>行动项进度</span>
            <strong>${readyCount}/${totalCount || "?"}</strong>
            <small>${blockedCount} 个阻断项需要补齐</small>
          </article>
          <article class="${topBlockers.length ? "is-amber" : "is-green"}">
            <span>最高优先级</span>
            <strong>${escape(topBlockers[0] || "无")}</strong>
            <small>${escape(topBlockers.slice(1, 4).join(" / ") || "继续保持 evidence 更新")}</small>
          </article>
          <article class="${drillBlockedCount ? "is-amber" : "is-green"}">
            <span>上线演练</span>
            <strong>${drillReadyCount}/${drillTotalCount || "?"}</strong>
            <small>${escape(summary.next_drill || (drillBlockedCount ? "commercial_hardening_drills" : "all_drills_ready"))}</small>
          </article>
          <article class="${newAccountSmokeBlockedCount ? "is-amber" : "is-green"}">
            <span>new eBay smoke</span>
            <strong>${newAccountSmokeReadyCount}/${newAccountSmokeTotalCount || "?"}</strong>
            <small>${escape(summary.next_new_account_smoke_step || (newAccountSmokeBlockedCount ? "new_ebay_account_smoke_runbook" : "new_account_smoke_ready"))}</small>
          </article>
          <article class="${cutoverBlockedCount ? "is-amber" : "is-green"}">
            <span>清绿表</span>
            <strong>${cutoverReadyCount}/${cutoverTotalCount || "?"}</strong>
            <small>${escape(summary.next_cutover_item || (cutoverBlockedCount ? "paid_launch_cutover_checklist" : "cutover_ready"))}</small>
          </article>
          <article class="${deferredExternalCount ? "is-amber" : "is-green"}">
            <span>prelaunch_deferred_strategy</span>
            <strong>${autonomousReadyCount}/${autonomousTotalCount || "?"}</strong>
            <small>external_deferred=${deferredExternalCount} / ${escape(summary.autonomous_internal_next_step || deferredSummary.next_autonomous_internal_step || "autonomous_internal_prelaunch_work")}</small>
          </article>
        </div>
        ${Object.keys(deferredStrategy).length ? _renderPrelaunchDeferredStrategy(deferredStrategy) : ""}
        ${Object.keys(approvalPacket).length ? _renderPaidLaunchApprovalPacket(approvalPacket) : ""}
        ${Object.keys(cutoverDecision).length ? _renderPaidLaunchCutoverDecision(cutoverDecision) : ""}
        ${drills.length
          ? `
            <div class="saas-settings-row-list saas-commercial-hardening-drills">
              <article>
                <div>
                  <span>正式商用硬化演练</span>
                  <strong>${drillReadyCount}/${drillTotalCount} ready</strong>
                  <small>收费、稳定域名、店铺连接续期、账号健康、发布体检和最终 smoke 都要有证据；真实写入继续进入确认中心。</small>
                </div>
              </article>
              ${drills.map((item) => _renderCommercialHardeningDrill(item)).join("")}
            </div>
          `
          : ""}
        ${newAccountSmoke.length
          ? `
            <div class="saas-settings-row-list saas-new-ebay-smoke-runbook">
              <article class="${newAccountSmokeBlockedCount ? "is-amber" : "is-green"}">
                <div>
                  <span>new_ebay_account_smoke_runbook</span>
                  <strong>${newAccountSmokeReadyCount}/${newAccountSmokeTotalCount} ready</strong>
                  <small>Clean new account only: no old frozen account, no old SKU/image/report, no silent OAuth repeat, no real publish or cleanup outside confirmation center.</small>
                  <small>clean_new_account_declared / new_account_oauth_authorization_gate / post_publish_cockpit_cleanup_gate</small>
                </div>
                <em>smoke</em>
              </article>
              ${newAccountSmoke.map((item) => _renderNewEbayAccountSmokeStep(item)).join("")}
            </div>
          `
          : ""}
        ${cutover.length
          ? `
            <div class="saas-settings-row-list saas-paid-launch-cutover-checklist">
              <article>
                <div>
                  <span>公开收费清绿表</span>
                  <strong>${cutoverReadyCount}/${cutoverTotalCount} ready</strong>
                  <small>这里只列证据、环境变量名和验证入口；不展示密钥值，不触发真实扣款，也不触发真实 eBay 写入。</small>
                </div>
              </article>
              ${cutover.map((item) => _renderPaidLaunchCutoverItem(item)).join("")}
            </div>
          `
          : ""}
        ${fallbackSections
          .map(
            (section) => `
              <div class="saas-settings-row-list">
                <article>
                  <div>
                    <span>${escape(section.label || section.key || "上线事项")}</span>
                    <strong>${escape(_sectionProgress(section))}</strong>
                    <small>正式收费上线前逐项清绿；涉及真实写入、账号风险和收费的动作继续走确认中心。</small>
                  </div>
                </article>
                ${(Array.isArray(section.items) ? section.items : [])
                  .map((item) => _renderLaunchActionItem(item))
                  .join("")}
              </div>
            `,
          )
          .join("")}
      </section>
    `;
  }

  function _renderPrelaunchDeferredStrategy(strategy) {
    const summary = strategy.summary && typeof strategy.summary === "object" ? strategy.summary : {};
    const external = Array.isArray(strategy.external_deferred_items) ? strategy.external_deferred_items : [];
    const internal = Array.isArray(strategy.autonomous_internal_work) ? strategy.autonomous_internal_work : [];
    const safety = strategy.safety_contract && typeof strategy.safety_contract === "object" ? strategy.safety_contract : {};
    const readyCount = Number(summary.autonomous_internal_ready_count || internal.filter((item) => item && item.status === "ready").length || 0);
    const totalCount = Number(summary.autonomous_internal_total_count || internal.length || 0);
    const flags = [
      `can_continue_without_payment=${Boolean(strategy.can_continue_without_payment)}`,
      `can_continue_without_new_ebay_account=${Boolean(strategy.can_continue_without_new_ebay_account)}`,
      `triggers_real_charge=${Boolean(safety.triggers_real_charge)}`,
      `triggers_ebay_oauth=${Boolean(safety.triggers_ebay_oauth)}`,
      `triggers_real_platform_write=${Boolean(safety.triggers_real_platform_write)}`,
      `frontend_gets_secret=${Boolean(safety.frontend_gets_secret)}`,
    ];
    return `
      <div class="saas-settings-row-list saas-prelaunch-deferred-strategy">
        <article class="${external.length ? "is-amber" : "is-green"}">
          <div>
            <span>prelaunch_deferred_strategy</span>
            <strong>${readyCount}/${totalCount || "?"} autonomous_internal_prelaunch_work ready</strong>
            <small>${escape(summary.plain_status || "Formal payment and clean eBay real validation are deferred; internal hardening continues.")}</small>
            <small>formal_payment_deferred=${Boolean(strategy.formal_payment_deferred)} / clean_ebay_account_validation_deferred=${Boolean(strategy.clean_ebay_account_validation_deferred)}</small>
            <small>${escape(flags.join(" / "))}</small>
          </div>
          <em>${external.length ? "deferred" : "ready"}</em>
        </article>
        <article class="${external.length ? "is-amber" : "is-green"}">
          <div>
            <span>external_deferred_items</span>
            <strong>${external.length} deferred</strong>
            <small>${escape(external.map((item) => item?.key).filter(Boolean).join(" / ") || "none")}</small>
          </div>
          <em>owner</em>
        </article>
        ${external.map((item) => _renderPrelaunchStrategyItem(item, "external")).join("")}
        <article class="${readyCount === totalCount && totalCount ? "is-green" : "is-amber"}">
          <div>
            <span>autonomous_internal_prelaunch_work</span>
            <strong>${readyCount}/${totalCount || "?"} ready</strong>
            <small>${escape(summary.next_autonomous_internal_step || "continue_evidence_capture")}</small>
          </div>
          <em>internal</em>
        </article>
        ${internal.map((item) => _renderPrelaunchStrategyItem(item, "internal")).join("")}
      </div>
    `;
  }

  function _renderPrelaunchStrategyItem(item, type) {
    const ready = item && item.status === "ready";
    const deferred = item && item.status === "deferred";
    const verification = Array.isArray(item?.verification) ? item.verification.slice(0, 4) : [];
    const flags = [
      `can_continue_without_payment=${Boolean(item?.can_continue_without_payment)}`,
      `can_continue_without_new_ebay_account=${Boolean(item?.can_continue_without_new_ebay_account)}`,
      `triggers_real_charge=${Boolean(item?.triggers_real_charge)}`,
      `triggers_ebay_oauth=${Boolean(item?.triggers_ebay_oauth)}`,
      `triggers_real_platform_write=${Boolean(item?.triggers_real_platform_write)}`,
      `secret_exposed=${Boolean(item?.secret_exposed)}`,
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.key || `${type}_prelaunch_item`)}</span>
          <strong>${escape(item?.title || "Prelaunch evidence item")}</strong>
          <small>status=${escape(item?.status || "pending")} / owner=${escape(item?.owner || "platform_ops")} / category=${escape(item?.category || type)}</small>
          <small>${escape(item?.evidence_summary || "")}</small>
          <small>${escape(flags.join(" / "))}</small>
          <small>${escape(verification.join(" / ") || item?.next_action || "")}</small>
        </div>
        <em>${deferred ? "deferred" : ready ? "ready" : "todo"}</em>
      </article>
    `;
  }

  function _renderPaidLaunchApprovalPacket(packet) {
    const summary = packet.summary && typeof packet.summary === "object" ? packet.summary : {};
    const steps = Array.isArray(packet.steps) ? packet.steps : [];
    const external = Array.isArray(packet.external_configuration_needed) ? packet.external_configuration_needed : [];
    const commands = Array.isArray(packet.final_rehearsal_commands) ? packet.final_rehearsal_commands.slice(0, 4) : [];
    const readyCount = Number(summary.ready_count || steps.filter((item) => item && item.status === "ready").length || 0);
    const totalCount = Number(summary.total_count || steps.length || 0);
    const blockedCount = Number(summary.blocked_count || steps.filter((item) => item && item.status !== "ready").length || 0);
    const allowed = Boolean(packet.ready_for_owner_approval);
    const flags = [
      `mode=${packet.mode || "owner_approval_packet_no_charge_no_write"}`,
      `charge_now_allowed=${Boolean(packet.charge_now_allowed)}`,
      `creates_checkout_session=${Boolean(packet.creates_checkout_session)}`,
      `calls_stripe_api=${Boolean(packet.calls_stripe_api)}`,
      `triggers_ebay_oauth=${Boolean(packet.triggers_ebay_oauth)}`,
      `triggers_real_platform_write=${Boolean(packet.triggers_real_platform_write)}`,
      `frontend_gets_payment_secret=${Boolean(packet.frontend_gets_payment_secret)}`,
    ];
    return `
      <div class="saas-settings-row-list saas-paid-launch-approval-packet">
        <article class="${allowed ? "is-green" : "is-amber"}">
          <div>
            <span>paid_launch_approval_packet</span>
            <strong>${readyCount}/${totalCount || "?"} ready</strong>
            <small>${escape(summary.next_step || (blockedCount ? "external_evidence_required" : "ready_for_owner_approval"))}</small>
            <small>stable_domain_hardening / wechat_pay_native_cutover / no_charge_launch_rehearsal / new_ebay_account_low_risk_smoke</small>
            <small>${escape(flags.join(" / "))}</small>
          </div>
          <em>${allowed ? "approval" : "blocked"}</em>
        </article>
        <article class="${external.filter((item) => item && item.status !== "ready").length ? "is-amber" : "is-green"}">
          <div>
            <span>external_configuration_needed</span>
            <strong>${external.filter((item) => item && item.status === "ready").length}/${external.length || "?"} ready</strong>
            <small>${escape(external.map((item) => item?.key).filter(Boolean).join(" / ") || "none")}</small>
            <small>secret_values_required_in_backend_only=true / frontend_gets_secret=false</small>
          </div>
          <em>owner</em>
        </article>
        <article>
          <div>
            <span>final_rehearsal_commands</span>
            <strong>${commands.length} checks</strong>
            <small>${escape(commands.join(" / ") || "no_commands")}</small>
          </div>
          <em>verify</em>
        </article>
        ${steps.map((step) => _renderPaidLaunchApprovalStep(step)).join("")}
        ${external.map((item) => _renderPaidLaunchExternalItem(item)).join("")}
      </div>
    `;
  }

  function _renderPaidLaunchApprovalStep(step) {
    const ready = step && step.status === "ready";
    const verification = Array.isArray(step?.verification) ? step.verification.slice(0, 3) : [];
    const blockedBy = Array.isArray(step?.blocked_by) ? step.blocked_by.slice(0, 4) : [];
    const flags = [
      step?.external_resource_required ? "external_resource" : "internal_evidence",
      step?.creates_checkout_session ? "would_create_checkout" : "no_checkout_created",
      step?.calls_stripe_api ? "would_call_stripe" : "no_stripe_call",
      step?.triggers_real_charge ? "would_charge" : "no_charge",
      step?.triggers_ebay_oauth ? "would_oauth" : "no_oauth",
      step?.triggers_real_platform_write ? "would_write" : "no_platform_write",
      step?.secret_exposed ? "secret_risk" : "secret_exposed_false",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(step?.owner || "platform_ops")} / ${escape(step?.category || "paid_launch")}</span>
          <strong>${escape(step?.title || step?.key || "paid_launch_approval_step")}</strong>
          <small>${escape(step?.evidence_summary || "waiting_for_approval_evidence")}</small>
          <small>${escape(step?.next_action || "continue_collecting_launch_evidence")}</small>
          <small>${escape(blockedBy.join(" / ") || "not_blocked")}</small>
          <small>${escape(verification.join(" / ") || "manual_verification_required")}</small>
          <small>${escape(flags.join(" / "))}</small>
        </div>
        <em>${ready ? "ready" : "blocked"}</em>
      </article>
    `;
  }

  function _renderPaidLaunchExternalItem(item) {
    const ready = item && item.status === "ready";
    const envKeys = Array.isArray(item?.environment_keys) ? item.environment_keys.slice(0, 6) : [];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${item?.external_resource_required ? "owner_external_config" : "operator_evidence"}</span>
          <strong>${escape(item?.title || item?.key || "external_configuration_item")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_external_configuration")}</small>
          <small>${escape(envKeys.join(" / ") || "no_env_keys_required")}${item?.environment_keys?.length > envKeys.length ? " / ..." : ""}</small>
          <small>secret_values_required_in_backend_only=${escape(Boolean(item?.secret_values_required_in_backend_only))} / frontend_gets_secret=${escape(Boolean(item?.frontend_gets_secret))}</small>
        </div>
        <em>${ready ? "ready" : "blocked"}</em>
      </article>
    `;
  }

  function _renderLaunchActionItem(item) {
    const ready = item && item.status === "ready";
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "平台")}</span>
          <strong>${escape(item?.title || item?.key || "上线事项")}</strong>
          <small>${escape(item?.evidence_summary || "等待证据")}</small>
          <small>${escape(item?.next_action || "继续补齐证据和回归检查。")}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderCommercialHardeningDrill(item) {
    const ready = item && item.status === "ready";
    const needsConfirmation = Boolean(item?.requires_confirmation_center);
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "platform")}</span>
          <strong>${escape(item?.title || item?.key || "commercial_hardening_drill")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_evidence")}</small>
          <small>${escape(item?.next_action || "continue_hardening_and_collect_evidence")}</small>
          <small>${needsConfirmation ? "真实执行必须进入确认中心" : "不触发真实写入或扣款"}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderNewEbayAccountSmokeStep(item) {
    const ready = item && item.status === "ready";
    const verification = Array.isArray(item?.verification) ? item.verification.slice(0, 3) : [];
    const flags = [
      item?.requires_clean_new_ebay_account ? "clean_new_account" : "account_unverified",
      item?.old_frozen_account_reuse_allowed ? "old_account_allowed" : "old_account_forbidden",
      item?.old_demo_product_or_sku_allowed ? "old_demo_allowed" : "fresh_product_required",
      item?.triggers_ebay_oauth ? "would_oauth" : "no_oauth_started",
      item?.repeat_oauth_allowed ? "repeat_oauth_allowed" : "repeat_oauth_forbidden",
      item?.real_platform_write_step ? "real_write_step" : "read_only_step",
      item?.confirmation_center_required ? "confirmation_center" : "operator_check",
      item?.secret_exposed ? "secret_risk" : "secret_exposed_false",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "platform")} · ${escape(item?.category || "new_account_smoke")}</span>
          <strong>${escape(item?.title || item?.key || "new_ebay_account_smoke_step")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_new_account_smoke_evidence")}</small>
          <small>${escape(item?.next_action || "continue_collecting_new_account_smoke_evidence")}</small>
          <small>${escape(verification.join(" / ") || "manual_verification_required")}</small>
          <small>${escape(flags.join(" · "))}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderPaidLaunchCutoverItem(item) {
    const ready = item && item.status === "ready";
    const envKeys = Array.isArray(item?.environment_keys) ? item.environment_keys.slice(0, 4) : [];
    const verification = Array.isArray(item?.verification) ? item.verification.slice(0, 3) : [];
    const flags = [
      item?.external_resource_required ? "needs_external_resource" : "internal_evidence",
      item?.confirmation_center_required ? "confirmation_center" : "operator_check",
      item?.triggers_real_charge ? "would_charge" : "no_charge",
      item?.triggers_real_platform_write ? "would_write" : "no_platform_write",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "platform")} · ${escape(item?.category || "cutover")}</span>
          <strong>${escape(item?.title || item?.key || "paid_launch_cutover_item")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_cutover_evidence")}</small>
          <small>${escape(item?.next_action || "continue_collecting_paid_launch_evidence")}</small>
          <small>${escape(envKeys.join(" / ") || "no_env_keys_required")}${item?.environment_keys?.length > envKeys.length ? " / ..." : ""}</small>
          <small>${escape(verification.join(" / ") || "manual_verification_required")}</small>
          <small>${escape(flags.join(" · "))}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderPaidLaunchCutoverDecision(decision) {
    const allowed = Boolean(decision?.public_paid_launch_allowed);
    const next = decision?.next_operator_step && typeof decision.next_operator_step === "object" ? decision.next_operator_step : {};
    const nextRunbook = decision?.next_runbook_step && typeof decision.next_runbook_step === "object" ? decision.next_runbook_step : {};
    const rollback = Array.isArray(decision?.rollback_plan) ? decision.rollback_plan.slice(0, 4) : [];
    const evidence = Array.isArray(decision?.evidence_to_record) ? decision.evidence_to_record.slice(0, 5) : [];
    const lanes = Array.isArray(decision?.lanes) ? decision.lanes : [];
    const runbook = Array.isArray(decision?.billing_domain_cutover_runbook) ? decision.billing_domain_cutover_runbook : [];
    const runbookReadyCount = Number(decision?.runbook_ready_count || runbook.filter((item) => item && item.status === "ready").length || 0);
    const runbookTotalCount = Number(decision?.runbook_total_count || runbook.length || 0);
    const runbookBlockedCount = Number(decision?.runbook_blocked_count || runbook.filter((item) => item && item.status !== "ready").length || 0);
    const nextKeys = Array.isArray(next.environment_keys) ? next.environment_keys.slice(0, 4) : [];
    return `
      <div class="saas-settings-row-list saas-paid-launch-cutover-decision">
        <article class="${allowed ? "is-green" : "is-amber"}">
          <div>
            <span>paid launch decision</span>
            <strong>${escape(decision?.status || "blocked")}</strong>
            <small>${allowed ? "owner approval is still required before public charging" : "public charging remains blocked until evidence is green"}</small>
            <small>charge_now_allowed=${escape(Boolean(decision?.charge_now_allowed))} / platform_write_now_allowed=${escape(Boolean(decision?.platform_write_now_allowed))} / repeat_oauth=${escape(Boolean(decision?.repeat_ebay_oauth_allowed))}</small>
          </div>
          <em>${allowed ? "approval" : "blocked"}</em>
        </article>
        <article class="${next.key ? "is-amber" : "is-green"}">
          <div>
            <span>${escape(next.owner || "release_manager")} / ${escape(next.category || "release")}</span>
            <strong>${escape(next.title || next.key || "owner_approval")}</strong>
            <small>${escape(next.next_action || "collect_cutover_evidence")}</small>
            <small>${escape(nextKeys.join(" / ") || "no_env_keys_required")}</small>
          </div>
          <em>next</em>
        </article>
        <article>
          <div>
            <span>rollback plan</span>
            <strong>${rollback.length} checkpoints</strong>
            <small>${escape(rollback.join(" / ") || "rollback_plan_missing")}</small>
          </div>
          <em>safe</em>
        </article>
        <article>
          <div>
            <span>audit evidence</span>
            <strong>${evidence.length} records</strong>
            <small>${escape(evidence.join(" / ") || "evidence_required")}</small>
          </div>
          <em>audit</em>
        </article>
        ${lanes.map((lane) => _renderPaidLaunchCutoverLane(lane)).join("")}
        ${runbook.length
          ? `
            <article class="saas-paid-launch-runbook ${runbookBlockedCount ? "is-amber" : "is-green"}">
              <div>
                <span>billing_domain_cutover_runbook</span>
                <strong>${runbookReadyCount}/${runbookTotalCount} ready</strong>
                <small>${escape(nextRunbook.key || (runbookBlockedCount ? "runbook_evidence_required" : "runbook_ready"))}</small>
                <small>WeChat Native、稳定域名、签名回调、OAuth/CORS 对齐和回滚证据未证明前保持阻塞。</small>
                <small>wechat_pay_signed_callback_resilience / stable_domain_oauth_cors_alignment</small>
              </div>
              <em>runbook</em>
            </article>
            ${runbook.map((item) => _renderPaidLaunchRunbookStep(item)).join("")}
          `
          : ""}
      </div>
    `;
  }

  function _renderPaidLaunchCutoverLane(lane) {
    const ready = lane && lane.status === "ready";
    const blocked = Array.isArray(lane?.blocked_keys) ? lane.blocked_keys : [];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>lane</span>
          <strong>${escape(lane?.category || "cutover")}</strong>
          <small>${escape(`${Number(lane?.ready_count || 0)}/${Number(lane?.total_count || 0)} ready`)}</small>
          <small>${escape(blocked.join(" / ") || "lane_ready")}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _renderPaidLaunchRunbookStep(item) {
    const ready = item && item.status === "ready";
    const envKeys = Array.isArray(item?.environment_keys) ? item.environment_keys.slice(0, 4) : [];
    const verification = Array.isArray(item?.verification) ? item.verification.slice(0, 2) : [];
    const docs = Array.isArray(item?.docs) ? item.docs.slice(0, 2) : [];
    const flags = [
      item?.triggers_real_charge ? "would_charge" : "no_charge",
      item?.triggers_real_platform_write ? "would_write" : "no_platform_write",
      item?.triggers_ebay_oauth ? "would_oauth" : "no_ebay_oauth",
      item?.repeat_oauth_allowed === false ? "repeat_oauth_forbidden" : "repeat_oauth_not_required",
    ];
    return `
      <article class="${ready ? "is-green" : "is-amber"}">
        <div>
          <span>${escape(item?.owner || "platform")} 路 ${escape(item?.category || "runbook")}</span>
          <strong>${escape(item?.title || item?.key || "billing_domain_cutover_runbook_step")}</strong>
          <small>${escape(item?.evidence_summary || "waiting_for_runbook_evidence")}</small>
          <small>${escape(item?.next_action || "continue_collecting_billing_domain_evidence")}</small>
          <small>${escape(envKeys.join(" / ") || "no_env_keys_required")}${item?.environment_keys?.length > envKeys.length ? " / ..." : ""}</small>
          <small>${escape(verification.join(" / ") || "manual_verification_required")}</small>
          <small>${escape(docs.join(" / ") || "project_runbook")}</small>
          <small>${escape(flags.join(" 路 "))}</small>
        </div>
        <em>${escape(ready ? "ready" : "blocked")}</em>
      </article>
    `;
  }

  function _sectionProgress(section) {
    const items = Array.isArray(section.items) ? section.items : [];
    const ready = items.filter((item) => item && item.status === "ready").length;
    return `${ready}/${items.length} ready`;
  }

  function _fallbackLaunchSections(launchGate) {
    const groups = Array.isArray(launchGate.groups) ? launchGate.groups : [];
    return [
      {
        key: "commercial_launch_gate",
        label: "商业上线门禁",
        items: groups.map((group) => ({
          key: group.key,
          title: group.label || group.key,
          owner: "平台",
          status: group.status,
          next_action: group.next_action,
          evidence_summary: group.key,
        })),
      },
    ];
  }

  global.JiejingSettingsPanels = Object.freeze({
    renderBillingProviderPanel,
    renderCommercialLaunchActionPlanPanel,
    renderEdgeCutoverReadinessPanel,
    renderPublicSecurityStatusPanel,
    renderQueueHealthPanel,
  });
})(window);
