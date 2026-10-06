#!/usr/bin/env node
/* Real app.html/app.js responsive regression, adapted from the existing history
 * browser smoke fixture, using the repository's installed Playwright harness.
 * Only loopback static resources and one intercepted read-only checkpoint exist;
 * every other request is blocked. No business writes, provider calls or boot API.
 * Boot hydration is intentionally excluded; real renderers and navigation run.
 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const { chromium } = require('../output/codex-playwright-deps/node_modules/playwright-core');
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jiejing-workbench-finish-'));
const completedCases = [];
const fixtureReads = [];
const checkpointFixture = { checkpoint: null, current_revision: 0, current_base_report_id: 'ui-fixture-report',
  current_base_report: {report_id:'ui-fixture-report',report_type:'merchant.product_facts',status:'saved',company_id:'ui-fixture-company',store_id:'ui-fixture-store',
    report:{product_name:'折叠平板电脑支架',listing_project_identity:{key:'ui-fixture-tablet-project',source_report_id:'ui-fixture-report',candidate_id:'candidate_1'}}} };
fs.mkdirSync(outDir, { recursive: true });

const deadline = setTimeout(() => { console.error('Workbench finish smoke exceeded 170 seconds'); process.exit(1); }, 170000);
deadline.unref();

async function verifyActualChatLayout(browser, base) {
  const results = completedCases;
  for (const width of [1440, 920, 390, 320]) {
    for (const variant of ["empty", "project", "project-long"]) {
      const context = await browser.newContext({ viewport: { width, height: width >= 920 ? 1000 : width === 390 ? 844 : 740 } });
      const errors = [];
      const requests = [];
      await context.route("**/*", (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin === base && request.method() === "GET" && /^\/(visual-app\.html|app\.js|styles\.css|assets\/)/.test(url.pathname)) return route.continue();
        if (url.protocol === "data:") return route.continue();
        if (url.origin === base && request.method() === "GET" && url.pathname === "/stores/ui-fixture-store/listing-drafts/ui-fixture-tablet-project/checkpoint") { fixtureReads.push(url.pathname); return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify(checkpointFixture)}); }
        requests.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      });
      const visual = await context.newPage();
      visual.on("pageerror", (error) => errors.push(error.message));
      visual.on("console", msg => { if (["warning", "error"].includes(msg.type())) errors.push(msg.type() + ": " + msg.text()); });
      await visual.goto(`${base}/visual-app.html?start=app&view=cockpit&qa=public-saas&saasApiBase=${encodeURIComponent(base)}`);
      await visual.evaluate(({ variant, width }) => {
        window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
        localStorage.setItem(saasStorageKeys.sessionHint, "1");
        localStorage.setItem(saasStorageKeys.storeId, "ui-fixture-store");
        state.saasToken = "local-visual-fixture-only";
        state.saasIdentity = { user_id: "ui-fixture-user", company_id: "ui-fixture-company" };
        state.saasUser = { user_id: "ui-fixture-user", email: "ui-fixture@example.test" };
        state.saasCompany = { company_id: "ui-fixture-company" };
        state.saasStores = [{ store_id: "ui-fixture-store", store_name: "eBay 店铺", platform: "ebay", status: "authorized" }];
        state.activeStore = "ui-fixture-store";
        state.saasConnected = true;
        state.saasProtectedStateReady = true;
        state.saasLoading = false;
        state.saasSessionExpiryHandled = false;
        state.saasAiCeoThread = [];
        state.saasAiCeoLatestTurn = null;
        state.saasReports = [];
        state.saasTasks = [];
        state.saasCeoCommandChatVisible = false;
        state.saasMerchantProjectStatus = null;
        state.view = "cockpit";
        state.dna.merchantStage = "store_opened";
        syncSaasPublicMvpMode();
        if (variant.startsWith("project")) {
          const identity = { key: "ui-fixture-tablet-project", source_report_id: "ui-fixture-report", candidate_id: "candidate_1" };
          state.saasAiCeoThread = [
            { assistant_id: "ui-fixture-chat-1", user_text: "我有一款折叠平板电脑支架，帮我整理商品资料并准备 eBay Listing。", assistant_text: "可以。先把商品图片和现有规格发给我，我会整理到商品资料中。缺少或互相冲突的信息会标为待确认，不会自动当成真实事实。", created_at: "2026-09-05T08:00:00Z" },
            { assistant_id: "ui-fixture-chat-2", user_text: "图片已经补充，先整理草稿，材质和包装重量我再核对。", assistant_text: "已整理当前商品资料，并保留材质和包装重量两项待确认。\n\n你可以在“选品与上架”检查标题、描述和商品规格。商品事实与图片审核完成后，再进行 eBay 发布前检查；最终发布仍需要你确认。", created_at: "2026-09-05T08:01:00Z" },
          ].map((turn) => normalizeSaasAiCeoLatestTurn({ ...turn, store_id: "ui-fixture-store", route: "ebay_workflow", status: "model_answered", listing_project_identity: identity }));
          state.saasAiCeoLatestTurn = state.saasAiCeoThread[1];
          const productName = variant === "project-long" ? "折叠式铝合金平板电脑支架适用于家庭办公室旅行便携桌面多角度调节加宽防滑底座超长商品名称测试" : "折叠平板电脑支架";
          state.saasMerchantProjectStatus = { snapshot_version: "merchant_project_status_v1", project: { project_id: identity.key, product_name: productName }, current_stage: "facts", overall_status: "blocked", stages: [
            { key: "research", label: "商品方向", status: "completed" },
            { key: "facts", label: "商品资料", status: "blocked", is_current: true, detail: "请核对材质和包装重量，再继续完善 Listing。" },
          ], blocker: { key: "merchant_product_facts_missing", title: "还有 2 项资料待确认" }, next_action: { view: "product", label: "核对商品资料" } };
          state.saasListingComposerDraft = { product: productName, listing_project_identity: identity, merchant_required_answers: ["材质", "包装重量"] };
          setSaasAiCeoTaskContextState("active_product_task", width >= 1280, { projectId: identity.key });
        } else setSaasAiCeoTaskContextState("plain_consultation", false);
        [entryShell, siteShell, onboardingShell].forEach((shell) => shell.classList.add("is-hidden"));
        appShell.classList.remove("is-hidden");
        document.documentElement.classList.add("app-ready");
        document.documentElement.classList.remove("app-shell-empty", "app-auth-pending");
        document.body.classList.remove("site-locked");
        document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === "view-cockpit"));
        renderAccountMenu();
        renderSaasCockpitRealWorkbench();
        document.addEventListener("click", (event) => {
          const control = event.target.closest("[data-ai-ceo-task-context-toggle], [data-ai-ceo-task-context-close]");
          if (control) { event.preventDefault(); handleSaasAiCeoTaskContextToggle(control); }
        });
      }, { variant, width });
      await visual.evaluate(() => document.fonts.ready);
      await visual.locator("#ceoInput").fill("本地界面检查，不发送");
      assert.equal(await visual.locator("#ceoInput").inputValue(), "本地界面检查，不发送");
      await visual.locator("#ceoInput").fill("");
      const geometry = await visual.evaluate(() => {
        const chat = document.querySelector(".saas-ai-ceo-thread").getBoundingClientRect();
        const composer = document.querySelector("#ceoForm").getBoundingClientRect();
        const send = document.querySelector("#ceoForm button[type=submit]");
        const button = send.getBoundingClientRect();
        const hit = document.elementFromPoint(button.x + button.width / 2, button.bottom - 2);
        return { chatBottom: chat.bottom, composerBottom: composer.bottom, sendBottomHit: hit === send || send.contains(hit), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      const screenshot = path.join(outDir, `jiejing-ai-ceo-layout-${variant}-${width}-${Date.now()}.png`);
      await visual.screenshot({ path: screenshot });
      assert(geometry.composerBottom <= geometry.chatBottom + 1 && geometry.sendBottomHit, `${variant} ${width}: composer and send button must remain fully usable: ${JSON.stringify(geometry)}`);
      assert(geometry.overflow <= 1, `${variant} ${width}: no horizontal overflow`);
      const composerControls = await assertComposerControls(visual, `${variant} ${width}`);
      const taskStates = [];
      if (variant.startsWith("project")) {
        const speaker = await visual.locator('#ceoChat .message.ai > span').first().evaluate((node) => {
          const style = getComputedStyle(node);
          return { color: style.color, whiteSpace: style.whiteSpace, width: node.clientWidth, contentWidth: node.scrollWidth };
        });
        assert.equal(speaker.color, 'rgb(255, 255, 255)', 'assistant badge must contrast with its dark background on every viewport');
        assert.equal(speaker.whiteSpace, 'nowrap');
        assert(speaker.contentWidth <= speaker.width, 'AI CEO badge must not wrap or clip');
        for (let transition = 0; transition < 3; transition += 1) {
          const taskGeometry = await visual.evaluate(() => {
            const task = document.querySelector("[data-ai-ceo-task-context]");
            const summary = task.querySelector("[data-ai-ceo-task-context-toggle]");
            const expanded = summary.getAttribute("aria-expanded") === "true";
            const panel = task.getBoundingClientRect();
            const chat = document.querySelector(".saas-ai-ceo-thread").getBoundingClientRect();
            const firstUser = document.querySelector("#ceoChat .message.user").getBoundingClientRect();
            const toggle = summary.getBoundingClientRect();
            const hit = document.elementFromPoint(toggle.x + toggle.width / 2, toggle.y + toggle.height / 2);
            const detail = task.querySelector("[data-ai-ceo-task-context-detail]");
            const action = task.querySelector("[data-ai-ceo-task-next-action]");
            const actionBox = action.getBoundingClientRect();
            const actionHit = document.elementFromPoint(actionBox.x + actionBox.width / 2, actionBox.y + actionBox.height / 2);
            const composer = document.querySelector("#ceoForm").getBoundingClientRect();
            const send = document.querySelector("#ceoForm button[type=submit]");
            const sendBox = send.getBoundingClientRect();
            const sendHit = document.elementFromPoint(sendBox.x + sendBox.width / 2, sendBox.bottom - 2);
            return { expanded, summaryHit: hit === summary || summary.contains(hit), chatWidth: chat.width, taskWidth: panel.width,
              overlap: panel.x < firstUser.right && panel.right > firstUser.x && panel.y < firstUser.bottom && panel.bottom > firstUser.y,
              composerUsable: composer.bottom <= chat.bottom + 1 && (sendHit === send || send.contains(sendHit)),
              detailVisible: !detail.hidden && !!detail.getClientRects().length, actionHit: actionHit === action || action.contains(actionHit) };
          });
          if (!taskGeometry.expanded || width > 1100) {
            assert.equal(taskGeometry.overlap, false, `${width}: task summary must not cover conversation: ${JSON.stringify(taskGeometry)}`);
            assert.equal(taskGeometry.summaryHit, true, `${width}: task summary must remain clickable`);
            assert.equal(taskGeometry.composerUsable, true, `${width}: toggling the task must leave the composer usable`);
            await assertComposerControls(visual, `${variant} ${width} toggle ${transition}`);
          }
          if (taskGeometry.expanded) {
            assert(taskGeometry.detailVisible && taskGeometry.actionHit, `${width}: expanded task detail action must be reachable`);
            if (width > 1100) assert(taskGeometry.chatWidth > taskGeometry.taskWidth * 1.8, "desktop conversation must remain primary");
          }
          taskStates.push(taskGeometry);
          if (transition < 2) {
            taskGeometry.screenshot = path.join(outDir, `jiejing-ai-ceo-layout-project-${taskGeometry.expanded ? "expanded" : "collapsed"}-${width}-${Date.now()}.png`);
            await visual.screenshot({ path: taskGeometry.screenshot });
          }
          if (transition < 2) await visual.locator(taskGeometry.expanded && width <= 1100 ? "[data-ai-ceo-task-context-close]" : "[data-ai-ceo-task-context-toggle]").click();
        }
      }
      assert.deepEqual(errors, []);
      assert.deepEqual(requests, [], "visual inspection must not invoke APIs or external providers");
      const supplement = await inspectModules(visual, variant, width);
      assert.deepEqual(errors, [], JSON.stringify({errors, requests}));
      assert.deepEqual(requests, []);
      results.push({ variant, width, screenshot, ...geometry, composerControls, task_states: taskStates, supplement,
        console_page_errors: [...errors], blocked_requests: [...requests] });
      await context.close();
    }
  }
  return results;
}

