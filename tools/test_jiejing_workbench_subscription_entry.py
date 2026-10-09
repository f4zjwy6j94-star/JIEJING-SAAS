from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def main() -> int:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    nav_start = app_html.index('<nav class="nav-list" id="navList"')
    nav_end = app_html.index("</nav>", nav_start)
    nav_html = app_html[nav_start:nav_end]
    if 'data-global-flow-key="billing"' in nav_html:
        return fail("subscription entry must not become an eighth workflow module")
    if 'class="sidebar-subscription-entry"' not in app_html:
        return fail("desktop workbench subscription entry is missing")
    if 'class="subscription-entry-compact-label"' not in app_html:
        return fail("tablet subscription entry needs a compact merchant label")
    if 'data-account-action="subscription"' not in app_js:
        return fail("account menu subscription entry is missing for tablet/mobile")
    if 'if (key === "billing") state.saasSettingsTab = "billing";' not in app_js:
        return fail("workflow subscription entry does not target the billing settings tab")
    if 'if (action === "subscription")' not in app_js:
        return fail("account menu subscription action is not implemented")
    if ".sidebar-subscription-entry" not in styles:
        return fail("subscription entry styling is missing")
    if "grid-template-columns: minmax(0, 1fr) 72px !important" not in styles:
        return fail("tablet bottom navigation must reserve an independent subscription utility slot")
    if "grid-template-columns: minmax(0, 1fr) 48px !important" not in styles:
        return fail("mobile module navigation must keep a fixed subscription utility slot")
    if "grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))" not in styles:
        return fail("media credit packs must adapt to the settings content width")
    if "word-break: keep-all" not in styles or "white-space: nowrap" not in styles:
        return fail("media credit pack labels and purchase actions must not break vertically")
    analytics_script = './assets/jiejing-first-party-analytics.js?v=20261009-ops-measurement-v105'
    if (f'src="{analytics_script}"' not in app_html
            or f'src="{analytics_script}"' not in (ROOT / "index.html").read_text(encoding="utf-8")):
        return fail("landing and workbench analytics must both reference the reviewed cache version")

    print("PASS: workbench subscription entry is visible, responsive, and reuses billing settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
