(function attachJiejingOpsPanels(global) {
"use strict";

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function safeStatus(value) {
  const normalized = String(value || "unknown").slice(0, 80);
  const key = normalized.toLowerCase();
  // Compound launch gates can contain both "ready" and "blocked". Unknown
  // future statuses must stay neutral instead of inheriting a success substring.
  const ready = new Set(["ready", "healthy", "ok", "green", "success", "succeeded", "complete", "completed", "passed", "available"]);
  const critical = /(^|_)(blocked|failed|failure|critical|red|unhealthy)(_|$)/.test(key);
  return { value: normalized, tone: critical ? "is-critical" : ready.has(key) ? "is-ready" : "is-attention" };
}

function safeList(value, limit = 8) {
  return (Array.isArray(value) ? value : []).filter((item) => item && typeof item === "object").slice(0, limit);
}

function evidenceCard(label, value, detail = "", evidenceKind = "") {
  const status = safeStatus(value);
  const labels = {ready: "已就绪", blocked: "受阻", attention_required: "需复核", unknown: "证据未提供", not_connected: "尚未接入", recorded: "历史已记录", info: "版本标识", private_beta_ready_public_launch_blocked: "内测就绪 · 公开门禁受阻", no_local_release_artifacts: "本地构建记录为空", ready_for_owner_approval: "待主理人批准"};
  const kindAttribute = evidenceKind ? ` data-evidence-kind="${escapeHtml(evidenceKind)}"` : "";
  return `<article class="ops-reliability-item ${status.tone}"${kindAttribute}><header><strong>${escapeHtml(label)}</strong><span class="ops-pill ${status.tone}" title="${escapeHtml(status.value)}">${escapeHtml(labels[status.value] || status.value)}</span></header><p>${escapeHtml(detail || "等待可验证证据")}</p></article>`;
}

function evidenceTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "证据时间未提供";
  return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "medium", hour12: false}).format(new Date(value)) + " 北京时间";
}

function evidenceNote(control) {
  return `<p class="ops-evidence-note">评估快照：${escapeHtml(evidenceTime(control?.generated_at))}。快照时间不是备份成功时间；缺失证据不代表服务宕机，历史验收不等于当前全部就绪。</p>`;
}

function issueList(items, empty = "本摘要未列出阻断项；不替代实时验收。") {
  const values = (Array.isArray(items) ? items : []).slice(0, 20);
  return values.length ? `<ul class="ops-evidence-issues">${values.map((item) => `<li>${escapeHtml(typeof item === "string" ? item : `${item.key || "unknown"}：${item.status || "unknown"}`)}</li>`).join("")}</ul>` : `<p>${escapeHtml(empty)}</p>`;
}

function renderLaunchAlignment(control) {
  const view = control.ops_console_evidence || {};
  const readiness = view.readiness || {};
  const release = view.release || {};
  const booleanStatus = (value) => value === true ? "ready" : value === false ? "blocked" : "unknown";
  return `<section class="ops-panel"><div class="ops-section-head"><div><h2>当前证据与历史交付</h2><p>产品是否就绪、服务是否健康、是否获准操作分别判断；首版历史交付不会因此重置。</p></div></div>${evidenceNote(control)}<div class="ops-reliability-list">${evidenceCard("当前生产就绪", booleanStatus(readiness.production_ready), "来自当前 readiness 的 production_ready；不是历史完成率。")}${evidenceCard("接待真实客户", booleanStatus(readiness.can_accept_real_customers), "来自 can_accept_real_customers；不授予收费或平台写入权限。")}${evidenceCard("当前代码版本", "info", release.frontend_asset_version || "当前接口未提供版本标识")}${evidenceCard("版本绑定历史证据", release.version_bound_evidence === true ? "recorded" : "unknown", "只证明记录与当前前端版本相符，不代替当前服务探针。")}${evidenceCard("生产部署回执", release.production_deployment_status || "not_connected", "尚未接入已应用部署回执。下方本地构建目录为空不表示未部署；不可据此推断实际生产提交。")}</div><h3>当前 readiness 阻断代码</h3>${issueList(readiness.blockers, "当前接口未提供具体阻断，或该快照无阻断；以当前生产就绪值和实时核验为准。")}</section>`;
}