async function assertComposerControls(page, label) {
  const metrics = await page.evaluate(() => {
    const chat = document.querySelector('.saas-ai-ceo-thread').getBoundingClientRect();
    const dock = document.querySelector('.saas-ai-ceo-composer-dock').getBoundingClientRect();
    const hint = document.querySelector('.saas-ai-ceo-input-hint');
    const range = document.createRange();
    if (hint) range.selectNodeContents(hint);
    const hintBottom = hint ? range.getBoundingClientRect().bottom : null;
    const controls = ['#ceoInput', '#ceoForm button[type=submit]'].map(selector => {
      const control = document.querySelector(selector);
      const r = control.getBoundingClientRect();
      const xInset = Math.min(12, r.width / 4);
      const yInset = Math.min(12, r.height / 4);
      // Test the complete action area: four rounded-corner interiors, four edge
      // midpoints and centre. Bottom edges catch the fixed-summary regression.
      const points = [[r.left+xInset,r.top+2],[r.right-xInset,r.top+2],
        [r.left+xInset,r.bottom-2],[r.right-xInset,r.bottom-2],
        [r.left+2,r.top+yInset],[r.right-2,r.top+yInset],
        [r.left+2,r.bottom-yInset],[r.right-2,r.bottom-yInset],
        [r.left+r.width/2,r.top+r.height/2]];
      return {selector, width:r.width, height:r.height, top:r.top, bottom:r.bottom,
        inside: r.left >= chat.left && r.right <= chat.right &&
          r.top >= chat.top && r.bottom <= chat.bottom &&
          r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
        hits:points.map(([x,y]) => {const hit=document.elementFromPoint(x,y); return hit === control || control.contains(hit);})};
    });
    return {dockBottom:dock.bottom, chatBottom:chat.bottom, hintBottom, controls};
  });
  // The legacy dock's decorative bottom padding may be clipped, but no text or
  // interactive rectangle may be clipped. Do not equate outer padding with UI.
  assert(metrics.hintBottom === null || metrics.hintBottom <= metrics.chatBottom, label + ': composer helper text must remain visible: ' + JSON.stringify(metrics));
  for (const control of metrics.controls) {
    assert(control.inside && control.hits.every(Boolean), label + ': complete input/send action rectangle must remain usable: ' + JSON.stringify(control));
  }
  return metrics;
}

