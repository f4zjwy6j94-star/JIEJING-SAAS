#!/usr/bin/env node
/* Reuse the downloaded live media proof to verify the merchant media UI. */

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");

const root = path.resolve(__dirname, "..");
const proof = JSON.parse(
  fs.readFileSync(path.join(root, "output", "jiejing-controlled-media-video-proof", "revalidated-latest.json"), "utf8"),
);
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(root, "output", "browser-smoke", `${stamp}-media-video-artifact-ui`);
fs.mkdirSync(outDir, { recursive: true });

async function main() {
  const browser = await chromium.launch({ channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error?.message || error)));
    const appUrl = `${pathToFileURL(path.join(root, "app.html")).href}?start=app&view=media&onboarded=1&qa=public-saas`;
    await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForFunction(
      () => typeof state === "object" && typeof setView === "function" && typeof renderMediaQualityBoard === "function",
      null,
      { timeout: 60000 },
    );
    await page.evaluate(
      ({ imageUrl, videoUrl, duration }) => {
        setView("media");
        state.saasListingComposerDraft = {
          source_type: "controlled_media_capability_proof",
          product: "Adjustable Drawer Dividers - capability proof",
          title: "Adjustable Drawer Dividers - capability proof",
          fields: { title: "Adjustable Drawer Dividers - capability proof", images: "" },
        };
        state.activeListingDraft = "";
        state.activeMediaDraft = "saas-controlled-media-proof";
        state.mediaGenerationStatus = "generated";
        state.saasMediaAssetJobs = [
          {
            media_job_id: "controlled-live-image-video-proof",
            status: "waiting_review",
            live_provider_called: true,
            spend_now_allowed: false,
            secret_exposed: false,
            asset_manifest_validation: { status: "manifest_ready" },
            asset_manifest: [
              {
                asset_id: "controlled-image-01",
                asset_type: "product_image",
                url: imageUrl,
                url_or_file_path: imageUrl,
                dimensions: "1024x1024",
                commercial_use_status: "needs_review",
                fact_review_status: "needs_review",
                listing_use_status: "not_ready_for_listing_until_review",
              },
              {
                asset_id: "controlled-video-01",
                asset_type: "product_video",
                url: videoUrl,
                url_or_file_path: videoUrl,
                dimensions: `${duration}s`,
                duration_seconds: duration,
                commercial_use_status: "needs_review",
                fact_review_status: "needs_review",
                listing_use_status: "not_ready_for_listing_until_review",
              },
            ],
          },
        ];
        renderMediaQualityBoard(readMediaGenerationConfig({ videoPreset: "10 秒产品展示视频" }));
        refreshSaasMediaGeneratedAssetSurfaces();
      },
      {
        imageUrl: pathToFileURL(proof.image_path).href,
        videoUrl: pathToFileURL(proof.video_path).href,
        duration: proof.video_duration_seconds,
      },
    );
    await page.waitForSelector('#view-media.is-active [data-asset-preview^="manifest:"] video', { timeout: 30000 });
    const videoCard = page.locator('#view-media.is-active [data-asset-preview^="manifest:"]:has(video)').first();
    await videoCard.click();
    await page.waitForSelector("#assetModal:not([hidden]) video", { timeout: 30000 });
    await page.waitForFunction(
      () => {
        const video = document.querySelector("#assetModal:not([hidden]) video");
        return Boolean(video && video.readyState >= 1 && Number.isFinite(video.duration) && video.duration > 0);
      },
      null,
      { timeout: 30000 },
    );
    const result = await page.evaluate(() => {
      const modal = document.querySelector("#assetModal:not([hidden])");
      const video = modal?.querySelector("video");
      const checks = Array.from(modal?.querySelectorAll("[data-media-review-check]") || []);
      const button = modal?.querySelector("#assetSendConfirm");
      const disabledBefore = Boolean(button?.disabled);
      checks.forEach((check) => {
        check.checked = true;
        check.dispatchEvent(new Event("change", { bubbles: true }));
      });
      return {
        modal_visible: Boolean(modal && !modal.hidden),
        video_ready_state: Number(video?.readyState || 0),
        video_duration: Number(video?.duration || 0),
        video_width: Number(video?.videoWidth || 0),
        video_height: Number(video?.videoHeight || 0),
        review_check_count: checks.length,
        review_button_disabled_before: disabledBefore,
        review_button_enabled_after: Boolean(button && !button.disabled),
        exposes_provider_brand: /\bFAL\b|fal\.ai|API key|refresh token/i.test(modal?.innerText || ""),
        has_direct_publish_copy: /直接发布|一键发布|自动发布到 eBay/.test(modal?.innerText || ""),
        contains_current_product: /Adjustable Drawer Dividers/.test(modal?.innerText || ""),
        contains_legacy_demo: /倒流香|香炉|Backflow Incense|incense burner|香粒/i.test(modal?.innerText || ""),
      };
    });
    await page.screenshot({ path: path.join(outDir, "media-video-preview.png"), fullPage: true });
    const checks = {
      live_video_preview_loaded:
        result.modal_visible && result.video_ready_state >= 1 && result.video_duration > 0 && result.video_width > 0 && result.video_height > 0,
      review_gate_complete:
        result.review_check_count >= 3 && result.review_button_disabled_before && result.review_button_enabled_after,
      merchant_boundary_clean:
        result.contains_current_product && !result.contains_legacy_demo && !result.exposes_provider_brand && !result.has_direct_publish_copy,
      no_page_errors: pageErrors.length === 0,
    };
    const output = { ok: Object.values(checks).every(Boolean), checks, result, page_errors: pageErrors, output_root: outDir };
    fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(output, null, 2));
    console.log(JSON.stringify(output, null, 2));
    if (!output.ok) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error?.stack || error);
  process.exit(1);
});
