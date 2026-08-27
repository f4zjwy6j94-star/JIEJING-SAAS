(function attachJiejingOpsPanels(global) {
"use strict";

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function safeStatus(value) {
  const normalized = String(value || "unknown").slice(0, 80);
  return { value: normalized, tone: /ready|green|success|complete/i.test(normalized) ? "is-ready" : /blocked|red|failed/i.test(normalized) ? "is-critical" : "is-attention" };
}

function safeList(value, limit = 8) {
  return (Array.isArray(value) ? value : []).filter((item) => item && typeof item === "object").slice(0, limit);
}

function evidenceCard(label, value, detail = "", evidenceKind = "") {
  const status = safeStatus(value);
  const kindAttribute = evidenceKind ? ` data-evidence-kind="${escapeHtml(evidenceKind)}"` : "";
  return `<article class="ops-reliability-item ${status.tone}"${kindAttribute}><header><strong>${escapeHtml(label)}</strong><span class="ops-pill ${status.tone}">${escapeHtml(status.value)}</span></header><p>${escapeHtml(detail || "等待可验证证据")}</p></article>`;
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
  return `<section class="ops-panel" data-contract="owner_war_room_v3"><div class="ops-section-head"><div><h2>上线与发布</h2><p>只读展示发布门禁和脱敏证据；真实收费与平台写入仍需独立确认。</p></div><button class="ops-button" type="button" data-ops-action="refresh-owner-launch-control">刷新证据</button></div><div class="ops-reliability-list">${evidenceCard("总体门禁", source.status, source.next_action, "overall-gate")}${evidenceCard("主理人复核包", review.status, review.generated_at, "owner-review-packet")}${evidenceCard("上线演练审计", audit.status, audit.generated_at, "launch-rehearsal-audit")}${evidenceCard("发布历史", history.status, history.updated_at, "release-history")}${evidenceCard("连续性交接", handoff.status, handoff.updated_at, "continuity-handoff")}${evidenceCard("切换决策清单", cutover.status, cutover.generated_at, "cutover-decision-checklist")}${evidenceCard("最终上线演练", finalRehearsal.status, finalRehearsal.generated_at, "final-launch-rehearsal-record")}${evidenceCard("收费上线审批档案", dossier.status, dossier.generated_at, "owner-paid-launch-dossier")}${evidenceCard("上线前验收报告", acceptance.status, acceptance.generated_at, "prelaunch-acceptance-report")}</div><div class="ops-toolbar-actions" aria-label="脱敏证据导出">${actions.map(([key, label]) => `<button class="ops-button" type="button" data-evidence-export="${key}" data-ops-action="copy-${key}">复制${label}</button><button class="ops-button" type="button" data-evidence-export="${key}" data-ops-action="download-${key}">下载${label}</button>`).join("")}</div><dl class="ops-definition-list" data-safety-contract="read-only-redacted"><dt>敏感凭证</dt><dd>不在浏览器展示或导出</dd><dt>真实收费与平台写入</dt><dd>本页不直接执行，仍需独立确认</dd><dt>证据导出</dt><dd>仅导出白名单摘要字段</dd></dl></section>`;
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
  const source = control?.backup_recovery && typeof control.backup_recovery === "object" ? control.backup_recovery : control?.database_recovery || {};
  return `<section class="ops-panel"><div class="ops-section-head"><div><h2>备份与恢复</h2><p>只显示自动备份、PITR、恢复演练和证据时效，不返回私有文件内容。</p></div></div><div class="ops-reliability-list">${evidenceCard("自动备份", source.backup_status || source.status, source.backup_checked_at)}${evidenceCard("PITR", source.pitr_status, source.pitr_checked_at)}${evidenceCard("恢复演练", source.restore_drill_status, source.restore_drill_at)}</div></section>`;
}

function renderRuntimeSecurityPanel(control) {
  const source = control?.operational_readiness && typeof control.operational_readiness === "object" ? control.operational_readiness : control || {};
  return `<section class="ops-panel"><div class="ops-section-head"><div><h2>运行与安全</h2><p>运行健康和公网边界均为只读证据；不在浏览器执行高风险命令。</p></div></div><div class="ops-reliability-list">${evidenceCard("运行健康", source.status, source.next_action)}${evidenceCard("公网边界", source.edge_status, source.edge_checked_at)}${evidenceCard("队列与 Worker", source.worker_status, source.worker_checked_at)}</div></section>`;
}

function buildSaasOwnerReviewPacketDownloadPayload(source = {}) {
  return { contract_version: "owner_review_packet_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), secret_exposed: false };
}

function buildSaasLaunchRehearsalAuditDownloadPayload(source = {}) {
  return { contract_version: "launch_rehearsal_audit_v1", status: String(source.status || "unknown"), generated_at: String(source.generated_at || ""), secret_exposed: false };
}

function buildSaasReleaseHistoryDownloadPayload(source = {}) {
  return { contract_version: "owner_release_history_v1", status: String(source.status || "unknown"), updated_at: String(source.updated_at || ""), secret_exposed: false };
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
