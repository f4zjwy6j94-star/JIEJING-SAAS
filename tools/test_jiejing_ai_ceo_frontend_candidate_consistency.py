#!/usr/bin/env python3
"""Regression for explicit AI CEO recommendation -> Listing product consistency."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    marker = "function saasExplicitRecommendedMarketProductLabelFromText"
    assert marker in app_js, "frontend must parse an explicit final recommendation before stale report metadata"

    start = app_js.index(marker)
    end = app_js.index("\nfunction saasAiCeoMarketProductLabel", start)
    function_source = app_js[start:end]
    answer = """
### 候选商品卡
候选商品 1：冰箱食品收纳整理架（Fridge Organizer Bin with Dividers）
候选商品 2：多功能抽屉分隔板（Adjustable Drawer Dividers）

### 选品确认与推荐
### ✅ 最值得测试：**多功能抽屉分隔板（Adjustable Drawer Dividers）**
""".strip()
    expected = "多功能抽屉分隔板（Adjustable Drawer Dividers）"
    node_script = f"""
const publicRuntimeText = (value = "") => String(value || "");
const saasCleanMarketCandidateName = (value = "") => String(value || "")
  .replace(/\\*\\*/g, "")
  .trim()
  .replace(/^[#>*\\-\\d.)、\\s]+/, "")
  .trim()
  .replace(/^[-:：]+|[-:：]+$/g, "")
  .trim();
const saasIsConcreteProductLabel = (value = "") => Boolean(String(value || "").trim());
{function_source}
const result = saasExplicitRecommendedMarketProductLabelFromText({json.dumps(answer, ensure_ascii=False)});
if (result !== {json.dumps(expected, ensure_ascii=False)}) {{
  throw new Error(`wrong selected product: ${{result}}`);
}}
if (saasExplicitRecommendedMarketProductLabelFromText("候选商品 1：普通商品") !== "") {{
  throw new Error("non-explicit candidate must not be treated as the final recommendation");
}}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    product_label_start = app_js.index("function saasAiCeoMarketProductLabel")
    product_label_end = app_js.index("\nfunction saasAiCeoConciseAnswerProductLabel", product_label_start)
    product_label_body = app_js[product_label_start:product_label_end]
    explicit_index = product_label_body.index("saasExplicitRecommendedMarketProductLabelFromText")
    candidate_index = product_label_body.index("saasSelectedMarketProductCandidate")
    assert explicit_index < candidate_index, "explicit final recommendation must outrank candidate/report fallbacks"

    candidate_start = app_js.index("function saasMarketCandidateMatchKey")
    candidate_end = app_js.index("\nfunction saasListingDescriptionFromCandidate", candidate_start)
    candidate_source = app_js[candidate_start:candidate_end]
    candidate_script = f"""
const publicRuntimeText = (value = "") => String(value || "");
const saasIsInvalidMarketProductLabel = () => false;
const saasCleanMarketCandidateName = (value = "") => String(value || "")
  .replace(/\\*\\*/g, "")
  .trim()
  .replace(/^[#>*\\-\\d.)、\\s]+/, "")
  .trim()
  .replace(/^[-:：]+|[-:：]+$/g, "")
  .trim();
{candidate_source}
const rawCandidates = [
  {{ candidate_id: "candidate_1", name: "冰箱食品收纳整理架", reasons: ["冰箱事实"], selected: false }},
  {{ candidate_id: "candidate_2", name: "多功能抽屉分隔板", reasons: ["抽屉事实"], selected: true }},
];
const firstPass = saasNormalizeMarketProductCandidates(rawCandidates, "最终推荐：多功能抽屉分隔板");
const selected = saasSelectedMarketProductCandidate(firstPass);
if (selected?.candidate_id !== "candidate_2") {{
  throw new Error(`selected candidate regressed to ${{selected?.candidate_id || "none"}}`);
}}
if (selected?.reasons?.[0] !== "抽屉事实") {{
  throw new Error(`selected facts came from the wrong candidate: ${{selected?.reasons?.[0] || "none"}}`);
}}
"""
    completed = subprocess.run(
        ["node", "-e", candidate_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    print("PASS jiejing_ai_ceo_frontend_candidate_consistency")


if __name__ == "__main__":
    main()
