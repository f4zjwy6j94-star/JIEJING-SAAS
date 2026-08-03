(() => {
  "use strict";

  const VIEW_TITLES = {
    overview: "经营总览",
    traffic: "流量与转化",
    merchants: "商家与订阅",
    transactions: "交易与退款",
    costs: "AI 与素材成本",
    workflows: "任务与工作流",
    feedback: "产品反馈",
    reliability: "系统可靠性",
    audit: "安全与审计",
    settings: "内部设置",
  };

  const DETAIL_VIEWS = new Set(["traffic", "merchants", "transactions", "costs", "workflows", "feedback", "audit"]);
  const state = {
    view: "overview",
    period: 30,
    overview: null,
    details: new Map(),
    loading: false,
    identity: null,
  };

  const elements = {
    login: document.querySelector("#ops-login"),
    loginForm: document.querySelector("#ops-login-form"),
    loginStatus: document.querySelector("#ops-login-status"),
    denied: document.querySelector("#ops-denied"),
    deniedLogout: document.querySelector("#ops-denied-logout"),
    app: document.querySelector("#ops-app"),
    nav: document.querySelector("#ops-nav"),
    title: document.querySelector("#ops-title"),
    content: document.querySelector("#ops-content"),
    alert: document.querySelector("#ops-alert"),
    dataStatus: document.querySelector("#ops-data-status"),
    updatedAt: document.querySelector("#ops-updated-at"),
    refresh: document.querySelector("#ops-refresh"),
    identity: document.querySelector("#ops-identity"),
    logout: document.querySelector("#ops-logout"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatNumber(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? new Intl.NumberFormat("zh-CN").format(numeric) : "-";
  }

  function formatMoney(minor, currency = "CNY") {
    const numeric = Number(minor);
    if (!Number.isFinite(numeric)) return "-";
    return new Intl.NumberFormat("zh-CN", {
      style: "currency",
      currency: currency || "CNY",
      minimumFractionDigits: 2,
    }).format(numeric / 100);
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function statusLabel(value) {
    const key = String(value || "unknown").toLowerCase();
    const labels = {
      active: "生效",
      paid: "已支付",
      pending: "待处理",
      pending_payment: "待支付",
      refunded: "已退款",
      refund_processing: "退款处理中",
      refund_review_requested: "退款待审核",
      failed: "失败",
      completed: "已完成",
      running: "进行中",
      queued: "排队中",
      open: "待处理",
      reviewing: "处理中",
      resolved: "已解决",
      ready: "正常",
      partial: "数据不完整",
      unavailable: "暂无数据",
      actual: "实际",
      reconciled: "已对账",
      configured_estimate: "配置估算",
      not_applicable: "不适用",
      recorded: "已记录",
      merchant: "商家",
      owner: "主理人",
      admin: "管理员",
      free: "免费版",
      none: "未订阅",
    };
    return labels[key] || String(value || "未知");
  }

  function statusClass(value) {
    const key = String(value || "").toLowerCase();
    if (/failed|critical|error|revoked|blocked/.test(key)) return "is-critical";
    if (/pending|partial|attention|unavailable|timeout|processing|review/.test(key)) return "is-attention";
    if (/ready|active|paid|completed|actual|reconciled|success|recorded/.test(key)) return "is-ready";
    return "";
  }

  function pill(value, label = statusLabel(value)) {
    return `<span class="ops-pill ${statusClass(value)}">${escapeHtml(label)}</span>`;
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || 15000);
    try {
      const response = await fetch(path, {
        method: options.method || "GET",
        credentials: "include",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
      let payload = {};
      try { payload = await response.json(); } catch (_) { payload = {}; }
      if (!response.ok) {
        const error = new Error(payload.error || payload.message || `请求失败 (${response.status})`);
        error.status = response.status;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") throw new Error("请求超时，请稍后重试");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function setScreen(screen) {
    elements.login.hidden = screen !== "login";
    elements.denied.hidden = screen !== "denied";
    elements.app.hidden = screen !== "app";
  }

  function setLoading(loading, copy = "正在读取真实数据") {
    state.loading = loading;
    elements.refresh.classList.toggle("is-loading", loading);
    elements.refresh.disabled = loading;
    elements.content.querySelectorAll("[data-filter], [data-load-more], [data-feedback-action]").forEach((control) => {
      control.disabled = loading;
    });
    elements.dataStatus.textContent = copy;
  }

  function showAlert(message) {
    elements.alert.textContent = message || "";
    elements.alert.hidden = !message;
  }

  function showSkeleton() {
    elements.content.innerHTML = `<div class="ops-metrics">${Array.from({ length: 4 }, () => '<div class="ops-skeleton"></div>').join("")}</div><div class="ops-skeleton"></div>`;
  }

  function showDetailLoadFailure(view) {
    const title = VIEW_TITLES[view] || "下钻数据";
    elements.content.innerHTML = `<div class="ops-empty">${escapeHtml(title)}暂时无法读取，请使用刷新按钮重试。</div>`;
  }

  function showFeedbackRefreshFailure() {
    elements.content.innerHTML = '<div class="ops-empty">反馈状态已更新，列表刷新失败，请使用刷新按钮重试。</div>';
  }

  async function authenticate() {
    try {
      const payload = await api("/permissions/me", { timeoutMs: 8000 });
      if (payload.platform_internal_admin !== true) {
        setScreen("denied");
        return false;
      }
      state.identity = payload;
      elements.identity.textContent = `${statusLabel(payload.role)} · 内部权限`;
      setScreen("app");
      return true;
    } catch (error) {
      if (error.status === 401) {
        setScreen("login");
        return false;
      }
      throw error;
    }
  }

  async function login(event) {
    event.preventDefault();
    const submit = elements.loginForm.querySelector("button[type='submit']");
    submit.disabled = true;
    elements.loginStatus.textContent = "正在验证账号";
    const form = new FormData(elements.loginForm);
    try {
      await api("/owner/auth/login", {
        method: "POST",
        body: { email: form.get("email"), password: form.get("password") },
        timeoutMs: 12000,
      });
      elements.loginForm.reset();
      elements.loginStatus.textContent = "";
      if (await authenticate()) await refreshAll();
    } catch (error) {
      elements.loginStatus.textContent = error.status === 401 ? "账号或密码不正确" : error.message;
    } finally {
      submit.disabled = false;
    }
  }

  async function logout() {
    try { await api("/auth/logout", { method: "POST", timeoutMs: 6000 }); } catch (_) { /* local state still clears */ }
    state.overview = null;
    state.details.clear();
    state.identity = null;
    setScreen("login");
  }

  function metric(label, value, note, tone = "") {
    return `<article class="ops-metric ${tone}"><span class="ops-metric-label">${escapeHtml(label)}</span><strong class="ops-metric-value">${escapeHtml(value)}</strong><span class="ops-metric-note">${escapeHtml(note)}</span></article>`;
  }

  function activeSubscriptionCount(subscriptions) {
    return (subscriptions || []).reduce((total, item) => total + (/active|paid/.test(String(item.status || "")) ? Number(item.count || 0) : 0), 0);
  }

  function paidConversion(overview) {
    const merchants = Number(overview?.accounts?.merchant_companies || 0);
    const paid = Number(overview?.unit_economics?.paid_company_count || 0);
    return merchants ? `${((paid / merchants) * 100).toFixed(1)}%` : "0.0%";
  }

  function feedbackModuleLabel(value) {
    const labels = {
      cockpit: "AI 主管工作台",
      workflow: "工作流",
      product: "选品与上架",
      bulk: "批量铺货",
      media: "素材工坊",
      confirm: "确认中心",
      service: "客服与物流",
      connect: "平台连接",
      activity: "AI 工作记录",
    };
    return labels[String(value || "").toLowerCase()] || String(value || "未知模块");
  }

  function feedbackReasonLabel(value) {
    const labels = {
      unclear: "这一步不清楚",
      wrong_result: "结果不对",
      missing_action: "缺一个动作",
    };
    return labels[String(value || "").toLowerCase()] || String(value || "未知原因");
  }

  function topFeedbackModule(byModule) {
    const entries = Object.entries(byModule || {})
      .map(([key, value]) => [key, Number(value || 0)])
      .filter(([, value]) => Number.isFinite(value) && value > 0)
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
    return entries.length ? feedbackModuleLabel(entries[0][0]) : "暂无集中模块";
  }

  function renderTrend(daily) {
    const rows = Array.isArray(daily) ? daily : [];
    if (!rows.length) return '<div class="ops-empty">当前时间范围没有流量趋势数据。</div>';
    const max = Math.max(1, ...rows.map((item) => Number(item.visitors || 0)));
    const bars = rows.map((item) => {
      const value = Number(item.visitors || 0);
      const height = Math.max(value ? 5 : 1, Math.round((value / max) * 100));
      return `<div class="ops-trend-column" title="${escapeHtml(item.day)} · ${formatNumber(value)} 位访客"><span style="height:${height}%"></span></div>`;
    }).join("");
    return `<div class="ops-trend">${bars}</div><div class="ops-trend-legend"><span>${escapeHtml(rows[0]?.day || "")}</span><span>${escapeHtml(rows.at(-1)?.day || "")}</span></div>`;
  }

  function renderFunnel(overview) {
    const traffic = overview.traffic_analytics || {};
    const values = [
      ["访问", Number(traffic.visitors || 0)],
      ["查看定价", Number(traffic.pricing_views || 0)],
      ["开始注册", Number(traffic.signup_started || 0)],
      ["完成注册", Number(traffic.signup_completed || 0)],
      ["成功付费商家", Number(overview.unit_economics?.paid_company_count || 0)],
    ];
    const max = Math.max(1, values[0][1]);
    return `<div class="ops-funnel">${values.map(([label, value]) => `<div class="ops-funnel-row"><span>${escapeHtml(label)}</span><div class="ops-funnel-track"><span style="width:${Math.min(100, (value / max) * 100)}%"></span></div><strong>${formatNumber(value)}</strong></div>`).join("")}</div>`;
  }

  function renderOverview() {
    const overview = state.overview || {};
    const traffic = overview.traffic_analytics || {};
    const economics = overview.unit_economics || {};
    const activeSubscriptions = activeSubscriptionCount(overview.subscriptions);
    const marginReady = economics.cost_coverage_complete === true;
    const alertSummary = overview.provider_reliability_analytics?.alerts || {};
    const openAlerts = Number(alertSummary.critical_count || 0) + Number(alertSummary.attention_count || 0);
    const feedback = overview.product_feedback || {};
    elements.content.innerHTML = `
      <div class="ops-metrics">
        ${metric("唯一访客", formatNumber(traffic.visitors), `${state.period} 天 · ${formatNumber(traffic.sessions)} 个会话`)}
        ${metric("注册商家", formatNumber(overview.accounts?.merchant_companies), `完成注册 ${formatNumber(traffic.signup_completed)} 次`)}
        ${metric("生效订阅", formatNumber(activeSubscriptions), `付费商家占比 ${paidConversion(overview)}`)}
        ${metric("平台实收", formatMoney(economics.paid_revenue_minor), `${formatNumber(economics.paid_order_count)} 笔商业订单`)}
        ${metric("标准化 MRR", formatMoney(economics.normalized_mrr_minor), economics.mrr_status === "ready" ? "有效订阅已覆盖" : "部分订阅缺付款依据", economics.mrr_status === "ready" ? "" : "is-attention")}
        ${metric("平台模型成本", formatMoney(economics.platform_model_cost_minor), "商家自带模型不计入捷境模型成本")}
        ${metric("素材与联网成本", formatMoney(economics.total_provider_cost_minor), marginReady ? "成本覆盖完整" : "仍有成本数据待补", marginReady ? "" : "is-attention")}
        ${metric("贡献毛利", marginReady ? formatMoney(economics.contribution_margin_minor) : "待补成本", marginReady ? "实收减已覆盖供应商成本" : "不会用缺失数据估算利润", marginReady ? "" : "is-attention")}
        ${metric("待处理告警", formatNumber(openAlerts), openAlerts ? "请进入系统可靠性查看" : "当前没有达到阈值的告警", openAlerts ? "is-critical" : "")}
        ${metric("待处理反馈", formatNumber(feedback.open), `待处理 ${formatNumber(feedback.open)} · 处理中 ${formatNumber(feedback.reviewing)} · 已解决 ${formatNumber(feedback.resolved)} · 主要集中：${topFeedbackModule(feedback.by_module)}`, Number(feedback.open) ? "is-attention" : "")}
      </div>
      <div class="ops-grid-two">
        <section class="ops-panel"><div class="ops-section-head"><div><h2>访客趋势</h2><p>按日去重访客，只统计允许列表事件。</p></div>${pill(traffic.status, traffic.status === "instrumented" ? "已采集" : "暂无事件")}</div>${renderTrend(traffic.daily_trend)}</section>
        <section class="ops-panel"><div class="ops-section-head"><div><h2>转化漏斗</h2><p>访问到付费的真实事件和订单事实。</p></div></div>${renderFunnel(overview)}</section>
      </div>
      <section class="ops-panel">
        <div class="ops-section-head"><div><h2>数据质量</h2><p>测试账号、验收订单和未覆盖成本不计入正式经营指标。</p></div>${pill(marginReady ? "ready" : "partial", marginReady ? "成本覆盖完整" : "成本覆盖不完整")}</div>
        <dl class="ops-definition-list">
          <dt>测试账号排除</dt><dd>${formatNumber(overview.data_quality?.synthetic_test_accounts_excluded)} 个</dd>
          <dt>测试反馈排除</dt><dd>${formatNumber(overview.data_quality?.synthetic_test_feedback_excluded)} 条</dd>
          <dt>验收订单排除</dt><dd>${formatNumber(overview.data_quality?.acceptance_orders_excluded)} 笔</dd>
          <dt>当前未计量模型任务</dt><dd>${formatNumber(economics.current_unmetered_model_tasks)} 个</dd>
          <dt>未覆盖供应商成本</dt><dd>${formatNumber(economics.unknown_provider_cost_records)} 条</dd>
        </dl>
      </section>`;
  }

  function table(headers, rows, options = {}) {
    if (!rows.length) return '<div class="ops-empty">当前筛选条件下没有真实数据。</div>';
    const columnClass = (item) => [item.number ? "is-number" : "", item.className || ""].filter(Boolean).join(" ");
    const wrapClass = ["ops-table-wrap", options.className || ""].filter(Boolean).join(" ");
    const hintId = options.hintId || "";
    const hint = options.scrollHint ? `<p id="${escapeHtml(hintId)}" class="ops-table-scroll-hint">${escapeHtml(options.scrollHint)}</p>` : "";
    const regionAttributes = options.ariaLabel
      ? ` tabindex="0" role="region" aria-label="${escapeHtml(options.ariaLabel)}"${hintId ? ` aria-describedby="${escapeHtml(hintId)}"` : ""}`
      : "";
    return `${hint}<div class="${escapeHtml(wrapClass)}"${regionAttributes}><table class="ops-table"><thead><tr>${headers.map((item) => `<th class="${escapeHtml(columnClass(item))}">${escapeHtml(item.label)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((item) => `<td class="${escapeHtml(columnClass(item))}">${item.render ? item.render(row) : escapeHtml(row[item.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function detailPanel(title, copy, filters, body, detail) {
    const more = detail?.has_more ? '<div class="ops-pagination"><button type="button" data-load-more>加载更多</button></div>' : "";
    return `<section class="ops-panel"><div class="ops-section-head"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(copy)}</p></div><div class="ops-filter">${filters}</div></div>${body}${more}</section>`;
  }

  function selectFilter(name, label, options, selected = "") {
    return `<select data-filter="${escapeHtml(name)}" aria-label="${escapeHtml(label)}"><option value="">${escapeHtml(label)}</option>${options.map(([value, text]) => `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(text)}</option>`).join("")}</select>`;
  }

  function renderTraffic(detail) {
    const summary = detail.summary || {};
    const headers = [
      { key: "page_key", label: "页面" },
      { key: "visitors", label: "访客", number: true, render: (r) => formatNumber(r.visitors) },
      { key: "sessions", label: "会话", number: true, render: (r) => formatNumber(r.sessions) },
      { key: "page_views", label: "浏览", number: true, render: (r) => formatNumber(r.page_views) },
      { key: "signup_completed", label: "完成注册", number: true, render: (r) => formatNumber(r.signup_completed) },
    ];
    return `<div class="ops-metrics">${metric("访客", formatNumber(summary.visitors), `${state.period} 天`)}${metric("会话", formatNumber(summary.sessions), "随机会话标识去重")}${metric("页面浏览", formatNumber(summary.page_views), "不存完整 URL")}${metric("访问转注册", `${Number(summary.visitor_to_signup_percent || 0).toFixed(1)}%`, "完成注册访客 / 访客")}</div>${detailPanel("页面表现", "只展示允许列表页面的聚合数据。", "", table(headers, detail.items || []), detail)}`;
  }

  function renderMerchants(detail) {
    const filters = selectFilter("status", "全部状态", [["active", "订阅生效"], ["none", "未订阅"], ["pending", "待处理"]], detail.filters?.status || "");
    const headers = [
      { key: "company_name", label: "商家" },
      { key: "email_masked", label: "账号" },
      { key: "plan_key", label: "套餐", render: (r) => escapeHtml(statusLabel(r.plan_key)) },
      { key: "subscription_status", label: "订阅", render: (r) => pill(r.subscription_status) },
      { key: "store_count", label: "店铺", number: true, render: (r) => formatNumber(r.store_count) },
      { key: "last_active_at", label: "最近活动", render: (r) => formatDate(r.last_active_at) },
      { key: "company_ref", label: "脱敏引用" },
    ];
    return detailPanel("商家与订阅", "账号、套餐、权益和最近活动；邮箱已脱敏。", filters, table(headers, detail.items || []), detail);
  }

  function renderTransactions(detail) {
    const filters = selectFilter("status", "全部状态", [["paid", "已支付"], ["pending_payment", "待支付"], ["refund_review_requested", "退款待审核"], ["refunded", "已退款"], ["failed", "失败"]], detail.filters?.status || "") + selectFilter("category", "全部类型", [["subscription", "订阅"], ["media_credit", "素材额度"]], detail.filters?.category || "");
    const headers = [
      { key: "transaction_ref", label: "交易引用" },
      { key: "kind", label: "类型", render: (r) => escapeHtml(r.kind === "media_credit" ? "素材额度" : "订阅") },
      { key: "plan_key", label: "项目" },
      { key: "status", label: "状态", render: (r) => pill(r.status) },
      { key: "amount_minor", label: "金额", number: true, render: (r) => formatMoney(r.amount_minor, r.currency) },
      { key: "payment_channel", label: "支付渠道", render: (r) => escapeHtml(r.payment_channel === "domestic_payment" ? "国内支付" : "境外支付") },
      { key: "created_at", label: "创建时间", render: (r) => formatDate(r.created_at) },
    ];
    return detailPanel("平台交易", "这里只统计捷境订阅和素材额度，不包含商家的电商平台 GMV。", filters, table(headers, detail.items || []), detail);
  }

  function renderCosts(detail) {
    const filters = selectFilter("category", "全部成本", [["model", "模型"], ["media_generation", "素材生成"], ["public_search", "联网搜索"], ["payment_processing", "支付处理"]], detail.filters?.category || "") + selectFilter("status", "全部覆盖状态", [["actual", "实际"], ["reconciled", "已对账"], ["configured_estimate", "配置估算"], ["unavailable", "暂无成本"]], detail.filters?.status || "");
    const headers = [
      { key: "cost_ref", label: "成本引用" },
      { key: "category", label: "类别", render: (r) => escapeHtml({ model: "模型", media_generation: "素材生成", public_search: "联网搜索", payment_processing: "支付处理" }[r.category] || r.category) },
      { key: "resource_type", label: "资源" },
      { key: "usage_owner", label: "费用承担", render: (r) => escapeHtml(r.usage_owner === "merchant_account_byok" ? "商家自带" : r.usage_owner === "jiejing_platform_trial" ? "捷境试用" : "捷境供应商") },
      { key: "units", label: "用量", number: true, render: (r) => formatNumber(r.total_tokens ?? r.units ?? r.media_points) },
      { key: "cost_status", label: "覆盖", render: (r) => pill(r.cost_status) },
      { key: "cost_minor", label: "成本", number: true, render: (r) => formatMoney(r.cost_minor, r.currency) },
      { key: "created_at", label: "时间", render: (r) => formatDate(r.created_at) },
    ];
    return detailPanel("AI 与素材成本", "供应商保持中性显示；商家自带模型 token 不计入捷境模型成本。", filters, table(headers, detail.items || []), detail);
  }

  function renderWorkflows(detail) {
    const filters = selectFilter("status", "全部状态", [["completed", "已完成"], ["running", "进行中"], ["queued", "排队中"], ["failed", "失败"]], detail.filters?.status || "") + selectFilter("module", "全部模块", [["merchant_ceo", "AI CEO"], ["listing", "Listing"], ["bulk", "批量铺货"], ["media", "素材工坊"], ["confirmation", "决策中心"]], detail.filters?.module || "");
    const headers = [
      { key: "task_ref", label: "任务引用" },
      { key: "module", label: "模块" },
      { key: "status", label: "状态", render: (r) => pill(r.status) },
      { key: "job_count", label: "子任务", number: true, render: (r) => formatNumber(r.job_count) },
      { key: "attempt_count", label: "尝试次数", number: true, render: (r) => formatNumber(r.attempt_count) },
      { key: "created_at", label: "创建时间", render: (r) => formatDate(r.created_at) },
      { key: "updated_at", label: "更新时间", render: (r) => formatDate(r.updated_at) },
    ];
    return detailPanel("任务与工作流", "只显示状态和脱敏引用，不显示商家对话、商品或客户内容。", filters, table(headers, detail.items || []), detail);
  }

  function renderAudit(detail) {
    const filters = selectFilter("result", "全部结果", [["recorded", "已记录"], ["success", "成功"], ["failed", "失败"]], detail.filters?.result || "");
    const headers = [
      { key: "audit_ref", label: "审计引用" },
      { key: "actor_type", label: "操作者类型" },
      { key: "action_type", label: "动作" },
      { key: "target_type", label: "对象" },
      { key: "result", label: "结果", render: (r) => pill(r.result) },
      { key: "created_at", label: "时间", render: (r) => formatDate(r.created_at) },
    ];
    return detailPanel("安全与审计", "操作记录不包含密钥、token、原始请求或商家内容。", filters, table(headers, detail.items || []), detail);
  }

  function renderFeedback(detail) {
    const filters = selectFilter("status", "全部状态", [["open", "待处理"], ["reviewing", "处理中"], ["resolved", "已解决"]], detail.filters?.status || "")
      + selectFilter("module", "全部模块", [["cockpit", "AI 主管工作台"], ["workflow", "工作流"], ["product", "选品与上架"], ["bulk", "批量铺货"], ["media", "素材工坊"], ["confirm", "确认中心"], ["service", "客服与物流"], ["connect", "平台连接"], ["activity", "AI 工作记录"]], detail.filters?.module || "");
    const headers = [
      { key: "created_at", label: "提交时间", render: (r) => formatDate(r.created_at) },
      { key: "module_key", label: "模块", render: (r) => escapeHtml(feedbackModuleLabel(r.module_key)) },
      { key: "stage_title", label: "步骤" },
      { key: "reason", label: "原因", render: (r) => escapeHtml(feedbackReasonLabel(r.reason)) },
      { key: "detail", label: "清洗后的说明" },
      { key: "status", label: "状态", className: "ops-feedback-status-column", render: (r) => pill(r.status) },
      {
        key: "feedback_id",
        label: "处理",
        className: "ops-feedback-action-column",
        render: (r) => {
          if (r.status === "open") return `<button type="button" class="ops-button" data-feedback-action="review" data-feedback-id="${escapeHtml(r.feedback_id)}">开始处理</button>`;
          if (r.status === "reviewing") return `<button type="button" class="ops-button ops-button-primary" data-feedback-action="resolve" data-feedback-id="${escapeHtml(r.feedback_id)}">标记解决</button>`;
          return '<span class="ops-muted">已完成</span>';
        },
      },
    ];
    return detailPanel("商家产品反馈", "只展示经过服务端清洗的产品与流程反馈；处理动作仅更新捷境内部状态。", filters, table(headers, detail.items || [], {
      className: "ops-feedback-table-wrap",
      ariaLabel: "产品反馈明细，可横向滚动",
      hintId: "ops-feedback-scroll-hint",
      scrollHint: "左右滑动查看完整信息；状态与处理操作固定在右侧。",
    }), detail);
  }

  function renderReliability() {
    const overview = state.overview || {};
    const reliability = overview.provider_reliability_analytics || {};
    const labels = { model: "模型能力", public_search: "联网搜索", media_generation: "素材生成", payment: "支付链路" };
    const cards = Object.entries(labels).map(([key, label]) => {
      const item = reliability[key] || {};
      const total = Number(item.request_count || 0);
      const success = Number(item.success_count || 0);
      const successRate = total ? `${((success / total) * 100).toFixed(1)}%` : "暂无样本";
      return `<article class="ops-reliability-item"><header><strong>${escapeHtml(label)}</strong>${pill(item.status, item.status === "instrumented" ? "已采集" : "暂无样本")}</header><dl><div><dt>成功率</dt><dd>${escapeHtml(successRate)}</dd></div><div><dt>P75</dt><dd>${item.p75_duration_ms == null ? "-" : `${formatNumber(item.p75_duration_ms)} ms`}</dd></div><div><dt>超时</dt><dd>${formatNumber(item.timeout_count)}</dd></div></dl></article>`;
    }).join("");
    const alerts = reliability.alerts || {};
    elements.content.innerHTML = `<div class="ops-metrics">${metric("严重告警", formatNumber(alerts.critical_count), "达到严重阈值的链路", Number(alerts.critical_count) ? "is-critical" : "")}${metric("关注告警", formatNumber(alerts.attention_count), "需要观察或处理", Number(alerts.attention_count) ? "is-attention" : "")}${metric("模型计量健康", statusLabel(overview.model_cost_analytics?.current_metering_health), "只统计当前计量窗口")}${metric("页面性能样本", formatNumber(overview.performance_analytics?.sample_count), "真实浏览器性能采样")}</div><section class="ops-panel"><div class="ops-section-head"><div><h2>核心链路</h2><p>供应商中性指标；不记录原始错误、查询或回复。</p></div></div><div class="ops-reliability-list">${cards}</div></section>`;
  }

  function renderSettings() {
    const overview = state.overview || {};
    elements.content.innerHTML = `<section class="ops-panel"><div class="ops-section-head"><div><h2>后台边界</h2><p>经营数据只读，反馈处理只更新内部状态；高风险命令仍由确认中心和人工审批控制。</p></div>${pill("ready", "内部账号")}</div><dl class="ops-definition-list"><dt>统计范围</dt><dd>${escapeHtml(overview.data_quality?.scope || "商家账号与商业交易")}</dd><dt>商家导航</dt><dd>不显示运营后台入口</dd><dt>供应商显示</dt><dd>中性能力名称，不展示供应商品牌或密钥</dd><dt>流量隐私</dt><dd>不存 IP、完整 URL、查询参数、User-Agent 或浏览器指纹</dd><dt>商家内容</dt><dd>任务下钻不显示对话、商品、客户或原始模型内容</dd><dt>资金与平台写入</dt><dd>本后台不直接执行付款、退款、eBay 发布、改价、库存、广告、采购或政策修改</dd><dt>成本覆盖</dt><dd>${overview.unit_economics?.cost_coverage_complete ? "当前时间范围覆盖完整" : "当前仍有缺失项，不显示确定毛利"}</dd><dt>版本</dt><dd>${escapeHtml(overview.contract_version || "-")}</dd></dl></section>`;
  }

  function renderDetail(view) {
    const detail = state.details.get(view);
    if (!detail) { showSkeleton(); return; }
    const renderers = { traffic: renderTraffic, merchants: renderMerchants, transactions: renderTransactions, costs: renderCosts, workflows: renderWorkflows, feedback: renderFeedback, audit: renderAudit };
    elements.content.innerHTML = renderers[view](detail);
    bindDetailControls();
  }

  function renderCurrentView() {
    elements.title.textContent = VIEW_TITLES[state.view] || "经营总览";
    elements.nav.querySelectorAll("button[data-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.view === state.view));
    if (state.view === "overview") renderOverview();
    else if (state.view === "reliability") renderReliability();
    else if (state.view === "settings") renderSettings();
    else renderDetail(state.view);
  }

  async function loadOverview(force = false) {
    if (state.overview && !force) return;
    const payload = await api(`/owner/operations-overview?period_days=${state.period}`);
    state.overview = payload.operations_overview;
    if (!state.overview || state.overview.secret_exposed !== false) throw new Error("运营数据安全合同未通过");
  }

  async function loadDetail(view, filters = {}, append = false) {
    const existing = state.details.get(view);
    const query = new URLSearchParams({ period_days: String(state.period), limit: "50" });
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
    if (append && existing?.next_cursor) query.set("cursor", existing.next_cursor);
    const payload = await api(`/owner/operations/${encodeURIComponent(view)}?${query.toString()}`);
    const detail = payload.operations_detail;
    if (!detail || detail.secret_exposed !== false || detail.merchant_content_exposed === true) throw new Error("运营下钻安全合同未通过");
    if (view === "feedback" && (detail.raw_merchant_content_exposed !== false || detail.sanitized_feedback_text_internal_only !== true)) throw new Error("产品反馈清洗合同未通过");
    detail.filters = filters;
    if (append && existing) detail.items = [...(existing.items || []), ...(detail.items || [])];
    state.details.set(view, detail);
  }

  async function refreshAll() {
    if (state.loading) return;
    setLoading(true);
    showAlert("");
    showSkeleton();
    try {
      await loadOverview(true);
      state.details.clear();
      if (DETAIL_VIEWS.has(state.view)) await loadDetail(state.view);
      renderCurrentView();
      elements.updatedAt.textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date())}`;
      setLoading(false, "真实数据已更新");
    } catch (error) {
      if (error.status === 401) { setScreen("login"); return; }
      if (error.status === 403) { setScreen("denied"); return; }
      showAlert(error.message || "运营数据读取失败");
      setLoading(false, "部分数据暂不可用");
    }
  }

  async function switchView(view) {
    if (!VIEW_TITLES[view] || state.loading) return;
    state.view = view;
    showAlert("");
    if (DETAIL_VIEWS.has(view) && !state.details.has(view)) {
      setLoading(true, "正在读取下钻数据");
      showSkeleton();
      try {
        await loadDetail(view);
      } catch (error) {
        showAlert(error.message || "下钻数据读取失败");
        setLoading(false, "下钻数据读取失败");
        showDetailLoadFailure(view);
        return;
      }
      setLoading(false, "真实数据已更新");
    }
    renderCurrentView();
  }

  function bindDetailControls() {
    elements.content.querySelectorAll("[data-filter]").forEach((control) => {
      control.addEventListener("change", async () => {
        if (state.loading) return;
        const filters = {};
        elements.content.querySelectorAll("[data-filter]").forEach((item) => { if (item.value) filters[item.dataset.filter] = item.value; });
        setLoading(true, "正在应用筛选条件");
        try {
          await loadDetail(state.view, filters);
          showAlert("");
          setLoading(false, "筛选结果已更新");
          renderCurrentView();
        } catch (error) {
          showAlert(error.message || "筛选失败");
          setLoading(false, "筛选失败，结果未更新");
        }
      });
    });
    const more = elements.content.querySelector("[data-load-more]");
    if (more) more.addEventListener("click", async () => {
      if (state.loading) return;
      more.disabled = true;
      const filters = state.details.get(state.view)?.filters || {};
      setLoading(true, "正在加载更多记录");
      try {
        await loadDetail(state.view, filters, true);
        showAlert("");
        setLoading(false, "记录已更新");
        renderCurrentView();
      } catch (error) {
        showAlert(error.message || "加载更多失败");
        more.disabled = false;
        setLoading(false, "加载失败，记录未更新");
      }
    });
    elements.content.querySelectorAll("[data-feedback-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (state.loading) return;
        const action = button.dataset.feedbackAction;
        const feedbackId = button.dataset.feedbackId;
        const path = action === "review"
          ? "/owner/product-feedback/review"
          : action === "resolve"
            ? "/owner/product-feedback/resolve"
            : "";
        if (!path || !feedbackId) return;
        button.disabled = true;
        setLoading(true, action === "review" ? "正在开始处理反馈" : "正在标记反馈已解决");
        showAlert("");
        try {
          await api(path, { method: "POST", body: { feedback_id: feedbackId } });
        } catch (error) {
          showAlert(error.message || "反馈状态更新失败");
          button.disabled = false;
          setLoading(false, "反馈状态更新失败");
          return;
        }
        const filters = state.details.get("feedback")?.filters || {};
        try {
          await Promise.all([
            loadDetail("feedback", filters),
            loadOverview(true),
          ]);
          renderCurrentView();
          setLoading(false, "反馈状态已更新");
        } catch (_) {
          state.details.delete("feedback");
          showAlert("反馈状态已更新，列表刷新失败，请刷新");
          showFeedbackRefreshFailure();
          setLoading(false, "反馈状态已更新，列表待刷新");
        }
      });
    });
  }

  async function boot() {
    try {
      if (!(await authenticate())) return;
      showSkeleton();
      await refreshAll();
    } catch (error) {
      setScreen("login");
      elements.loginStatus.textContent = error.message || "运营后台暂时不可用";
    }
  }

  elements.loginForm.addEventListener("submit", login);
  elements.logout.addEventListener("click", logout);
  elements.deniedLogout.addEventListener("click", logout);
  elements.refresh.addEventListener("click", refreshAll);
  elements.nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (button) switchView(button.dataset.view);
  });
  document.querySelectorAll("[data-period]").forEach((button) => button.addEventListener("click", async () => {
    if (state.loading) return;
    state.period = Number(button.dataset.period || 30);
    document.querySelectorAll("[data-period]").forEach((item) => item.classList.toggle("is-active", item === button));
    await refreshAll();
  }));

  boot();
})();
