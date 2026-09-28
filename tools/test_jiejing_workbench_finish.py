#!/usr/bin/env python3
"""Keep the approved visual finish separate from merchant state and workflows."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app.html").read_text(encoding="utf-8")
CSS = (ROOT / "assets" / "jiejing-workbench-finish.css").read_text(encoding="utf-8")


class AppDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str | None]] = {}
        self.links: list[str] = []
        self.nav: list[tuple[str, str]] = []
        self._nav = False
        self._button: str | None = None
        self._label: list[str] = []
        self._icon = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids[attributes["id"]] = attributes
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.links.append(attributes.get("href", ""))
        if tag == "nav" and attributes.get("id") == "navList":
            self._nav = True
        if self._nav and tag == "button":
            self._button = attributes.get("data-view")
            self._label = []
        if self._button and tag == "span":
            self._icon = "nav-icon" in attributes.get("class", "").split()

    def handle_data(self, data: str) -> None:
        if self._button and not self._icon:
            self._label.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if self._nav and tag == "span":
            self._icon = False
        if self._nav and tag == "button" and self._button:
            self.nav.append((self._button, "".join(self._label)))
            self._button = None
        if tag == "nav":
            self._nav = False


def rules(source: str):
    """Read declaration blocks and recurse through media queries without dependencies."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    offset = 0
    while offset < len(source):
        opening = source.find("{", offset)
        if opening == -1:
            if source[offset:].strip():
                raise AssertionError("unexpected CSS tail")
            break
        selector = source[offset:opening].strip()
        level, closing = 1, opening + 1
        while closing < len(source) and level:
            level += (source[closing] == "{") - (source[closing] == "}")
            closing += 1
        if level:
            raise AssertionError("unbalanced CSS declaration block")
        body = source[opening + 1 : closing - 1]
        if selector.startswith("@media"):
            yield from rules(body)
        else:
            yield selector, body
        offset = closing


def contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))

    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + .05) / (values[0] + .05)


class WorkbenchFinishContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = AppDocument()
        cls.document.feed(HTML)

    def test_six_navigation_routes_keep_approved_names(self) -> None:
        self.assertEqual(self.document.nav, [
            ("cockpit", "JV AI"), ("product", "选品与上架"),
            ("media", "素材工坊"), ("confirm", "确认中心"),
            ("service", "客服与订单"), ("connect", "设置"),
        ])

    def test_finish_loads_after_existing_geometry_and_keeps_auth_hidden(self) -> None:
        self.assertRegex(self.document.links[-1], r"jiejing-workbench-finish\.css\?v=\d{8}-.+")
        head = HTML[:HTML.index("</head>")]
        self.assertGreater(head.index("jiejing-workbench-finish.css"), head.rindex("</style>"))
        self.assertIn("is-hidden", self.document.ids["appShell"]["class"].split())
        self.assertIn("hidden", self.document.ids["appBootLoading"])
        self.assertIn("hidden", self.document.ids["accountMenuPopover"])

    def test_rename_does_not_change_runtime_identifiers_or_preserved_views(self) -> None:
        self.assertEqual(self.document.ids["ceoInput"]["name"], "ai_ceo_prompt")
        self.assertEqual(self.document.ids["view-cockpit"]["data-title"], "JV AI")
        self.assertIn("ceoForm", self.document.ids)
        self.assertIn("view-bulk", self.document.ids)
        self.assertIn("view-connect", self.document.ids)
        self.assertIn("hidden", self.document.ids["view-activity"])
        self.assertEqual(self.document.ids["view-activity"]["data-internal-view"], "legacy-report-center")
        self.assertNotIn("AI CEO", HTML)

    def test_finish_cannot_override_visibility_or_layout_state(self) -> None:
        forbidden = {
            "display", "visibility", "position", "z-index", "pointer-events",
            "overflow", "overflow-x", "overflow-y", "height", "max-height",
            "grid-template-columns", "grid-template-rows", "flex", "order",
        }
        self.assertNotIn("!important", CSS)
        for selector, declarations in rules(CSS):
            with self.subTest(selector=selector):
                if selector == "@font-face":
                    continue
                self.assertTrue(selector.startswith("body.saas-public-mvp"))
                self.assertNotIn(".public-home", selector)
                for property_name in re.findall(r"(?:^|;)\s*([\w-]+)\s*:", declarations):
                    self.assertNotIn(property_name, forbidden)

    def test_font_is_local_and_color_roles_are_readable(self) -> None:
        self.assertNotRegex(CSS, r"(?:url\(|@import).*https?:")
        self.assertIn('"PingFang SC", "Microsoft YaHei"', CSS)
        self.assertIn("font-display: swap", CSS)
        tokens = dict(re.findall(r"(--jiejing-[\w-]+):\s*(#[0-9a-fA-F]{6});", CSS))
        for foreground in ("--jiejing-ink", "--jiejing-muted", "--jiejing-accent"):
            for background in ("--jiejing-shell-canvas", "--jiejing-surface", "--jiejing-surface-accent"):
                self.assertGreaterEqual(contrast(tokens[foreground], tokens[background]), 4.5, (foreground, background))
        self.assertGreaterEqual(contrast("#ffffff", tokens["--jiejing-accent"]), 4.5)
        self.assertIn("@media (max-width: 700px)", CSS)
        self.assertIn("font-size: 16px", CSS)
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
