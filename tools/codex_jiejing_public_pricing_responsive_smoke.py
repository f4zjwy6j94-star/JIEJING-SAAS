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
    parser.add_argument("--url", default="https://app.jiejing.shop/#pricing")
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
            pricing = page.locator("#pricing")
            pricing.wait_for(state="visible", timeout=10000)
            pricing.scroll_into_view_if_needed()
            page.wait_for_timeout(300)

            if local_static_target:
                console_errors = [
                    error
                    for error in console_errors
                    if "Unsupported method ('POST')" not in error
                    and "status of 501" not in error
                ]

            prices = page.locator(".price").evaluate_all(
                """
                (elements) => elements.map((element) => {
                  const range = document.createRange();
                  range.selectNodeContents(element);
                  const lineTops = [...range.getClientRects()]
                    .filter((rect) => rect.width > 0 && rect.height > 0)
                    .map((rect) => Math.round(rect.top));
                  return {
                    text: element.textContent.trim(),
                    lineCount: new Set(lineTops).size,
                    clientWidth: element.clientWidth,
                    scrollWidth: element.scrollWidth,
                    fits: element.scrollWidth <= element.clientWidth + 1,
                  };
                })
                """
            )
            screenshot = output_dir / f"pricing-{key}-{width}x{height}.png"
            pricing.screenshot(path=str(screenshot))
            result = {
                "viewport": key,
                "width": width,
                "height": height,
                "url": page.url,
                "prices": prices,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "screenshot": str(screenshot),
            }
            results.append(result)

            if len(prices) != 4:
                failures.append(f"{key}: expected 4 prices, found {len(prices)}")
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