function renderOwnerLaunchControlPanel(control) {
  const source = control && typeof control === "object" ? control : {};
  const review = source.owner_review_packet && typeof source.owner_review_packet === "object" ? source.owner_review_packet : {};
  const audit = source.launch_rehearsal_audit_packet && typeof source.launch_rehearsal_audit_packet === "object" ? source.launch_rehearsal_audit_packet : {};
  const history = source.release_history && typeof source.release_history === "object" ? source.release_history : {};
  const handoff = source.continuity_handoff_digest && typeof source.continuity_handoff_digest === "object" ? source.continuity_handoff_digest : {};
  const cutover = source.cutover_decision_checklist && typeof source.cutover_decision_checklist === "object" ? source.cutover_decision_checklist : {};
  const finalRehearsal = source.final_launch_rehearsal_execution_record && typeof source.final_launch_rehearsal_execution_record === "object" ? source.final_launch_rehearsal_execution_record : {};
  const dossier = source.owner_paid_launch_approval_dossier && typeof source.owner_paid_launch_approval_dossier === "object" ? source.owner_paid_launch_approval_dossier : {};
  const acceptance = source.prelaunch_acceptance_report && typeof source.prelaunch_acceptance_report === "object" ? source.prelaunch_acceptance_report : {};
  const actions = [
    ["owner-review-packet", "复核摘要"],
    ["launch-rehearsal-audit", "演练摘要"],
    ["release-history", "发布历史"],
    ["continuity-handoff", "交接摘要"],
    ["cutover-decision-checklist", "切换清单"],
    ["final-launch-rehearsal-record", "最终演练"],
    ["owner-paid-launch-dossier", "收费上线档案"],
    ["prelaunch-acceptance-report", "上线验收报告"],
  ];
  return `<section class="ops-panel" data-contract="owner_war_room_v3"><div class="ops-section-head"><div><h2>上线与发布</h2><p>只读展示发布门禁和脱敏证据；真实收费与平台写入仍需独立确认。</p></div><button class="ops-button" type="button" data-ops-action="refresh-owner-launch-control">刷新证据</button></div><div class="ops-reliability-list">${evidenceCard("总体门禁", source.status, source.next_action, "overall-gate")}${evidenceCard("主理人复核包", review.status, review.generated_at, "owner-review-packet")}${evidenceCard("上线演练审计", audit.status, audit.generated_at, "launch-rehearsal-audit")}${evidenceCard("历史本地构建记录", history.status, `本地 staging 包索引；不是生产部署记录。${evidenceTime(history.generated_at || history.updated_at)}`, "release-history")}${evidenceCard("连续性交接", handoff.status, handoff.updated_at, "continuity-handoff")}${evidenceCard("切换决策清单", cutover.status, cutover.generated_at, "cutover-decision-checklist")}${evidenceCard("最终上线演练", finalRehearsal.status, finalRehearsal.generated_at, "final-launch-rehearsal-record")}${evidenceCard("收费上线审批档案", dossier.status, dossier.generated_at, "owner-paid-launch-dossier")}${evidenceCard("上线前验收报告", acceptance.status, acceptance.generated_at, "prelaunch-acceptance-report")}</div><div class="ops-toolbar-actions" aria-label="脱敏证据导出">${actions.map(([key, label]) => `<button class="ops-button" type="button" data-evidence-export="${key}" data-ops-action="copy-${key}">复制${label}</button><button class="ops-button" type="button" data-evidence-export="${key}" data-ops-action="download-${key}">下载${label}</button>`).join("")}</div><dl class="ops-definition-list" data-safety-contract="read-only-redacted"><dt>敏感凭证</dt><dd>不在浏览器展示或导出</dd><dt>真实收费与平台写入</dt><dd>本页不直接执行，仍需独立确认</dd><dt>证据导出</dt><dd>仅导出白名单摘要字段</dd></dl></section>`;
}

function renderPaymentAcceptancePanel(state) {
  const testEvent = state?.testEvent && typeof state.testEvent === "object" ? state.testEvent : {};
  const provider = state?.provider && typeof state.provider === "object" ? state.provider : {};
  const wechat = state?.wechat && typeof state.wechat === "object" ? state.wechat : {};
  return `<section class="ops-panel" data-acceptance-contract="zero-charge-no-external-write"><div class="ops-section-head"><div><h2>支付验收</h2><p>三项动作分别只允许运行一次；均不创建真实订单、不扣款、不退款，也不跳转支付页。</p></div></div><div class="ops-reliability-list">${evidenceCard("计费状态事件", testEvent.status, testEvent.reason, "billing-test-event")}${evidenceCard("支付提供方演练", provider.status, provider.reason, "billing-provider-rehearsal")}${evidenceCard("微信零扣费验收", wechat.status, wechat.reason, "wechat-zero-charge-rehearsal")}</div><div class="ops-toolbar-actions" aria-label="零扣费验收动作"><button class="ops-button" type="button" data-one-attempt="true" data-ops-action="billing-test-event" ${state?.testEventAttempted ? "disabled" : ""}>运行计费状态事件</button><button class="ops-button" type="button" data-one-attempt="true" data-ops-action="billing-provider-rehearsal" ${state?.providerAttempted ? "disabled" : ""}>运行支付提供方演练</button><button class="ops-button ops-button-primary" type="button" data-one-attempt="true" data-ops-action="wechat-zero-charge-rehearsal" ${state?.wechatAttempted ? "disabled" : ""}>运行微信零扣费验收</button></div><dl class="ops-definition-list"><dt>外部支付调用</dt><dd>不调用</dd><dt>真实订单与扣款</dt><dd>不创建、不扣款、不退款</dd><dt>失败处理</dt><dd>不自动重试，需人工复核后再次发起</dd></dl></section>`;
}

function renderSaasWechatZeroChargeRehearsalPanel(state) {
  return renderPaymentAcceptancePanel(state);
}

