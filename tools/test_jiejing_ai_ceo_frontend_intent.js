#!/usr/bin/env node
/* Regression guard for merchant-facing AI CEO intent routing. */

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = source.indexOf(marker);
  assert.notStrictEqual(start, -1, `${name} must exist in app.js`);
  const bodyStart = source.indexOf("{", start);
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

const context = {};
vm.createContext(context);
vm.runInContext(
  `${extractFunction("isSaasCeoHighRiskCommand")}\n${extractFunction("saasCeoCommandIntent")}`,
  context,
);

const route = (message) => vm.runInContext(`saasCeoCommandIntent(${JSON.stringify(message)})`, context);

assert.strictEqual(
  route(
    "请做一份独立的 eBay 市场调研，比较三种香炉并只选一个可导入 Listing 的候选；本轮不写 eBay。",
  ),
  "research",
  "market research must not be stolen by a downstream Listing mention",
);
assert.strictEqual(
  route("帮我找一个 eBay 轻小品，并给市场调研报告和 Listing 字段建议。"),
  "research",
  "product selection with Listing field suggestions must stay in research",
);
assert.strictEqual(
  route("我有香炉货源链接，请根据这份商品资料生成 Listing 草稿。"),
  "listing",
  "an existing-source merchant asking for a Listing draft must enter Listing",
);
assert.strictEqual(
  route("继续 report_123，现在创建被事实阻断的内部 Listing 草稿。"),
  "listing",
  "an explicit report-to-internal-draft handoff must enter Listing",
);

console.log("PASS AI CEO frontend intent routing: 4/4");