async function inspectModules(page, variant, width) {
  const initial = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('#navList .nav-item')];
    const visible = nodes.filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
    const chat = document.querySelector('.saas-ai-ceo-thread');
    const input = document.querySelector('#ceoInput');
    return { title: document.title, url: location.href, labels: nodes.map(n => n.innerText.trim()), visibleNav: visible.length,
      textLength: document.querySelector('#view-cockpit').innerText.trim().length,
      background: getComputedStyle(document.body).backgroundColor, font: getComputedStyle(document.body).fontFamily,
      chatBackground: getComputedStyle(chat).backgroundColor, inputFontSize: parseFloat(getComputedStyle(input).fontSize),
      styleLoaded: !![...document.styleSheets].find(s => s.href?.includes('jiejing-workbench-finish.css')),
      frameworkOverlay: !!document.querySelector('vite-error-overlay, nextjs-portal [data-nextjs-dialog]') };
  });
  assert.match(initial.title, /AI CEO/);
  assert.equal(initial.visibleNav, 6);
  assert(initial.textLength > 25);
  assert(initial.styleLoaded && initial.background === 'rgb(242, 244, 238)' && initial.chatBackground === 'rgb(255, 255, 255)');
  assert.equal(initial.frameworkOverlay, false);
  if (width <= 700) assert(initial.inputFontSize >= 16);
  // The existing fixture omits boot/network hydration. Bind only the same real
  // navigation handlers from bindEvents; rendering and route functions stay real.
  await page.evaluate(() => {
    document.querySelector('#navList').addEventListener('click', event => {
      const button = event.target.closest('.nav-item');
      if (button) setView(button.dataset.view);
    });
    for (const viewId of ['product', 'bulk']) document.querySelector('#view-' + viewId).addEventListener('click', event => {
      const button = event.target.closest('[data-listing-mode]');
      if (button) { event.preventDefault(); activateSaasListingMode(button.dataset.listingMode || 'single'); }
    });
  });
  await page.locator('#navList [data-view="product"]').click();
  await page.locator('#view-product.is-active [data-listing-mode="bulk"]').waitFor({state: 'visible'});
  const product = await page.evaluate(() => ({ active: state.view, overflow: document.documentElement.scrollWidth - innerWidth }));
  await page.screenshot({ path: path.join(outDir, `product-${variant}-${width}.png`) });
  await page.locator('#view-product.is-active [data-listing-mode="bulk"]').click();
  await page.locator('#view-bulk.is-active').waitFor({state: 'visible'});
  const bulk = await page.evaluate(() => ({ active: state.view, mode: state.saasListingMode,
    text: document.querySelector('#view-bulk').innerText.slice(0, 120),
    overflow: document.documentElement.scrollWidth - innerWidth,
    navCount: [...document.querySelectorAll('#navList .nav-item')].filter(n => n.getClientRects().length).length }));
  await page.screenshot({ path: path.join(outDir, `bulk-${variant}-${width}.png`) });
  assert.equal(product.active, 'product');
  assert.equal(bulk.active, 'bulk');
  assert.equal(bulk.mode, 'bulk');
  assert.equal(bulk.navCount, 6);
  assert(product.overflow <= 1 && bulk.overflow <= 1, `business pages overflow: ${JSON.stringify({product, bulk})}`);
  const settingsData = variant === 'empty' && [1440, 390, 320].includes(width)
    ? await inspectRestrictedSettingsData(page, width) : null;
  return {initial, product, bulk, settingsData};
}

