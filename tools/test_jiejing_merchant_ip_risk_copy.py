from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "app.html").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")
APPROVED_COPY = "侵权风险初筛，仍需商家核对"


def function_body(name: str, next_name: str) -> str:
    start = APP_JS.index(f"function {name}")
    end = APP_JS.index(f"function {next_name}", start)
    return APP_JS[start:end]


def main() -> int:
    merchant_sources = APP_JS + "\n" + APP_HTML + "\n" + INDEX_HTML
    forbidden_patterns = [
        r"侵权检测通过",
        r"IP\s*初筛通过",
        r"VeRO\s*初筛通过",
        r"知识产权(?:检测|审核|初筛)通过",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, merchant_sources, flags=re.IGNORECASE), f"merchant UI must not overpromise with: {pattern}"

    risk_surfaces = [
        function_body("renderSaasListingStoreSyncOverview", "renderSaasListingSyncedProductsPanel"),
        function_body("renderSaasListingIpReadinessPanel", "parseSaasKeyValueLines"),
        function_body("renderSaasMerchantIpRiskPanel", "saasIpRiskStatusLabel"),
    ]
    for surface in risk_surfaces:
        assert APPROVED_COPY in surface, "every merchant IP/VeRO result surface must state the approved review boundary"

    status_labels = function_body("saasIpRiskStatusLabel", "renderSaasMerchantDataCoveragePanel")
    assert 'ready_no_hits: "侵权风险初筛，仍需商家核对"' in status_labels, "a no-hit scan must remain an initial screen, not a passing result"
    assert APPROVED_COPY in APP_HTML and APPROVED_COPY in INDEX_HTML, "the app entry and public homepage must use the same risk boundary"

    print("PASS: merchant IP risk copy stays an initial screen that still requires merchant review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
