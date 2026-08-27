(function attachJiejingSettingsPanels(global) {
  "use strict";

  function escape(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function planName(plan) {
    const key = String(plan?.plan_key || plan?.key || "free_trial").toLowerCase();
    if (key === "single_store" || key === "merchant_single") return "有店铺";
    if (key === "multi_store" || key === "merchant_multi") return "多店铺";
    return "免费体验";
  }

  function renderBillingProviderPanel(state) {
    const plan = state?.saasBillingPlan && typeof state.saasBillingPlan === "object" ? state.saasBillingPlan : {};
    const usage = state?.saasBillingUsage && typeof state.saasBillingUsage === "object" ? state.saasBillingUsage : {};
    const subscription = usage.subscription && typeof usage.subscription === "object" ? usage.subscription : {};
    const quota = plan.quota_contract && typeof plan.quota_contract === "object" ? plan.quota_contract : {};
    const payment = plan.mainland_payment && typeof plan.mainland_payment === "object" ? plan.mainland_payment : {};
    const paymentOpen = payment.public_checkout_active === true;
    const tasksRemaining = Number.isFinite(Number(quota.remaining_tasks)) ? Number(quota.remaining_tasks) : null;
    const mediaRemaining = Number.isFinite(Number(quota.remaining_media_points)) ? Number(quota.remaining_media_points) : null;
    return `
      <section class="saas-settings-card saas-merchant-billing-summary" data-contract="merchant_billing_copy_public_safe_v1" aria-label="订阅与付款">
        <div class="saas-settings-card-head"><div><span>订阅与付款</span><strong>${escape(planName(plan))}</strong><p>套餐已包含对应素材点；用完后才需要加购。页面不展示任何支付密钥。</p></div></div>
        <div class="saas-settings-status-list">
          <article class="${subscription.entitlement_active === true ? "is-green" : "is-amber"}"><span>当前模式</span><strong>${subscription.entitlement_active === true ? "权益生效中" : "免费体验或待开通"}</strong><small>${escape(subscription.ends_at ? `有效期至 ${subscription.ends_at}` : "不绑卡，不自动续费")}</small></article>
          <article><span>续费 / 取消</span><strong>由商家主动操作</strong><small>付款、退款和套餐变更都会先显示订单与结果。</small></article>
          <article><span>AI / 素材用量</span><strong>${tasksRemaining == null ? "按当前套餐计算" : `剩余 ${tasksRemaining} 个任务`}</strong><small>${mediaRemaining == null ? "素材点余额在本页单独显示" : `剩余 ${mediaRemaining} 素材点`}</small></article>
          <article><span>欠费保护</span><strong>历史结果继续可见</strong><small>权益暂停时只停止新增计量任务，不删除已有商品、素材和记录。</small></article>
          <article class="${paymentOpen ? "is-green" : "is-amber"}"><span>付款状态</span><strong>${paymentOpen ? "在线付款开放" : "当前仅展示试用和订阅说明"}</strong><small>${paymentOpen ? "商家主动创建订单并微信扫码；到账后由后端更新套餐权益。" : "在线付款尚未向此账号开放，不会自动扣款。"}</small></article>
        </div>
      </section>
    `;
  }

  function merchantBillingModuleVersion() {
    return "merchant_billing_copy_public_safe_v1";
  }

  global.JiejingSettingsPanels = Object.freeze({ renderBillingProviderPanel, merchantBillingModuleVersion });
})(window);
