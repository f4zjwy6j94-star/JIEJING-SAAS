#!/usr/bin/env node
"use strict";

// Owned loopback integration: actual DOM -> actual Python API -> actual
// checkpoint persistence. Only Python's external model boundary is a fixture.
// Startup is removed from app.js; no business functions are mocked. The optional
// transport fixture discards an already-successful generation response only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("../output/codex-playwright-deps/node_modules/playwright-core");
let diagnosticTag = "";

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const fixture = JSON.parse(input);
  const api = new URL(fixture.api_base);
  assert.equal(api.protocol, "http:");
  assert.equal(api.hostname, "127.0.0.1");
  assert.ok(api.port && !api.username && !api.password, "only an owned loopback API is allowed");
  const fieldKeys = ["title", "selling_points", "description", "category", "item_specifics", "keywords", "price", "images", "logistics", "risk_notes"];
  const copyKeys = ["title", "selling_points", "description"];
  assert.deepEqual(Object.keys(fixture.fields).sort(), [...fieldKeys].sort());
  for (const key of fieldKeys) assert.equal(typeof fixture.fields[key], "string");
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
  const generationPath = `/stores/${fixture.store_id}/listing-drafts/generate`;
  const generationStatusPath = `/stores/${fixture.store_id}/listing-drafts/${fixture.identity.key}/generation-status`;
  const statusPath = `/stores/${fixture.store_id}/merchant-project-status`;
  const requests = [], forbidden = [], errors = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (req.method === "GET" && ["/app.html", "/app.js"].includes(url.pathname)) {
      res.writeHead(200, { "content-type": url.pathname === "/app.js" ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8" });
      return res.end(url.pathname === "/app.js" ? app : html);
    }
    const checkpointRequest = url.pathname === checkpointPath && ["GET", "POST"].includes(req.method);
    const generationRequest = url.pathname === generationPath && req.method === "POST" && !url.search;
    const generationRead = url.pathname === generationStatusPath && req.method === "GET" && url.searchParams.size === 3
      && /^[a-f0-9-]{36}$/i.test(url.searchParams.get("operation_id") || "")
      && url.searchParams.get("source_report_id") === fixture.identity.source_report_id
      && url.searchParams.get("candidate_id") === fixture.identity.candidate_id;
    const statusRequest = url.pathname === statusPath && req.method === "GET"
      && url.searchParams.size === 1 && url.searchParams.get("project_id") === fixture.identity.key;
    const liveScopeRequest = req.method === "GET" && !url.search && ["/me", "/stores"].includes(url.pathname);
    if (!checkpointRequest && !generationRequest && !generationRead && !statusRequest && !liveScopeRequest) {
      forbidden.push("unapproved_request"); res.writeHead(404); return res.end();
    }
    requests.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams) });
    if (generationRequest && fixture.unregistered_first_response && requests.filter((r) => r.path === generationPath).length === 1) {
      // Transport/API boundary before the owned Python server sees a request.
      // No task is fabricated and the real status endpoint must prove not_found.
      req.resume(); res.writeHead(400, { "content-type": "application/json" });
      return res.end(JSON.stringify({ status: "blocked", failure_code: "listing_generation_operation_invalid",
        model_called: false, usage_consumed: false, report: null }));
    }
    // Forward the actual HttpOnly session. This proxy does not authenticate,
    // manufacture model results, or accept checkpoints on behalf of Python.
    const upstream = http.request(new URL(req.url, api), { method: req.method, headers: req.headers }, (response) => {
      if (generationRequest && fixture.lose_generation_response) {
        assert.equal(response.statusCode, 201, "Python saved the report before the transport fixture drops acknowledgement");
        response.resume(); response.on("end", () => {
          res.writeHead(502, { "content-type": "application/json" }); res.end('{"error":"local_transport_fixture"}');
        }); return;
      }
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
    const safeFixture = { ...fixture, session_token: undefined, api_base: undefined };
    async function device(report = fixture.base_report, fresh = false) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await context.addCookies([{ name: "jiejing_saas_session", value: fixture.session_token,
        url: base, httpOnly: true, sameSite: "Lax" }]);
      const page = await context.newPage();
      page.on("pageerror", () => errors.push("page_error"));
      await page.route("**/*", (route) => {
        if (new URL(route.request().url()).origin === base) return route.continue();
        forbidden.push("foreign_request"); return route.abort();
      });
      await page.goto(`${base}/app.html?start=app&qa=public-saas&view=product&project=${fixture.identity.key}`);
      assert.equal(await page.evaluate(() => localStorage.length), 0, "fresh device has no prior draft storage");
      await page.evaluate(({ fixture, base, report, fresh }) => {
        window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
        localStorage.setItem(saasStorageKeys.storeId, fixture.store_id);
        localStorage.setItem(saasStorageKeys.lastAccount, fixture.profile.identity.user_id);
        localStorage.setItem("jiejing_saas_backend_session_hint", "1");
        localStorage.setItem("jiejing_saas_session_hint", "1");
        state.saasApiBase = base;
        state.saasIdentity = fixture.profile.identity;
        state.saasUser = fixture.profile.user;
        state.saasCompany = fixture.profile.company;
        state.saasPermissions = fixture.profile.permissions;
        state.saasStores = [{ store_id: fixture.store_id, company_id: fixture.profile.identity.company_id,
          platform: "ebay", marketplace: "EBAY_US" }];
        state.saasProtectedStateReady = true;
        state.saasReports = [report]; state.saasTasks = []; state.view = "product";
        state.saasListingComposerDraft = fresh ? saasListingDraftFromReport(report) : {
          product: "Foldable Tablet Stand", title: fixture.fields.title,
          source_report_id: fixture.identity.source_report_id, listing_project_identity: fixture.identity,
          fields: { ...fixture.fields }, merchant_edited_fields: [...fixture.merchant_edited_fields],
          merchant_product_fact_packet: sanitizeSaasMerchantProductFactPacketSnapshot(report.report.merchant_product_fact_packet),
          model_generated: false, safe_local_only: true, simulation_only: true,
        };
        state.saasDetachedListingProjectDrafts = {}; bindEvents();
        document.querySelector("#view-product").innerHTML = renderSaasListingDraftEditor();
      }, { fixture: safeFixture, base, report, fresh });
      await page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
      return { page, context };
    }
    const first = await device();
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), fixture.fields);
    const pagePacket = await first.page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);
    assert.ok(Object.hasOwn(pagePacket, "listing_copy") && Object.hasOwn(pagePacket, "saved_at"),
      "the real page snapshot carries UI-only metadata, unlike a backend-only fixture");
    let packetAtSend;
    await first.page.route(`${base}${generationPath}`, async (route) => {
      packetAtSend = await first.page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);
      await route.continue(); // Inspect only: actual bytes still reach the real Python API.
    });
    if (fixture.wire_case) {
      assert.ok(["default", "unknown", "sensitive"].includes(fixture.wire_case));
      if (fixture.wire_case === "default") await first.page.evaluate(() => {
        document.querySelector("#view-product").insertAdjacentHTML("beforeend", renderSaasMerchantProductFactsModule());
      });
      await first.page.evaluate((kind) => {
        const packet = state.saasListingComposerDraft.merchant_product_fact_packet;
        if (kind === "unknown") packet.unrelated_private_note = "fixture unknown field must reach backend rejection";
        if (kind === "sensitive") packet.product_name = "sk-" + "a".repeat(40); // Synthetic rejection sentinel, never a credential.
      }, fixture.wire_case);
      const before = await first.page.evaluate(() => state.saasListingComposerDraft.merchant_product_fact_packet);
      const responsePromise = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath
        && r.request().method() === "POST", { timeout: 15000 }).then((response) => ({ response }), () => ({ missing: true }));
      await first.page.locator(fixture.wire_case === "default"
        ? '[data-saas-action="listing-generate-ai-draft"]' : '[data-saas-action="listing-rewrite-buyer-copy"]').click();
      const observed = await responsePromise;
      if (!observed.response) {
        const feedback = await first.page.evaluate(() => ({
          blocked: state.saasListingAiGenerationStatus === "blocked",
          running: !!state.saasListingAiGenerationInFlight,
          uncertain: state.saasListingComposerDraft?.ai_generation_feedback?.status === "generation_uncertain",
          failed: state.saasListingComposerDraft?.ai_generation_feedback?.status === "failed",
        }));
        diagnosticTag = Object.entries(feedback).map(([key, value]) => `${key}${value ? 1 : 0}`).join("_");
      }
      assert.ok(observed.response, "native action must reach the real API");
      let response = observed.response;
      const body = response.request().postDataJSON();
      if (fixture.unregistered_first_response) {
        assert.equal(response.status(), 400);
        await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
        const proof = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback);
        assert.match(proof.request_signature, /^[a-f0-9]{64}$/);
        assert.equal(proof.operation.expected_base_report_id, null); assert.equal(proof.operation.expected_checkpoint_revision, null);
        await first.page.reload();
        await first.page.evaluate(async ({ fixture, base }) => {
          window.__JIEJING_FORCE_PUBLIC_MVP__ = true; state.saasApiBase = base;
          const [me, storeResponse] = await Promise.all([saasFetch("/me"), saasFetch("/stores")]);
          state.saasIdentity = me.identity; state.saasUser = me.user; state.saasCompany = me.company;
          state.saasPermissions = me.permissions; state.saasStores = storeResponse.stores;
          if (!hydrateSaasProtectedStateFromCache({ me, stores: storeResponse.stores, storeId: fixture.store_id })) throw new Error("fixture_cache_missing");
          state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false;
          state.view = "product"; bindEvents(); renderProductListingCenter();
        }, { fixture: safeFixture, base });
        await first.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
        assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.request_signature), proof.request_signature);
        await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
        await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.resume_available === true);
        assert.equal(requests.filter((request) => request.path === generationPath).length, 1);
        const continued = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath && r.request().method() === "POST", { timeout: 10000 })
          .then((value) => value, () => null);
        await first.page.getByRole("button", { name: "继续本次生成", exact: true }).click();
        response = await continued; assert.ok(response, "signed default continuation reaches the real claim once");
        assert.deepEqual(response.request().postDataJSON(), body);
        await first.page.waitForFunction(() => !saasListingAiGenerationInFlight.size);
      }
      const result = await response.json();
      assert.equal(response.status(), fixture.wire_case === "default" ? 201 : 400);
      assert.ok(Object.hasOwn(packetAtSend, "listing_copy") && Object.hasOwn(packetAtSend, "saved_at"));
      assert.deepEqual(body.merchant_product_fact_packet,
        Object.fromEntries(Object.entries(packetAtSend).filter(([key]) => !["listing_copy", "saved_at"].includes(key))));
      if (fixture.wire_case === "default") {
        assert.equal(body.generation_mode, undefined);
        assert.equal(result.report.report.listing_handoff.listing_fields.buyer_copy_rewrite, undefined);
      } else {
        assert.deepEqual(packetAtSend, before, "wire serialization does not mutate the page packet");
        assert.equal(result.failure_code, "listing_generation_operation_invalid");
        assert.equal(result.model_called, false); assert.equal(result.usage_consumed, false); assert.equal(result.report, null);
      }
      assert.equal(requests.filter((r) => r.path === generationPath && r.method === "POST").length, fixture.unregistered_first_response ? 2 : 1);
      assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
      await first.context.close();
      process.stdout.write(JSON.stringify({ wire_case: fixture.wire_case, generation_posts: fixture.unregistered_first_response ? 2 : 1,
        checkpoint_posts: requests.filter((r) => r.path === checkpointPath && r.method === "POST").length,
        generation_status_gets: requests.filter((r) => r.path === generationStatusPath).length,
        persisted_signature_reloaded: fixture.unregistered_first_response === true,
        status: response.status(), ui_metadata_retained_at_send: true, external_requests: 0, page_errors: 0 }));
      return;
    }
    assert.match(await first.page.locator('[data-saas-listing-draft-field="title"]').inputValue(), /[\u3400-\u9fff]/);
    const generatedResponse = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath
      && r.request().method() === "POST", { timeout: 15000 });
    const adoptionResponse = first.page.waitForResponse((r) => new URL(r.url()).pathname === checkpointPath
      && r.request().method() === "POST" && r.request().postDataJSON().base_report_id !== fixture.base_report.report_id,
    { timeout: 15000 });
    // Observe rejection immediately so a generation failure cannot leave an
    // unhandled adoption waiter while the sanitized harness error is reported.
    const generatedResult = generatedResponse.then((response) => ({ response }), () => ({ error: true }));
    const adoptedResult = adoptionResponse.then((response) => ({ response }), () => ({ error: true }));
    await first.page.getByRole("button", { name: "让 AI 重写买家文案", exact: true }).click();
    const generation = await generatedResult;
    assert.ok(generation.response, "native rewrite must reach Python generation");
    assert.equal(generation.response.status(), fixture.unregistered_first_response ? 400 : fixture.lose_generation_response ? 502 : 201);
    const generationRequest = generation.response.request().postDataJSON();
    let generated = await generation.response.json();
    if (fixture.unregistered_first_response) {
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
      const originalProof = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback.input_signature);
      if (fixture.legacy_request_signature) await first.page.evaluate(() => {
        // Simulate the previous client, preserving its real original input proof.
        delete state.saasListingComposerDraft.ai_generation_feedback.request_signature;
        saveSaasProtectedStateSnapshot();
      });
      const firstRead = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationStatusPath && r.request().method() === "GET");
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      const notFound = await (await firstRead).json();
      assert.equal(notFound.status, "not_found"); assert.equal(notFound.operation_id, generationRequest.operation_id);
      assert.equal(notFound.can_retry, false); assert.equal(notFound.report, null);
      assert.equal(requests.filter((r) => r.path === generationPath).length, 1, "checking does not automatically resubmit");
      assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), fixture.fields);
      assert.equal(await first.page.getByRole("button", { name: "继续本次生成", exact: true }).count(), 1);
      const resumedPost = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationPath && r.request().method() === "POST")
        .then((response) => ({ response }), () => ({ missing: true }));
      const resumedResult = first.page.waitForResponse(async (r) => new URL(r.url()).pathname === generationStatusPath
        && r.request().method() === "GET" && (await r.json()).status === "report_saved")
        .then((response) => ({ response }), () => ({ missing: true }));
      await first.page.getByRole("button", { name: "继续本次生成", exact: true }).click();
      const continued = await resumedPost;
      assert.ok(continued.response); assert.equal(continued.response.status(), 201);
      if (fixture.legacy_request_signature) assert.equal(await first.page.evaluate(() =>
        state.saasListingComposerDraft.ai_generation_feedback?.request_signature ?? null), null, "never manufacture an old request proof");
      assert.equal(await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback?.input_signature), originalProof);
      assert.deepEqual(continued.response.request().postDataJSON(), generationRequest, "continue uses the exact original wire request and operation");
      const result = await resumedResult; assert.ok(result.response);
      generated = await result.response.json();
      assert.equal(generated.operation_id, generationRequest.operation_id);
      assert.equal(requests.filter((r) => r.path === generationStatusPath).length, 3, "initial check, action-time check, then read the exact saved result");
    }
    if (fixture.lose_generation_response) {
      await first.page.waitForFunction(() => state.saasListingComposerDraft.ai_generation_feedback?.status === "generation_uncertain");
      const feedback = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback);
      assert.match(feedback.input_signature, /^[a-f0-9]{64}$/);
      assert.equal(feedback.operation.operation_id, generationRequest.operation_id);
      if (fixture.reload_before_check) {
        await first.page.reload();
        assert.equal(await first.page.evaluate(async ({ fixture, base }) => {
          window.__JIEJING_FORCE_PUBLIC_MVP__ = true; state.saasApiBase = base;
          const [me, storeResponse] = await Promise.all([saasFetch("/me"), saasFetch("/stores")]);
          state.saasIdentity = me.identity; state.saasUser = me.user; state.saasCompany = me.company;
          state.saasPermissions = me.permissions; state.saasStores = storeResponse.stores;
          // The real owned API verifies the session and store membership before
          // restoration. No draft, signature, or operation is manufactured here.
          const restored = hydrateSaasProtectedStateFromCache({ me, stores: storeResponse.stores, storeId: fixture.store_id });
          state.saasProtectedStateReady = true; state.saasProtectedStateFromCache = false; state.view = "product";
          bindEvents(); renderProductListingCenter();
          document.querySelector("#view-product").classList.add("is-active");
          return restored;
        }, { fixture: safeFixture, base }), true);
        await first.page.evaluate(() => hydrateSaasListingCloudCheckpoint({ force: true }));
        const reloaded = await first.page.evaluate(() => state.saasListingComposerDraft.ai_generation_feedback);
        assert.equal(reloaded.input_signature, feedback.input_signature, "reuse the exact persisted signature, never sign the reloaded draft");
        assert.deepEqual(reloaded.operation, feedback.operation);
        assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), fixture.fields);
        assert.equal(await first.page.evaluate(async () => state.saasListingComposerDraft.ai_generation_feedback.input_signature
          === await saasSha256Hex(saasListingAiGenerationEditSnapshot().draft)), true, "the unchanged restored draft must still match its original proof");
      }
      assert.equal(await first.page.getByRole("button", { name: "核对本次结果", exact: true }).count(), 1);
      const checkedResponse = first.page.waitForResponse((r) => new URL(r.url()).pathname === generationStatusPath
        && r.request().method() === "GET", { timeout: 15000 }).then((response) => ({ response }), () => ({ missing: true }));
      await first.page.getByRole("button", { name: "核对本次结果", exact: true }).click();
      const observedCheck = await checkedResponse;
      assert.ok(observedCheck.response, "the native result check reaches Python");
      const checked = observedCheck.response;
      assert.equal(checked.status(), 200); generated = await checked.json();
      assert.equal(generated.status, "report_saved"); assert.equal(generated.operation_id, generationRequest.operation_id);
    }
    const report = generated.report;
    const contract = report.report.listing_handoff.listing_fields.buyer_copy_rewrite;
    assert.equal(generationRequest.generation_mode, "rewrite_buyer_copy");
    assert.equal(generationRequest.expected_base_report_id, fixture.base_report.report_id);
    assert.deepEqual(generationRequest.merchant_product_fact_packet,
      Object.fromEntries(Object.entries(pagePacket).filter(([key]) => !["listing_copy", "saved_at"].includes(key))),
      "the wire packet drops only UI copy and timestamp metadata");
    assert.deepEqual(packetAtSend, pagePacket, "rewrite serialization does not mutate the page packet");
    assert.deepEqual(Object.fromEntries(fieldKeys.map((key) => [key, generationRequest.current_draft_fields[key]])), fixture.fields);
    assert.deepEqual(contract.previous_fields, fixture.fields);
    assert.deepEqual(contract.previous_merchant_edited_fields.sort(), [...fixture.merchant_edited_fields].sort());
    for (const key of fieldKeys) {
      if (copyKeys.includes(key)) { assert.notEqual(contract.fields[key], fixture.fields[key]); assert.ok(contract.fields[key].trim()); }
      else assert.equal(contract.fields[key], fixture.fields[key], `non-copy field ${key} is exact`);
    }
    const diagnostic = await first.page.evaluate(({ report, fields, generationRequest }) => {
      const draft = state.saasListingComposerDraft, cloud = saasListingCloudRecord();
      const rewrite = report.report.listing_handoff.listing_fields.buyer_copy_rewrite;
      const keys = saasListingMerchantEditableFieldKeys();
      const validFields = (values) => Object.keys(values).length === keys.length && keys.every((key) =>
        typeof values[key] === "string" && saasListingEditableFieldText(values[key], key) === values[key]);
      return {
        reader: !!saasListingBuyerCopyRewriteFromReport(report),
        context: saasListingCloudReportMatchesContext(report, saasListingCloudContext()),
        oldvalid: validFields(rewrite.previous_fields), newvalid: validFields(rewrite.fields),
        oldvisible: JSON.stringify(saasListingCloudFields(draft.fields)) === JSON.stringify(saasListingCloudFields(fields)),
        fixedrev: cloud?.revision === generationRequest.expected_checkpoint_revision,
        dirty: !!cloud?.dirty, pending: !!cloud?.pending, write: !!cloud?.write,
        conflict: cloud?.status === "conflict", failed: draft.ai_generation_feedback?.status === "failed",
        unknown: draft.ai_generation_feedback?.status === "generation_uncertain",
        unapplied: draft.ai_generation_feedback?.status === "generated_unapplied",
      };
    }, { report, fields: fixture.fields, generationRequest });
    diagnosticTag = Object.entries(diagnostic).map(([key, value]) => `${key}${value ? 1 : 0}`).join("_");
    const adoption = await adoptedResult;
    assert.ok(adoption.response, "new report must reach Python checkpoint CAS");
    assert.equal(adoption.response.status(), 201);
    const adoptionRequest = adoption.response.request().postDataJSON();
    const adopted = await adoption.response.json();
    assert.equal(adoptionRequest.expected_revision, generationRequest.expected_checkpoint_revision);
    assert.equal(adopted.checkpoint.revision, generationRequest.expected_checkpoint_revision + 1);
    assert.equal(adopted.checkpoint.base_report_id, report.report_id);
    assert.deepEqual(adopted.checkpoint.fields, contract.fields);
    assert.deepEqual(adopted.checkpoint.listing_project_identity, fixture.identity);
    await first.page.waitForFunction((title) => state.saasListingComposerDraft.fields.title === title, contract.fields.title);
    assert.deepEqual(await first.page.evaluate(() => state.saasListingComposerDraft.fields), contract.fields);
    await first.page.getByText("查看重写前文案", { exact: true }).click();
    for (const key of copyKeys) assert.ok((await first.page.locator("[data-saas-listing-copy-history]").textContent()).includes(fixture.fields[key]));
    await first.context.close();

    // No localStorage or earlier JS state crosses devices. The new report alone
    // defaults to old copy; only the real authenticated checkpoint adopts it.
    const second = await device(report, true);
    assert.deepEqual(await second.page.evaluate(() => state.saasListingComposerDraft.fields), contract.fields);
    assert.equal(await second.page.getByText("查看重写前文案", { exact: true }).count(), 1);
    await second.page.evaluate(() => renderProductListingCenter());
    await second.page.locator('[data-saas-action="focus-publish-intake"]').first().click();
    assert.equal(await second.page.locator('#saasPublishIntakeForm [name="title"]').inputValue(), contract.fields.title);
    assert.equal(await second.page.locator('#saasPublishIntakeForm [name="description_html"]').inputValue(), `${contract.fields.selling_points}\n\n${contract.fields.description}`);
    assert.equal(await second.page.locator('#saasPublishIntakeForm [name="price"]').inputValue(), "39.99");
    const generationPosts = requests.filter((r) => r.path === generationPath && r.method === "POST").length;
    const checkpointPosts = requests.filter((r) => r.path === checkpointPath && r.method === "POST").length;
    assert.equal(generationPosts, fixture.unregistered_first_response ? 2 : 1);
    assert.equal(checkpointPosts, 2, "one old-copy flush plus exactly one adoption");
    for (const request of requests.filter((r) => r.path === checkpointPath && r.method === "GET")) {
      assert.deepEqual(request.query, { source_report_id: fixture.identity.source_report_id, candidate_id: fixture.identity.candidate_id });
    }
    assert.deepEqual(forbidden, []); assert.deepEqual(errors, []);
    await second.context.close();
    process.stdout.write(JSON.stringify({ generation_posts: generationPosts, checkpoint_posts: checkpointPosts,
      restored_fields: fieldKeys.length, refreshed: true, history_visible: true, prefill_matches: true,
      generation_status_gets: requests.filter((r) => r.path === generationStatusPath).length,
      persisted_signature_reloaded: fixture.reload_before_check === true,
      legacy_request_signature_remains_absent: fixture.legacy_request_signature === true,
      external_requests: 0, page_errors: 0 }));
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  // Only the assertion's source location is emitted; never print fixture,
  // request payload, session cookie, provider text, or arbitrary error values.
  const frame = String(error?.stack || "").split("\n").find((line) => line.includes("test_jiejing_listing_buyer_copy_rewrite_http_smoke.js:")) || "";
  const line = frame.match(/http_smoke\.js:(\d+):/);
  process.stderr.write(`buyer_copy_rewrite_http_browser_smoke_failed${line ? `_line_${line[1]}` : ""}${diagnosticTag ? `_${diagnosticTag}` : ""}\n`);
  process.exitCode = 1;
});
