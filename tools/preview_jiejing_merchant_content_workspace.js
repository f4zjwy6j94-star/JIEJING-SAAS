"use strict";
// Local-only synthetic review fixture. No production cookies, data or API access.
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");
const actualBoot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
if (!actualBoot.test(app)) throw new Error("Unexpected boot boundary");
const setup = `
  window.fetch = () => Promise.reject(new Error('Local preview has no API connection'));
  state.saasConnected = true;
  state.saasCompany = {company_id: 'local-preview-company'};
  state.saasIdentity = {company_id: 'local-preview-company'};
  state.saasStores = [];
  state.saasConfirmations = [];
  const previewCase = new URL(location.href).searchParams.get('case');
  if(['pending','approved'].includes(previewCase)) state.saasConfirmations = [{confirmation_id:'local-review-confirmation',company_id:'local-preview-company',status:previewCase,action_type:'sensitive_customer_reply',title:'本地合成：核对回复内容',summary:'请核对买家问题与回复草稿。',created_at:'2026-09-24T12:00:00Z',high_risk:true,item:{reply_text:'本地合成草稿，不会向买家发送。'}}];
  state.saasExecutionResults = [];
  state.saasBillingUsage = {subscription: {status:'active', entitlement_active:true, plan_key:'starter'}, plan:{key:'starter',amount_minor:9900}, media_credits:{contract_version:'2026-08-27-merchant-media-points-v1', available_points:80,included_points:80,purchased_points:0,promotional_points:0,packs:[{key:'pack_1000',points:1000,amount_minor:1000}],purchase:{purchase_enabled:false,status:'not_open'}}};
  state.saasDomesticBillingOrders = [];
  state.saasDomesticBillingContract = {provider:'wechat_pay_native',real_checkout_ready:true,charge_now_allowed:true};
  state.saasSettingsTab = 'billing';
  const previewContext = {connection:{status:'connected'},store:{store_id:'local-preview-store'},packetBody:{section_summary:[{key:'orders_and_fulfillment',data_present:true,source_type:'official_api'}]},presentKeys:['orders_and_fulfillment'],presentCount:1,coverageTotal:6,missingKeys:['inventory_and_offers'],hasPacket:true,lastSync:'2026-08-28T02:20:00Z',sourceLabel:'eBay 官方来源'};
  saasMerchantWorkbenchContext = () => previewContext;
  function showPreview(view) {
    document.querySelectorAll('.view').forEach(el => el.classList.toggle('is-active', el.id === 'view-'+view));
    document.body.dataset.view = view;
    state.view = view;
    if(view === 'service') renderSaasServiceCenter();
    if(view === 'confirm') renderSaasConfirmPanel();
    if(view === 'connect') document.querySelector('#view-connect').innerHTML = renderSaasSettingsCleanLayout(previewContext);
  }
  document.addEventListener('click', event => {
    const settings = event.target.closest('[data-saas-settings-tab]');
    if(settings) {state.saasSettingsTab=settings.dataset.saasSettingsTab;showPreview('connect');return;}
    const nav = event.target.closest('[data-preview-view]');
    if(nav) {showPreview(nav.dataset.previewView);return;}
    const action = event.target.closest('[data-saas-action],[data-global-flow-view]');
    if(action) {event.preventDefault();document.querySelector('#previewStatus').textContent='本地预览：已识别操作入口；不会调用服务或修改账号。';}
  });
  showPreview(new URL(location.href).searchParams.get('view') || 'confirm');
`;
const html = `<!doctype html><html lang="zh-CN" class="app-ready"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>捷境内容整理 · 本地合成预览</title><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/assets/jiejing-premium-surfaces.css"></head><body class="saas-public-mvp"><div class="app-shell" id="appShell" data-ui-generation="premium-merchant-workbench-v1"><aside class="sidebar"><strong>捷境</strong><p>本地合成预览</p><nav><button data-preview-view="confirm">确认中心</button><button data-preview-view="service">客服与订单</button><button data-preview-view="connect">设置</button></nav><p id="previewStatus" role="status">不连接生产账号，不执行外部操作。</p></aside><main class="main"><section id="view-confirm" class="view"><div id="confirmGrid"></div></section><section id="view-service" class="view"></section><section id="view-connect" class="view"></section></main></div><script src="/app.js"></script><script>${setup}</script></body></html>`;
http.createServer((req,res) => {
  const pathname = new URL(req.url,"http://127.0.0.1").pathname;
  res.setHeader("Cache-Control","no-store");
  res.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'");
  if(pathname === "/app.js") {res.setHeader("Content-Type","text/javascript; charset=utf-8");res.end(fs.readFileSync(path.join(root,"app.js"),"utf8").replace(actualBoot, ""));}
  else if(pathname === "/") {res.setHeader("Content-Type","text/html; charset=utf-8");res.end(html);}
  else if(["/styles.css","/assets/jiejing-premium-surfaces.css"].includes(pathname)) {res.setHeader("Content-Type","text/css; charset=utf-8");res.end(fs.readFileSync(path.join(root,pathname.slice(1))));}
  else {res.writeHead(404);res.end();}
}).listen(9051,"127.0.0.1",() => console.log("Synthetic content preview: http://127.0.0.1:9051/?start=app&qa=public-saas"));
