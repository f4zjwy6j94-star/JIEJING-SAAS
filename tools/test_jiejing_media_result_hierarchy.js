"use strict";
// Offline, synthetic fixture using the production markup, CSS and renderers.
// No production session, external request, model generation or platform write.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const test = require("node:test");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "app.html"), "utf8");
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  const tail = source.slice(start);
  return tail.slice(0, tail.search(/\n(?:async )?function /));
}
const start = html.indexOf('<section class="view" id="view-media"');
const end = html.indexOf('<section class="view"', start + 1);
assert.ok(start >= 0 && end > start);
const mediaMarkup = html.slice(start, end).replace('class="view"', 'class="view is-active"');
assert.match(extract("renderSaasMediaStudioStatus"), /placeSaasMediaResultPanels\(\);/);
const fixture = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>素材工坊 · 本地合成回归</title>
<link rel="stylesheet" href="/styles.css"><body class="saas-public-mvp"><div id="appShell" class="app-shell" data-ui-generation="premium-merchant-workbench-v1">
<aside class="sidebar"><strong>捷境</strong><p>本地合成回归</p><p>AI CEO</p><p>选品与上架</p><p>素材工坊</p></aside><main class="main">${mediaMarkup}</main></div></body></html>`;

test("desktop and tablet keep results outside collapsed help through refreshes", async () => {
  const server = http.createServer((req, res) => {
    if (req.url === "/styles.css") { res.setHeader("content-type", "text/css"); res.end(fs.readFileSync(path.join(root, "styles.css"))); }
    else if (req.url === "/") { res.setHeader("content-type", "text/html; charset=utf-8"); res.end(fixture); }
    else { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  const outDir = path.join(root, "output", "browser-smoke", "media-result-hierarchy-20260923");
  fs.mkdirSync(outDir, { recursive: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 820, height: 1180 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on("pageerror", error => errors.push(String(error)));
      await page.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.addScriptTag({ content: `
        const state = {};
        let empty = false;
        const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
        const activeMediaDraftProfileForDisplay = () => null;
        const saasMerchantWorkbenchContext = () => ({});
        const latestSaasReportByTypes = () => null;
        const activeMediaDraftProductNameForDisplay = () => '平板电脑支架（本地合成测试）';
        const latestSaasMediaAssetJobWithManifest = () => ({});
        const saasMediaAssetJobIsConceptOnly = () => true;
        const saasMediaAssetJobStatusLabel = () => '仅供概念参考';
        const saasMediaManifestAssetCards = () => empty ? [] : [{ key: 'main', label: '概念参考', title: '本地合成素材', body: '用于界面回归，不是商品图片',
          url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="600" height="450"%3E%3Crect width="600" height="450" fill="%23eef3f0"/%3E%3Ctext x="80" y="230" font-size="28"%3ELocal test fixture%3C/text%3E%3C/svg%3E' }];
        const trustedJiejingHtml = html => html;
        const replaceJiejingTrustedHtml = (node, html) => node.outerHTML = html;
        const insertJiejingTrustedHtml = (node, position, html) => node.insertAdjacentHTML(position, html);
        ${extract("renderSaasFirstRunAssuranceStrip")}
        ${extract("ensureSaasMediaFirstRunStrip")}
        ${extract("renderSaasMediaGeneratedAssetsPanel")}
        ${extract("placeSaasMediaResultPanels")}
        function refreshFixture() {
          const strip = ensureSaasMediaFirstRunStrip();
          const existing = document.querySelector('.saas-media-generated-assets');
          if (existing) existing.outerHTML = renderSaasMediaGeneratedAssetsPanel();
          else strip.insertAdjacentHTML('afterend', renderSaasMediaGeneratedAssetsPanel());
          placeSaasMediaResultPanels();
        }
        refreshFixture();
      ` });
      const guide = page.locator(".saas-media-usage-guide");
      const result = page.locator(".saas-media-generated-assets");
      assert.equal(await guide.getAttribute("open"), null);
      assert.equal(await page.locator(".saas-media-usage-guide .saas-media-generated-assets").count(), 0);
      assert.equal(await result.isVisible(), true);
      assert.match(await result.innerText(), /概念参考图不可用于刊登/);
      const box = await result.boundingBox();
      assert.ok(box.y < 400, `results start near top at ${viewport.width}: ${box.y}`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.screenshot({ path: path.join(outDir, `media-${viewport.width}.png`) });
      await guide.locator("summary").focus();
      await page.keyboard.press("Enter");
      assert.equal(await guide.evaluate(node => node.open), true);
      assert.equal(await page.locator(".media-pipeline").isVisible(), true);
      assert.equal(await page.locator(".saas-media-first-run-strip").isVisible(), true);
      await page.evaluate(() => { refreshFixture(); refreshFixture(); });
      assert.equal(await page.locator(".saas-media-generated-assets").count(), 1);
      assert.equal(await page.locator(".saas-media-first-run-strip").count(), 1);
      assert.equal(await guide.evaluate(node => node.open), true);
      assert.equal(await page.locator('[data-media-channel="flow"]').isVisible(), true);
      assert.equal(await page.locator('[data-media-channel="independent"]').isVisible(), true);
      await page.evaluate(() => { empty = true; refreshFixture(); });
      assert.match(await result.innerText(), /等待当前商品和素材清单/);
      assert.equal(await result.locator("img").count(), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log(`Offline screenshots: ${outDir}`);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
