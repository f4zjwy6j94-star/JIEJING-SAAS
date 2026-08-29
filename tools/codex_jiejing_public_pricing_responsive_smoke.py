from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


VIEWPORTS = (
    ("desktop", 1266, 720),
    ("tablet", 820, 1180),
    ("mobile", 390, 844),
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Verify public pricing cards remain readable across merchant viewports."
    )
    parser.add_argument("--url", default="https://app.jiejing.shop/#plans")
    parser.add_argument(
        "--output-dir",
        default="output/jiejing-public-pricing-smoke",
    )
    args = parser.parse_args()
    local_static_target = args.url.startswith(("http://127.0.0.1:", "http://localhost:"))

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for key, width, height in VIEWPORTS:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                user_agent="Mozilla/5.0 Codex Jiejing Pricing Smoke",
            )
            page = context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type in {"error", "warning"}
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            plans = page.locator("#plans")
            plans.wait_for(state="visible", timeout=10000)
            page.evaluate(
                "window.scrollTo({top: document.querySelector('#plans').offsetTop - 72, behavior: 'instant'})"
            )
            page.wait_for_timeout(300)

            if local_static_target:
                console_errors = [
                    error
                    for error in console_errors
                    if "Unsupported method ('POST')" not in error
                    and "status of 501" not in error
                ]

            prices = page.locator("#plans .path-card .price").evaluate_all(
                """
                (elements) => elements.map((element) => {
                  const range = document.createRange();
                  range.selectNodeContents(element);
                  const textRects = [...range.getClientRects()]
                    .filter((rect) => rect.width > 0 && rect.height > 0)
                  const lineTops = textRects.map((rect) => Math.round(rect.top));
                  const textWidth = textRects.reduce((width, rect) => Math.max(width, rect.width), 0);
                  const parentStyle = getComputedStyle(element.parentElement);
                  const parentWidth = element.parentElement.getBoundingClientRect().width
                    - parseFloat(parentStyle.paddingLeft || 0)
                    - parseFloat(parentStyle.paddingRight || 0);
                  return {
                    text: element.textContent.trim(),
                    lineCount: new Set(lineTops).size,
                    textWidth: Math.round(textWidth * 100) / 100,
                    availableWidth: Math.round(parentWidth * 100) / 100,
                    fits: textWidth <= parentWidth + 1,
                  };
                })
                """
            )
            home_sections = page.locator("[data-home-section]").evaluate_all(
                "(elements) => elements.map((element) => element.dataset.homeSection)"
            )
            primary_cta_count = page.locator(
                '[data-home-primary-cta="jiejing_ai_ceo_workspace_v2"]'
            ).count()
            horizontal_overflow = page.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth + 1"
            )
            visible_legacy_sections = page.locator(
                "#merchant-guide:visible, #ai-ceo-workbench-technical:visible, #ai-ceo-workbench:visible"
            ).count()
            screenshot = output_dir / f"pricing-{key}-{width}x{height}.png"
            plans.screenshot(path=str(screenshot))
            result = {
                "viewport": key,
                "width": width,
                "height": height,
                "url": page.url,
                "prices": prices,
                "home_sections": home_sections,
                "primary_cta_count": primary_cta_count,
                "horizontal_overflow": horizontal_overflow,
                "visible_legacy_sections": visible_legacy_sections,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "screenshot": str(screenshot),
            }
            results.append(result)

            if len(prices) != 3:
                failures.append(f"{key}: expected 3 prices, found {len(prices)}")
            if home_sections != ["hero", "proof", "capabilities", "workflow", "merchants", "plans"]:
                failures.append(f"{key}: unexpected homepage sections: {home_sections}")
            if primary_cta_count != 1:
                failures.append(f"{key}: expected one primary CTA, found {primary_cta_count}")
            if horizontal_overflow:
                failures.append(f"{key}: homepage has horizontal overflow")
            if visible_legacy_sections:
                failures.append(f"{key}: legacy homepage sections remain visible")
            for price in prices:
                if price["lineCount"] != 1 or not price["fits"]:
                    failures.append(f"{key}: price does not fit one line: {price}")
            if console_errors or page_errors:
                failures.append(
                    f"{key}: browser errors console={console_errors} page={page_errors}"
                )
            context.close()
        browser.close()

    packet = {
        "status": "pass" if not failures else "fail",
        "url": args.url,
        "viewports": results,
        "failures": failures,
    }
    output_path = output_dir / "latest.json"
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output_path}")
    if failures:
        return 1
    print("PASS jiejing_public_pricing_responsive_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
