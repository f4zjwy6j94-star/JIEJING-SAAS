#!/usr/bin/env node
"use strict";

// Invoked by the Python HTTP suite with an owned, temporary API and session on
// stdin. Only startup is removed from app.js; no business API is mocked here.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
let diagnostic = { stage: "startup" };

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const fixture = JSON.parse(input);
  const api = new URL(fixture.api_base);
  assert.equal(api.protocol, "http:");
  assert.equal(api.hostname, "127.0.0.1", "only the owned loopback API is permitted");
  assert.ok(api.port && !api.username && !api.password);
  const root = path.resolve(__dirname, "..");
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const boot = /exposeLocalJiejingTestHooks\(\);\r?\ninit\(\);\r?\nrunLocalJiejingQaScenarioFromUrl\(\);\s*$/;
  assert.match(source, boot);
  const app = source.replace(boot, "exposeLocalJiejingTestHooks();\n");
  const html = fs.readFileSync(path.join(root, "app.html"), "utf8")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<link\b[^>]*>/gi, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace("</body>", '<script src="/app.js"></script></body>');
  const checkpointPath = `/stores/${fixture.store_id}/listing-drafts/${fixture.identity.key}/checkpoint`;
  const statusPath = `/stores/${fixture.store_id}/merchant-project-status`;
  const factPath = `/stores/${fixture.store_id}/product-facts`;
  const precheckPath = `/stores/${fixture.store_id}/publish-precheck`;
  const confirmationPaths = ["publish-confirmation", "ebay-draft-confirmation"].map(name => `/stores/${fixture.store_id}/${name}`);
  const newMediaScenario = fixture.scenario === "new-media-after-generation";
  const wizardScenario = fixture.scenario === "unchanged-facts-wizard" || newMediaScenario;
  const requests = [], forbidden = [], errors = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "GET" && ["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname === "/app.js" ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname === "/app.js" ? app : html);
    }
    const checkpointRequest = url.pathname === checkpointPath && ["GET", "POST"].includes(req.method);
    const statusRequest = url.pathname === statusPath && req.method === "GET"
      && url.searchParams.size === 1 && url.searchParams.get("project_id") === fixture.identity.key;
    const wizardRequest = wizardScenario && ((url.pathname === factPath && req.method === "POST")
      || (url.pathname === "/reports" && req.method === "GET"));
    const safetyRequest = newMediaScenario && (([precheckPath, ...confirmationPaths].includes(url.pathname) && req.method === "POST")
      || (["/tasks", "/confirmations"].includes(url.pathname) && req.method === "GET"));
    if (!checkpointRequest && !statusRequest && !wizardRequest && !safetyRequest) {
      forbidden.push("unapproved_request"); res.writeHead(404); return res.end();
    }
    // The browser's real HttpOnly session cookie is forwarded unchanged. The
    // Python server, not this proxy, authenticates and applies all persistence.
    if (checkpointRequest || wizardRequest || safetyRequest) requests.push({ method: req.method, path: url.pathname,
      query: Object.fromEntries(url.searchParams) });
    const upstream = http.request(new URL(req.url, api), { method: req.method, headers: req.headers }, (response) => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    upstream.on("error", () => { errors.push("loopback_proxy_failure"); res.writeHead(502); res.end(); });
    req.pipe(upstream);
  });
  let browser;
  try {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ headless: true, channel: process.env.JIEJING_PLAYWRIGHT_CHANNEL || "chrome" });
    if (wizardScenario) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await context.addCookies([{ name: "jiejing_saas_session", value: fixture.session_token,
        url: base, httpOnly: true, sameSite: "Lax" }]);
      const page = await context.newPage();
      page.on("pageerror", () => errors.push("page_error"));
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        if (url.origin === base) return route.continue();
        if (url.href === "https://media.example.test/approved-gold-set.jpg") return route.fulfill({
          status: 200, contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="gold"/></svg>' });
        forbidden.push("foreign_request"); return route.abort();
      });
      const query = new URLSearchParams({ source_report_id: fixture.identity.source_report_id,
        candidate_id: fixture.identity.candidate_id });
      async function readCheckpoint() {
        const response = await context.request.get(`${base}${checkpointPath}?${query}`);
        assert.equal(response.status(), 200);
        return response.json();
      }
      async function mount(startStep) {
        await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${fixture.identity.key}`);
        await page.evaluate(async ({ fixture, base, startStep }) => {
          window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
          localStorage.setItem(saasStorageKeys.storeId, fixture.store_id);
          localStorage.setItem(saasStorageKeys.sessionHint, "1");
          localStorage.setItem("jiejing_saas_backend_session_hint", "1");
          state.saasApiBase = base;
          state.saasIdentity = fixture.profile.identity; state.saasUser = fixture.profile.user;
          state.saasCompany = fixture.profile.company; state.saasPermissions = fixture.profile.permissions;
          state.saasStores = [{ store_id: fixture.store_id, company_id: fixture.profile.identity.company_id,
            platform: "ebay", marketplace: "EBAY_US", status: "authorized" }];
          state.saasConnected = true; state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false;
          state.saasTasks = []; state.saasListingMode = "single"; state.saasLoading = false;
          state.saasAccountHealth = { store_id: fixture.store_id, company_id: fixture.profile.identity.company_id,
            status: "restricted", incident_mode: true, can_execute_real_writes: false };
          const reports = await saasFetch(`/reports?store_id=${encodeURIComponent(fixture.store_id)}&limit=24`);
          state.saasReports = reports.reports;
          state.saasListingComposerDraft = null; state.saasDetachedListingProjectDrafts = {};
          state.view = "product"; syncSaasPublicMvpMode(); bindEvents();
          restoreSaasListingComposerDraftFromBackendReports({ preferBackendLatest: true, projectId: fixture.identity.key });
          await refreshSaasMerchantProjectStatus();
          await hydrateSaasListingCloudCheckpoint({ force: true });
          [entryShell, siteShell, onboardingShell].forEach(shell => shell.classList.add("is-hidden"));
          appShell.classList.remove("is-hidden"); document.body.classList.remove("site-locked");
          document.body.dataset.view = "product";
          document.querySelectorAll(".view").forEach(view => view.classList.toggle("is-active", view.id === "view-product"));
          setSaasListingWizardStep(startStep); renderProductListingCenter();
        }, { fixture: { ...fixture, session_token: undefined }, base, startStep });
        diagnostic.mount = await page.evaluate(() => ({ draft_exists: Boolean(state.saasListingComposerDraft),
          context_exists: Boolean(saasListingCloudContext()), step: saasListingWizardRecord()?.step,
          reports: state.saasReports.length, panels: document.querySelectorAll("[data-listing-wizard-step]").length }));
        assert.equal(await page.locator(`#view-product [data-listing-wizard-step="${startStep}"]`).isVisible(), true);
        if (fixture.expected_unknown_fields?.length) {
          const restored = await page.evaluate(() => saasMerchantProductFactPacket());
          for (const key of fixture.expected_unknown_fields) {
            assert.ok(restored.unknown_facts.includes(key), `${key}: explicit unknown must survive cold restore`);
            assert.equal(restored.derived_listing_suggestions[key], undefined, `${key}: rejected historical suggestion must not revive`);
          }
        }
      }
      async function move(direction, expectedStep) {
        const beforeMove = await page.evaluate(() => ({ signature: JSON.parse(saasListingMediaCopyFactSignature(saasMerchantProductFactPacket())),
          revision: saasListingCloudRecord()?.revision, seq: saasListingCloudRecord()?.seq }));
        await page.locator(`#view-product [data-saas-action="listing-wizard-${direction}"]`).click();
        await page.waitForFunction(() => !saasListingWizardRecord()?.busy);
        const actual = await page.evaluate(() => ({ step: saasListingWizardRecord()?.step,
          status: saasListingCloudRecord()?.status, conflict: Boolean(saasListingCloudRecord()?.conflict) }));
        diagnostic.navigation = actual;
        if (actual.step !== expectedStep) diagnostic.fact_signature_difference = await page.evaluate(() => {
          const current = JSON.parse(saasListingMediaCopyFactSignature(state.saasListingComposerDraft.merchant_product_fact_packet));
          const generated = state.saasReports.find(item => item.runtime_run_id === "listing_draft_generation");
          const prior = JSON.parse(saasListingMediaCopyFactSignature(generated?.report?.merchant_product_fact_packet));
          return Object.keys({ ...current, ...prior }).filter(key => JSON.stringify(current[key]) !== JSON.stringify(prior[key]));
        });
        if (actual.step !== expectedStep) diagnostic.transition_difference = await page.evaluate(before => {
          const packet = JSON.parse(saasListingMediaCopyFactSignature(saasMerchantProductFactPacket()));
          const record = saasListingCloudRecord();
          return { keys: Object.keys({ ...packet, ...before.signature }).filter(key => JSON.stringify(packet[key]) !== JSON.stringify(before.signature[key])),
            revision_changed: before.revision !== record?.revision, sequence_changed: before.seq !== record?.seq,
            base_type: saasListingCloudBaseReport(record.context)?.report_type,
            source_matches_base: state.saasListingComposerDraft.source_product_fact_report_id === saasListingCloudBaseReport(record.context)?.report_id,
            fact_save_status: state.saasListingProductFactSaveStatus,
            project_reports: state.saasReports.filter(report => saasListingCloudReportMatchesContext(report, record.context))
              .map(report => ({ type: report.report_type, created_at: report.created_at,
                is_source: report.report_id === state.saasListingComposerDraft.source_product_fact_report_id })) };
        }, beforeMove);
        assert.equal(actual.step, expectedStep, "wizard navigation must complete through the actual save handlers");
        assert.equal(await page.locator(`#view-product [data-listing-wizard-step="${expectedStep}"]`).isVisible(), true,
          "the destination wizard panel must actually be visible");
      }
      async function intakeValues() {
        return page.locator("#saasPublishIntakeForm").evaluate(form => Object.fromEntries(
          [...form.elements].filter(item => item.name).map(item => [item.name, item.type === "checkbox" ? item.checked : item.value])));
      }
      diagnostic.stage = "initial_restore";
      await mount(2);
      diagnostic.stage = "initial_copy_restored";
      if (!newMediaScenario) {
        const sourceProjection = await page.evaluate(() => {
          const draft = state.saasListingComposerDraft;
          const report = state.saasReports.find(item => item.report_id === draft.source_product_fact_report_id);
          return { actual: sanitizeSaasMerchantProductFactPacketSnapshot(draft.merchant_product_fact_packet).source_records,
            expected: sanitizeSaasMerchantProductFactPacketSnapshot(report.report.merchant_product_fact_packet).source_records };
        });
        diagnostic.source_projection_equal = require("node:util").isDeepStrictEqual(sourceProjection.actual, sourceProjection.expected);
        assert.deepEqual(sourceProjection.actual, sourceProjection.expected,
          "current authoritative sources must survive history restore without loss or obsolete duplicates");
      }
      diagnostic.initial_title_matches = (await page.locator('#view-product [data-saas-listing-draft-field="title"]').inputValue()) === fixture.expected_copy.title;
      assert.equal(diagnostic.initial_title_matches, true);
      diagnostic.stage = "copy_to_images";
      await move("next", 3);
      if (newMediaScenario) {
        diagnostic.stage = "first_image_rights_save";
        await page.getByText("查看或补充已有图片地址（可选）", { exact: true }).click();
        await page.locator('[data-saas-product-fact-field="image_urls"]').fill("https://media.example.test/approved-gold-set.jpg");
        await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').check();
      }
      diagnostic.stage = "images_to_publish";
      const initialFactSave = fixture.saved_fact_noop ? page.waitForResponse(response =>
        new URL(response.url()).pathname === `/stores/${fixture.store_id}/product-facts` &&
        response.request().method() === "POST").then(response => response.json()) : null;
      await move("next", 4);
      if (initialFactSave) {
        const savedFact = await initialFactSave;
        const currentCheckpoint = await readCheckpoint();
        diagnostic.initial_fact_save_unchanged = savedFact.unchanged === true;
        diagnostic.initial_checkpoint_base_type = currentCheckpoint.current_base_report.report_type;
        assert.equal(savedFact.unchanged, true, "the real fact API must reuse the existing immutable head");
        assert.equal(currentCheckpoint.base_changed, false);
        assert.equal(currentCheckpoint.current_base_report.report_type, "listing.package");
      }
      diagnostic.stage = "edit_publish_intake";
      await page.getByRole("button", { name: "编辑发布资料", exact: true }).click();
      const firstForm = page.locator("#saasPublishIntakeForm");
      assert.equal(await firstForm.isVisible(), true);
      if (newMediaScenario) {
        const saved = await readCheckpoint();
        diagnostic = { ...diagnostic, stage: "media_publish_copy_projection",
          checkpoint_copy_present: saved.checkpoint.fields.title === fixture.expected_copy.title &&
            saved.checkpoint.fields.description === fixture.expected_copy.description,
          base_changed: saved.base_changed,
          publish_title_present: Boolean(await firstForm.locator('[name="title"]').inputValue()),
          publish_description_present: Boolean(await firstForm.locator('[name="description_html"]').inputValue()) };
        assert.equal(await firstForm.locator('[name="title"]').inputValue(), fixture.expected_copy.title,
          "saving the first merchant-attested image must not blank already validated buyer copy");
        assert.ok((await firstForm.locator('[name="description_html"]').inputValue()).includes(fixture.expected_copy.description));
        assert.equal(saved.base_changed, false);
        assert.deepEqual(saved.checkpoint.merchant_edited_fields, []);
        const modelGenerated = await page.evaluate(() => state.saasListingComposerDraft.model_generated);
        assert.equal(modelGenerated, false, "a checkpoint must not invent a new generation proof");
        diagnostic.stage = "media_copy_cold_reload";
        await mount(4);
        await page.getByRole("button", { name: "编辑发布资料", exact: true }).click();
        assert.equal(await page.locator('#saasPublishIntakeForm [name="title"]').inputValue(), fixture.expected_copy.title);
        assert.ok((await page.locator('#saasPublishIntakeForm [name="description_html"]').inputValue()).includes(fixture.expected_copy.description));
        const blockers = [];
        async function businessCounts() {
          const counts = {};
          for (const name of ["tasks", "reports", "confirmations"]) {
            const response = await context.request.get(`${base}/${name}?store_id=${encodeURIComponent(fixture.store_id)}`);
            assert.equal(response.status(), 200);
            counts[name] = (await response.json())[name].length;
          }
          return counts;
        }
        async function preparedPayload() {
          diagnostic.stage = "prepare_source_guard_form";
          const form = page.locator("#saasPublishIntakeForm");
          assert.equal(await form.locator('[name="title"]').inputValue(), fixture.expected_copy.title);
          assert.ok((await form.locator('[name="description_html"]').inputValue()).includes(fixture.expected_copy.description));
          await form.locator('[name="category_id"]').fill("20552");
          await form.locator('[name="price"]').fill("12.99");
          await page.evaluate(() => flushSaasListingCloudCheckpoint());
          return page.evaluate(() => readSaasPublishIntakeForm());
        }
        async function assertSourceBlocked(payload, blocker, { dom = false } = {}) {
          diagnostic.stage = `source_guard_${blocker}`;
          const before = await businessCounts();
          const check = await context.request.post(`${base}${precheckPath}`, { data: { ...payload, simulation_only: false } });
          assert.equal(check.status(), 200);
          const receipt = await check.json();
          assert.deepEqual(receipt.source_blockers, [blocker]);
          for (const key of ["confirmation_created", "task_created", "platform_write_attempted", "real_execution_allowed"]) {
            assert.equal(receipt[key], false);
          }
          if (dom) {
            // Exercise the same real confirmation handler used by the button.
            // This fixture has no synced eBay packet, so do not forge account
            // authorization merely to enable the UI's additional account gate.
            const denied = page.waitForResponse(response => new URL(response.url()).pathname === confirmationPaths[1]
              && response.request().method() === "POST");
            const accepted = page.evaluate(() => createSaasPublishConfirmationFromIntakeForm("ebay-draft"));
            const response = await denied;
            assert.equal(response.status(), 422);
            const rejection = await response.json();
            assert.deepEqual(rejection.blockers, [blocker]);
            assert.equal(rejection.confirmation_created, false);
            assert.equal(await accepted, false);
          }
          // A client cannot bypass the same source protection by forging its
          // simulation flag or calling either confirmation endpoint directly.
          for (const endpoint of confirmationPaths) {
            const response = await context.request.post(`${base}${endpoint}`, { data: { ...payload, simulation_only: false } });
            assert.equal(response.status(), 422);
            const rejection = await response.json();
            assert.deepEqual(rejection.blockers, [blocker]);
            assert.equal(rejection.confirmation_created, false);
          }
          assert.deepEqual(await businessCounts(), before, "source denials must not create tasks, reports or confirmations");
          blockers.push(blocker);
        }
        if (fixture.simulation_only) {
          const payload = await preparedPayload();
          const beforePosts = requests.filter(item => confirmationPaths.includes(item.path)).length;
          assert.equal(await page.evaluate(() => createSaasPublishConfirmationFromIntakeForm("ebay-draft")), false);
          assert.equal(requests.filter(item => confirmationPaths.includes(item.path)).length, beforePosts,
            "the real confirmation handler must reject simulation before HTTP");
          assert.match(await page.locator("body").textContent(), /不能创建 eBay/);
          assert.equal(payload.simulation_only, true);
          await assertSourceBlocked(payload, "simulation_only_product_facts");
        } else {
          let payload = await preparedPayload();
          const cleanCheck = await context.request.post(`${base}${precheckPath}`, { data: payload });
          assert.equal(cleanCheck.status(), 200);
          assert.deepEqual((await cleanCheck.json()).source_blockers, [],
            "non-simulation fixture must first pass authenticated source and rights validation");
          await page.evaluate(job => { state.saasMediaAssetJobs = [job]; }, fixture.pending_media);
          assert.equal((await page.evaluate(() => readSaasPublishIntakeForm())).publish_evidence_refs.media_job_id, "",
            "a pending media job cannot enter the actual publication form as approved evidence");
          await assertSourceBlocked({ ...payload, publish_evidence_refs: { ...payload.publish_evidence_refs,
            media_job_id: fixture.pending_media.media_job_id } }, "media_job_not_approved");
          for (const mode of ["revoke-rights", "clear-images"]) {
            diagnostic.stage = mode;
            await mount(3);
            if (mode === "clear-images") {
              await page.getByText("查看或补充已有图片地址（可选）", { exact: true }).click();
              await page.locator('[data-saas-product-fact-field="image_urls"]').fill("");
              await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').check();
            } else await page.locator('[data-saas-product-fact-field="image_rights_confirmed"]').uncheck();
            await move("next", 3);
            const afterSave = await readCheckpoint();
            assert.equal(afterSave.base_changed, false);
            assert.equal(afterSave.checkpoint.fields.title, fixture.expected_copy.title);
            await mount(4);
            await page.getByRole("button", { name: "编辑发布资料", exact: true }).click();
            payload = await preparedPayload();
            if (mode === "clear-images") assert.deepEqual(payload.asset_manifest.assets, [],
              "no former image may be restored into the publish form");
            else {
              assert.notEqual(afterSave.current_base_report.report.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed, true);
              assert.notEqual(await page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet.merchant_confirmed_facts.image_rights_confirmed), true);
            }
            await assertSourceBlocked(payload, mode === "clear-images" ? "image_assets_missing" : "image_rights_not_attested", { dom: true });
          }
        }
        assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
        await context.close();
        process.stdout.write(JSON.stringify({ scenario: fixture.scenario, copy_preserved: true,
          cold_reload_preserved: true, model_generated_after_checkpoint: modelGenerated,
          base_changed: saved.base_changed, external_requests: 0, page_errors: 0,
          source_blockers: blockers, denials_created_no_business_records: true, confirmation_entry_exercised: true }));
        return;
      }
      const costs = { shipping_cost: "4.20", ebay_fee: "2.07", ad_budget: "0", return_risk_reserve: "0.65",
        exchange_rate: "1", net_profit: "3.57", gross_margin_percent: "27.48" };
      for (const [key, value] of Object.entries(costs)) await firstForm.locator(`[name="${key}"]`).fill(value);
      await page.locator('#view-product [data-saas-listing-cloud-action="save-publish-intake"]').click();
      await page.waitForFunction(() => saasListingCloudRecord()?.status === "saved" && !saasListingCloudRecord()?.dirty);
      const beforeReload = await intakeValues();
      diagnostic.stage = "cold_reload";
      await mount(4);
      assert.deepEqual(await intakeValues(), beforeReload, "all published-form controls must survive the real checkpoint reload");
      const before = await readCheckpoint();
      diagnostic.stage = "unchanged_facts_roundtrip";
      await move("previous", 3); await move("previous", 2); await move("previous", 1);
      const beforeSignature = await page.evaluate(() => saasListingMediaCopyFactSignature(saasMerchantProductFactPacket(), { includeMedia: true }));
      await move("next", 2);
      await page.evaluate(async () => { if (saasListingCloudRecord()?.read) await saasListingCloudRecord().read; });
      const after = await readCheckpoint();
      const afterSignature = await page.evaluate(() => saasListingMediaCopyFactSignature(saasMerchantProductFactPacket(), { includeMedia: true }));
      const oldPacket = before.current_base_report.report.merchant_product_fact_packet;
      const newPacket = after.current_base_report.report.merchant_product_fact_packet;
      const packetEqual = require("node:util").isDeepStrictEqual(oldPacket, newPacket);
      const signatureBefore = JSON.parse(beforeSignature), signatureAfter = JSON.parse(afterSignature);
      diagnostic = { ...diagnostic, server_packets_equal: packetEqual,
        before_revision: before.current_revision, after_revision: after.current_revision,
        base_changed: after.base_changed, base_id_advanced: before.current_base_report_id !== after.current_base_report_id,
        signature_changed_keys: Object.keys(signatureBefore).filter(key => JSON.stringify(signatureBefore[key]) !== JSON.stringify(signatureAfter[key])),
        checkpoint_post_count: requests.filter(item => item.method === "POST" && item.path === checkpointPath).length };
      assert.equal(packetEqual, true, "unchanged UI must persist semantically identical server fact packets");
      assert.equal(after.base_changed, false, "an unchanged save must not strand the checkpoint on its former fact base");
      assert.equal(await page.getByRole("button", { name: "保留本机修改并重新保存", exact: true }).count(), 0,
        "an unchanged roundtrip must not ask the merchant to resolve a manufactured conflict");
      for (const key of ["title", "selling_points", "description"]) {
        assert.equal(after.checkpoint.fields[key], fixture.expected_copy[key]);
        assert.equal(await page.locator(`#view-product [data-saas-listing-draft-field="${key}"]`).inputValue(), fixture.expected_copy[key]);
      }
      assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
      await context.close();
      process.stdout.write(JSON.stringify({ ...diagnostic, scenario: fixture.scenario,
        no_conflict: true, external_requests: 0, page_errors: 0, restored_publish_fields: Object.keys(beforeReload).length }));
      return;
    }
    const keys = ["title", "selling_points", "description", "category", "item_specifics", "keywords", "price", "images", "logistics", "risk_notes"];
    const visibleKeys = keys.filter((key) => !["keywords", "risk_notes"].includes(key));
    const originalFields = Object.fromEntries(keys.map((key) => [key, `Original ${key}`]));
    const edited = { ...originalFields, title: "", category: "", selling_points: "Merchant point one\nMerchant point two",
      description: "Merchant FAL description stays exact", item_specifics: "Material: Aluminum", price: "29.00 USD",
      images: "Merchant photo still required", logistics: "Weight to be confirmed" };
    async function device() {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.addCookies([{ name: "jiejing_saas_session", value: fixture.session_token,
        url: base, httpOnly: true, sameSite: "Lax" }]);
      const page = await context.newPage();
      page.on("pageerror", () => errors.push("page_error"));
      await page.route("**/*", (route) => {
        if (new URL(route.request().url()).origin === base) return route.continue();
        forbidden.push("foreign_request"); return route.abort();
      });
      await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${fixture.identity.key}`);
      assert.equal(await page.evaluate(() => localStorage.length), 0);
      await page.evaluate(({ fixture, base, originalFields }) => {
        window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
        localStorage.setItem(saasStorageKeys.storeId, fixture.store_id);
        localStorage.setItem("jiejing_saas_backend_session_hint", "1");
        localStorage.setItem("jiejing_saas_session_hint", "1");
        state.saasApiBase = base;
        state.saasIdentity = fixture.profile.identity;
        state.saasUser = fixture.profile.user;
        state.saasCompany = fixture.profile.company;
        state.saasPermissions = fixture.profile.permissions;
        state.saasStores = [{ store_id: fixture.store_id, company_id: fixture.profile.identity.company_id,
          platform: "ebay", marketplace: "EBAY_US" }];
        state.saasReports = [fixture.base_report]; state.saasTasks = [];
        state.saasProtectedStateReady = true;
        state.saasListingComposerDraft = { product: "Foldable Tablet Stand", title: "Original title",
          source_report_id: fixture.base_report.report_id, listing_project_identity: fixture.identity,
          fields: { ...originalFields }, merchant_edited_fields: [], model_generated: false, safe_local_only: true };
        state.saasDetachedListingProjectDrafts = {}; state.view = "product";
        bindEvents();
        document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
      }, { fixture: { ...fixture, session_token: undefined }, base, originalFields });
      return { context, page };
    }
    const first = await device();
    assert.equal(await first.page.locator("[data-saas-listing-draft-field]").count(), 8);
    const posted = first.page.waitForResponse((response) => new URL(response.url()).pathname === checkpointPath
      && response.request().method() === "POST", { timeout: 10000 }).catch(() => null);
    for (const key of visibleKeys) await first.page.locator(`[data-saas-listing-draft-field="${key}"]`).fill(edited[key]);
    const response = await posted;
    assert.ok(response, "actual input must reach the real Python checkpoint POST");
    assert.equal(response.status(), 201);
    const receipt = await response.json();
    assert.deepEqual(receipt.checkpoint.fields, edited);
    assert.equal(receipt.checkpoint.base_report_id, fixture.base_report.report_id);
    assert.deepEqual(receipt.checkpoint.listing_project_identity, fixture.identity);
    assert.equal(receipt.model_called || receipt.usage_consumed || receipt.real_platform_writes_enabled, false);
    await first.page.evaluate(() => flushSaasListingCloudCheckpoint());
    async function mountIntake(page) {
      await page.evaluate(() => {
        const slot = document.createElement("div");
        slot.innerHTML = renderSaasPublishConfirmationIntakePanel(undefined, { includeGuide: false });
        document.body.append(slot);
      });
      return page.locator("#saasPublishIntakeForm");
    }
    const intakeValues = { shipping_cost: "4.20", ebay_fee: "2.07", ad_budget: "0", return_risk_reserve: "0.65",
      exchange_rate: "1", net_profit: "3.57", gross_margin_percent: "27.48", merchant_location_key: "LOCAL-ONLY-TEST", title: "" };
    const firstIntake = await mountIntake(first.page);
    const intakePosted = first.page.waitForResponse((item) => new URL(item.url()).pathname === checkpointPath
      && item.request().method() === "POST", { timeout: 10000 });
    for (const [name, value] of Object.entries(intakeValues)) await firstIntake.locator(`[name="${name}"]`).fill(value);
    const intakeResponse = await intakePosted;
    assert.equal(intakeResponse.status(), 201);
    const intakeReceipt = await intakeResponse.json();
    for (const [name, value] of Object.entries(intakeValues)) assert.equal(intakeReceipt.checkpoint.publish_intake.values[name], value, name);
    await first.page.evaluate(() => flushSaasListingCloudCheckpoint());
    await first.context.close();
    const second = await device();
    await second.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
    for (const key of visibleKeys) assert.equal(await second.page.locator(`[data-saas-listing-draft-field="${key}"]`).inputValue(), edited[key]);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), edited);
    const secondIntake = await mountIntake(second.page);
    for (const [name, value] of Object.entries(intakeValues)) assert.equal(await secondIntake.locator(`[name="${name}"]`).inputValue(), value, name);
    assert.match(await second.page.locator('[data-saas-publish-intake-draft-status]').textContent(), /已云端保存/);
    assert.equal(requests.filter((item) => item.method === "POST").length, 2);
    for (const request of requests.filter((item) => item.method === "GET")) {
      assert.deepEqual(request.query, { source_report_id: fixture.identity.source_report_id, candidate_id: fixture.identity.candidate_id });
    }
    assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
    await second.context.close();
    process.stdout.write(JSON.stringify({ visible_controls: 8, restored_fields: 10, restored_publish_fields: Object.keys(intakeValues).length, post_count: 2,
      get_count: requests.filter((item) => item.method === "GET").length, external_requests: 0, page_errors: 0 }));
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  const reference = error?.name === "ReferenceError" ? String(error.message || "").match(/^([A-Za-z_$][\w$]*) is not defined$/)?.[1] : undefined;
  const failedAt = Number(String(error?.stack || "").match(/test_jiejing_listing_cloud_checkpoint_http_smoke\.js:(\d+):/)?.[1]) || undefined;
  process.stderr.write(JSON.stringify({ error: "checkpoint_http_browser_smoke_failed", ...diagnostic,
    error_kind: ["AssertionError", "TypeError", "ReferenceError", "TimeoutError"].includes(error?.name) ? error.name : "other",
    ...(failedAt ? { fixture_line: failedAt } : {}),
    ...(reference ? { missing_fixture_symbol: reference } : {}) }) + "\n");
  process.exitCode = 1;
});