async function inspectRestrictedSettingsData(page, width) {
  // This is saved fixture data, not a read from an account or eBay. Exercise the
  // real context resolver, settings renderer and tab handler with scoped state.
  await page.evaluate(() => {
    const companyId = 'ui-fixture-company';
    const storeId = 'ui-fixture-store';
    const resourceKeys = ['store_profile', 'account_business_policies', 'inventory_and_offers',
      'orders_and_fulfillment', 'finances', 'taxonomy_listing_metadata'];
    state.saasAccountHealth = {company_id:companyId, store_id:storeId, status:'restricted', incident_mode:true, label:'账号受限'};
    state.saasDataPackets = [{packet_id:'ui-fixture-stale-packet', company_id:companyId, store_id:storeId,
      platform:'ebay', source_mode:'official_api', created_at:'2026-08-28T08:00:00Z',
      packet:{source_label:'official_api', present_resource_keys:resourceKeys, missing_resource_keys:[],
        freshness:{stale_after_seconds:21600},
        section_summary:resourceKeys.map(key => ({key, data_present:true, source_type:'official_api'}))}}];
    state.saasSettingsTab = 'account';
    document.querySelector('#view-connect').addEventListener('click', event => {
      const button = event.target.closest('[data-saas-settings-tab]');
      if (button) {
        event.preventDefault();
        state.saasSettingsTab = button.dataset.saasSettingsTab || 'account';
        renderSaasConnectCenter(document.querySelector('#view-connect'));
      }
    });
    setView('connect');
  });
  await page.locator('#view-connect.is-active [data-saas-settings-tab="data"]').click();
  const panel = page.locator('#view-connect.is-active .saas-settings-clean-content');
  const account = panel.locator('[data-saas-data-account-status]');
  await account.waitFor({state:'visible'});
  assert.match(await account.innerText(), /账号受限/);
  assert.match(await account.innerText(), /真实发布已暂停/);
  const text = await panel.innerText();
  assert.match(text, /6\/6\s*类已保存/);
  assert.match(text, /08[/-]28/);
  assert.match(text, /历史资料\s*·\s*需更新/);
  assert.doesNotMatch(text, /已读取|无核心缺口/);
  const savedResources = await panel.locator('.saas-settings-resource-list article > strong').allTextContents();
  assert.deepEqual(savedResources, Array(6).fill('已保存'));
  const rendered = await page.evaluate(() => {
    const view = document.querySelector('#view-connect');
    const ctx = saasMerchantWorkbenchContext();
    const account = view.querySelector('[data-saas-data-account-status]');
    const content = view.querySelector('.saas-settings-clean-content');
    return {view:state.view, tab:state.saasSettingsTab,
      source:ctx.packetBody.source_label, lastSync:ctx.lastSync,
      storeId:ctx.store.store_id, accountStoreId:state.saasAccountHealth.store_id,
      companyId:state.saasCompany.company_id, accountCompanyId:state.saasAccountHealth.company_id,
      accountStatus:account.innerText, visible:!!account.getClientRects().length,
      overflow:document.documentElement.scrollWidth - innerWidth,
      contentOverflow:content.scrollWidth - content.clientWidth,
      frameworkOverlay:!!document.querySelector('vite-error-overlay, nextjs-portal [data-nextjs-dialog]')};
  });
  assert.equal(rendered.view, 'connect');
  assert.equal(rendered.tab, 'data');
  assert.equal(rendered.source, 'official_api');
  assert.equal(rendered.lastSync, '2026-08-28T08:00:00Z');
  assert.equal(rendered.storeId, rendered.accountStoreId);
  assert.equal(rendered.companyId, rendered.accountCompanyId);
  assert.equal(rendered.visible, true);
  assert.equal(rendered.frameworkOverlay, false);
  assert(rendered.overflow <= 1 && rendered.contentOverflow <= 1,
    `settings data ${width}: no horizontal overflow: ${JSON.stringify(rendered)}`);
  const screenshot = path.join(outDir, `settings-data-restricted-stale-${width}.png`);
  await page.screenshot({path:screenshot, fullPage:true});
  // A mobile full-page screenshot includes the fixed bottom navigation at its
  // initial viewport position. Also prove the status is readable after normal
  // scrolling, not merely present somewhere in the DOM below that navigation.
  await account.evaluate(node => node.scrollIntoView({block:'center'}));
  const accountReadable = await account.evaluate(node => {
    const r = node.getBoundingClientRect();
    const points = [[r.left + 12, r.top + 12], [r.right - 12, r.bottom - 12],
      [r.left + r.width / 2, r.top + r.height / 2]];
    return r.top >= 0 && r.bottom <= innerHeight && points.every(([x,y]) => {
      const hit = document.elementFromPoint(x,y);
      return hit === node || node.contains(hit);
    });
  });
  assert.equal(accountReadable, true, `settings data ${width}: account warning must remain readable after scrolling`);
  const statusScreenshot = path.join(outDir, `settings-data-account-visible-${width}.png`);
  await page.screenshot({path:statusScreenshot});
  return {width, ...rendered, savedResources, text, screenshot, accountReadable, statusScreenshot};
}