function renderBackupRecoveryPanel(control) {
  const source = control?.ops_console_evidence?.backup || control?.evidence?.backup || {};
  return `<section class="ops-panel"><div class="ops-section-head"><div><h2>备份与恢复</h2><p>分别呈现整体门禁、对象存储探针和数据库恢复记录，不把策略要求当成验收结果。</p></div></div>${evidenceNote(control)}<div class="ops-reliability-list">${evidenceCard("备份与恢复整体门禁", source.status, "来源：backup_plan；这是合并门禁，不是最近一次自动备份结果。")}${evidenceCard("备份存储探针", source.storage_status, evidenceTime(source.storage_checked_at))}${evidenceCard("PITR 独立验收", source.pitr_status, "未接入独立的 PITR 实测证据；策略中要求开启不等于已验证可恢复。")}${evidenceCard("数据库恢复演练", source.restore_status, evidenceTime(source.restore_checked_at))}</div><h3>需复核的证据项</h3>${issueList(source.blockers)}</section>`;
}

function renderRuntimeSecurityPanel(control) {
  const source = control?.ops_console_evidence?.runtime || control?.evidence?.operational || {};
  const edgeStatus = source.edge_status || control?.evidence?.edge?.status;
  return `<section class="ops-panel"><div class="ops-section-head"><div><h2>运行与安全</h2><p>读取实际健康探针，不以是否允许上线或收费代替服务健康。</p></div></div>${evidenceNote(control)}<div class="ops-reliability-list">${evidenceCard("运行健康", source.status, "来源：operational_health；与发布门禁分开。")}${evidenceCard("数据库探针", source.database_status, "仅展示安全状态，不输出数据库地址或凭据。")}${evidenceCard("公网边界", edgeStatus, "来源：edge_cutover_preflight。")}${evidenceCard("队列", source.queue_status, "来源：queue_runtime；没有数据时保持未知。")}${evidenceCard("Worker", source.worker_status, `${source.worker_heartbeat_status || "未提供心跳状态"} · ${evidenceTime(source.worker_checked_at)}`)}</div><h3>阻断与关注</h3>${issueList([...(source.blockers || []), ...(source.warnings || [])])}</section>`;
}

function buildSaasOwnerReviewPacketDownloadPayload(source = {}) {
  return { contract_version: "owner_review_packet_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), secret_exposed: false };
}

function buildSaasLaunchRehearsalAuditDownloadPayload(source = {}) {
  return { contract_version: "launch_rehearsal_audit_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), secret_exposed: false };
}

function buildSaasReleaseHistoryDownloadPayload(source = {}) {
  return { contract_version: "owner_release_history_v1", status: String(source.status || "unknown"), scope: "local_build_artifacts_not_production_deployments", updated_at: String(source.generated_at || source.updated_at || ""), secret_exposed: false };
}

function buildSaasContinuityHandoffDownloadPayload(source = {}) {
  return { contract_version: "continuity_handoff_v1", status: String(source.status || "unknown"), updated_at: String(source.updated_at || ""), secret_exposed: false };
}

function buildSaasCutoverDecisionChecklistDownloadPayload(source = {}) {
  return { contract_version: "cutover_decision_checklist_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), recommended_next_step: String(source.summary?.recommended_next_step || ""), secret_exposed: false };
}

function buildSaasFinalLaunchRehearsalRecordDownloadPayload(source = {}) {
  return { contract_version: "final_launch_rehearsal_execution_record_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), decision: String(source.summary?.decision || ""), secret_exposed: false };
}

function buildSaasOwnerPaidLaunchDossierDownloadPayload(source = {}) {
  return { contract_version: "owner_paid_launch_approval_dossier_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), decision: String(source.summary?.decision || ""), readiness_score_percent: Number(source.summary?.readiness_score_percent || 0), secret_exposed: false };
}

function buildSaasPrelaunchAcceptanceReportDownloadPayload(source = {}) {
  return { contract_version: "prelaunch_acceptance_report_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), decision: String(source.summary?.decision || ""), readiness_score_percent: Number(source.summary?.readiness_score_percent || 0), secret_exposed: false };
}

global.JiejingOpsPanels = Object.freeze({
  renderLaunchAlignment,
  renderOwnerLaunchControlPanel,
  renderPaymentAcceptancePanel,
  renderSaasWechatZeroChargeRehearsalPanel,
  renderBackupRecoveryPanel,
  renderRuntimeSecurityPanel,
  buildSaasOwnerReviewPacketDownloadPayload,
  buildSaasLaunchRehearsalAuditDownloadPayload,
  buildSaasReleaseHistoryDownloadPayload,
  buildSaasContinuityHandoffDownloadPayload,
  buildSaasCutoverDecisionChecklistDownloadPayload,
  buildSaasFinalLaunchRehearsalRecordDownloadPayload,
  buildSaasOwnerPaidLaunchDossierDownloadPayload,
  buildSaasPrelaunchAcceptanceReportDownloadPayload,
});
})(window);
