const fs = require('fs');
const path = require('path');
const { chromium } = require('/workspace/JIEJING-SAAS/output/codex-playwright-deps/node_modules/playwright-core');
const out = process.env.JIEJING_V9_OUTPUT || '/workspace/jiejing-deliverables/11.0/20261007-product-rework-v9';
const base = process.env.JIEJING_V9_PREVIEW || 'http://127.0.0.1:8819';
const times = [0, 1.5, 5.2, 7.7, 9.65, 11.6, 13.8, 15.7, 18.6, 19.75, 21.7, 23.4, 25.4, 28.5];
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true });
  const errors = [], failedRequests = [];
  fs.mkdirSync(path.join(out, 'qa-frames'), { recursive: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
    page.on('pageerror', e => errors.push(e.message));
    page.on('requestfailed', r => failedRequests.push({url:r.url(),failure:r.failure()}));
    page.on('request', r => { if (new URL(r.url()).origin !== base) errors.push('Unexpected external request: ' + r.url()); });
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => document.querySelector('audio').readyState >= 4, null, {timeout:30000});
    const frames = [];
    for (const time of times) {
      await page.evaluate(t => { window.__timelines.main.seek(t); }, time);
      const file = `qa-frames/frame-${time.toFixed(2).replace('.', '-')}.png`;
      await page.screenshot({ path: path.join(out, file) });
      const state = await page.evaluate(() => ({
        images: [...document.images].map(i => ({ source: i.getAttribute('src'), decoded: i.complete && i.naturalWidth > 0 })),
        captions: [...document.querySelectorAll('.caption')].filter(x => getComputedStyle(x).visibility === 'visible').map(x => ({ text: x.textContent, x:x.getBoundingClientRect().x, width:x.getBoundingClientRect().width })),
        duration: window.__timelines.main.duration(),
      }));
      frames.push({time, file, ...state});
    }
    const badImages = frames.some(f => f.images.some(i => !i.decoded));
    const badCaptions = frames.some(f => f.captions.some(c => c.x < 30 || c.x + c.width > 1030));
    const ok = !errors.length && !failedRequests.length && !badImages && !badCaptions;
    fs.writeFileSync(path.join(out, 'BROWSER_FRAMES.safe.json'), JSON.stringify({exit_code: ok ? 0 : 1, browser: 'Existing Playwright Chromium; Browser/IAB tool unavailable', errors, failedRequests, frames}, null, 2));
    console.log(JSON.stringify({exit_code: ok ? 0 : 1, frames: frames.length, errors, failedRequests}));
    if (!ok) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