(async () => {
  const appSource = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert(boot.test(appSource));
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    const relative = url.pathname === '/visual-app.html' ? 'app.html' : url.pathname.slice(1);
    const file = path.resolve(root, relative);
    const allowed = ['app.html', 'app.js', 'styles.css'].includes(relative) || relative.startsWith('assets/');
    if (!allowed || !file.startsWith(path.resolve(root) + path.sep) || !fs.existsSync(file) || req.method !== 'GET') {
      res.writeHead(404); return res.end('No business API in this local fixture');
    }
    const types = {'.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8', '.svg':'image/svg+xml', '.woff2':'font/woff2', '.webp':'image/webp', '.png':'image/png', '.jpg':'image/jpeg'};
    res.writeHead(200, {'content-type': types[path.extname(file)] || 'application/octet-stream', 'cache-control':'no-store'});
    res.end(relative === 'app.js' ? appSource.replace(boot, 'exposeLocalJiejingTestHooks();\n') : fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  let report;
  try {
    const cases = await verifyActualChatLayout(browser, base);
    report = {status:'pass', base, actualResources:['app.html','app.js','styles.css','assets/jiejing-premium-surfaces.css','assets/jiejing-workbench-finish.css'], fixtureSource:'tools/codex_jiejing_ai_ceo_history_pagination_browser_smoke.js::verifyActualChatLayout', cases, fixtureReads, limitations:'Boot init and backend hydration intentionally skipped; same real renderer/route functions with explicit local account/project fixtures. One exact read-only checkpoint endpoint is fulfilled in browser; all other nonstatic browser requests abort.'};
  } catch (error) {
    report = {status:'fail', base, cases:completedCases, error: String(error.stack || error)};
    const pages = browser.contexts().flatMap(context => context.pages());
    for (let i = 0; i < pages.length; i++) await pages[i].screenshot({path:path.join(outDir, `failure-${i}.png`)}).catch(()=>{});
    report.geometry = await pages[0]?.evaluate(() => {
      const rect = sel => { const n = document.querySelector(sel); const r = n?.getBoundingClientRect(); const s = n && getComputedStyle(n); return r ? {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,paddingBottom:s.paddingBottom,lineHeight:s.lineHeight,fontSize:s.fontSize} : null; };
      const button = document.querySelector('#ceoForm button[type=submit]'); const b = button?.getBoundingClientRect(); const hit = b && document.elementFromPoint(b.x+b.width/2,b.bottom-2);
      return {intro:rect('.saas-ai-ceo-thread-intro'),handoff:rect('.saas-ai-ceo-first-run-handoff'),stream:rect('#ceoChat'),hint:rect('.saas-ai-ceo-composer-dock .voice-hint'),thread:rect('.saas-ai-ceo-thread'), composer:rect('#ceoForm'), dock:rect('.saas-ai-ceo-composer-dock'), task:rect('[data-ai-ceo-task-context]'), taskSummary:rect('[data-ai-ceo-task-context-toggle]'),send:rect('#ceoForm button[type=submit]'),occluder:hit?.outerHTML.slice(0,250)};
    }).catch(()=>null);
    process.exitCode = 1;
  } finally {
    fs.writeFileSync(path.join(outDir, 'evidence.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({status:report.status,cases:report.cases?.length,evidence:path.join(outDir,'evidence.json'),error:report.error}));
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
