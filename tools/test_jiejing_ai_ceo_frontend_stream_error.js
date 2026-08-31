#!/usr/bin/env node
/* Regression guard for immediate AI CEO stream blockers. */

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");

function extractAsyncFunction(name) {
  const marker = `async function ${name}(`;
  const start = source.indexOf(marker);
  assert.notStrictEqual(start, -1, `${name} must exist in app.js`);
  const signatureEnd = source.indexOf(") {", start);
  assert.notStrictEqual(signatureEnd, -1, `${name} signature must terminate`);
  const bodyStart = signatureEnd + 2;
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote) {
      if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated ${name} function`);
}

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = source.indexOf(marker);
  assert.notStrictEqual(start, -1, `${name} must exist in app.js`);
  const signatureEnd = source.indexOf(") {", start);
  assert.notStrictEqual(signatureEnd, -1, `${name} signature must terminate`);
  const bodyStart = signatureEnd + 2;
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote) {
      if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated ${name} function`);
}

const blockedPayload = {
  ai_ceo_chat: {
    status: "blocked",
    answer: "免费体验的 20 次平台 AI 调用已用完。",
    blocked_by: ["platform_default_model_trial_exhausted"],
  },
  usage_consumed: false,
  listing_created: false,
};

let protectedSessionChecks = 0;
let fetchCalls = 0;
const context = {
  AbortController,
  Error,
  JSON,
  TextDecoder,
  Uint8Array,
  clearTimeout,
  console,
  ensureSaasProtectedSessionForMutation: async () => {
    protectedSessionChecks += 1;
    return { user: { user_id: "user-test" } };
  },
  fetch: async () => {
    fetchCalls += 1;
    return {
      ok: false,
      status: 402,
      text: async () => JSON.stringify(blockedPayload),
      headers: { get: () => "application/json" },
    };
  },
  recordOptionalSaasSoftTimeout: () => {},
  publicRuntimeText: (value) => String(value || ""),
  saasModelBlockedReasonText: (value) => String(value || ""),
  saasBackendErrorMessage: () => "quota blocked",
  setTimeout,
  shouldAttachSaasBearerToken: () => false,
  state: { saasApiBase: "https://app.jiejing.shop", saasToken: "" },
};

vm.createContext(context);
vm.runInContext(extractAsyncFunction("saasFetchNdjsonWithTimeout"), context);
vm.runInContext(extractFunction("saasBackendErrorMessage"), context);
vm.runInContext(extractFunction("saasAiCeoMerchantSafeFailureText"), context);

(async () => {
  const result = await vm.runInContext(
    'saasFetchNdjsonWithTimeout("/stores/test/merchant-ceo/chat?stream=1", { method: "POST" })',
    context,
  );
  assert.strictEqual(result._http_status, 402, "logical HTTP status must be preserved");
  assert.strictEqual(result.usage_consumed, false, "quota blocker must preserve no-usage evidence");
  assert.strictEqual(
    result.ai_ceo_chat.blocked_by[0],
    "platform_default_model_trial_exhausted",
    "the exact backend blocker must reach the chat state handler",
  );
  assert.strictEqual(protectedSessionChecks, 1, "mutation preflight must run exactly once");
  assert.strictEqual(fetchCalls, 1, "AI mutation request must be sent exactly once");
  const permissionFailureText = await vm.runInContext(
    `saasAiCeoMerchantSafeFailureText(new Error(saasBackendErrorMessage(403, "", { error: "missing permission: create_task" })))`,
    context,
  );
  assert.match(
    permissionFailureText,
    /创建任务权限|联系管理员/,
    "ordinary create_task denial must tell the merchant that the account lacks task creation permission or to contact an administrator",
  );
  assert.doesNotMatch(
    permissionFailureText,
    /AI|模型|连接/,
    "ordinary create_task denial must not be misclassified as an AI connection or model-name problem",
  );
  const providerPermissionFailureText = await vm.runInContext(
    `saasAiCeoMerchantSafeFailureText(new Error(saasBackendErrorMessage(403, "", { error: "missing permission to access model" })))`,
    context,
  );
  assert.doesNotMatch(
    providerPermissionFailureText,
    /没有创建任务权限|团队负责人|调整角色/,
    "a provider permission failure must not be misclassified as a Jiejing task-role denial",
  );
  console.log("PASS AI CEO frontend immediate stream blocker: 8/8");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
