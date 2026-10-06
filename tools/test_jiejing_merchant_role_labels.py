from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


class MerchantTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.accessible_labels: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"aria-label", "aria-description", "title", "alt"} and value:
                self.accessible_labels.append(value)

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized:
            self.text.append(normalized)


def run_role_ui_contract() -> dict[str, object]:
    node_script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[2], "utf8");
const state = {
  saasRoles: [
    { role: "owner", label: "Owner" },
    { role: "admin", label: "Admin" },
    { role: "operator", label: "Operator" },
    { role: "media", label: "Media" },
    { role: "support", label: "Support" },
    { role: "finance", label: "Finance" },
    { role: "viewer", label: "Viewer" },
  ],
  saasTeamMember: { role: "platform_internal_admin" },
  saasPermissions: ["manage_store", "view_report", "approve_high_risk"],
};
const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function between(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`missing source markers: ${startMarker} -> ${endMarker}`);
  return source.slice(start, end);
}

eval(between("function saasPermissionLabel", "function saasMerchantWorkflowTemplateRoles"));
eval(between("function renderSaasMerchantPermissionPanel", "function renderSaasMerchantProviderHubPanel"));

const codes = ["owner", "admin", "operator", "media", "support", "finance", "viewer"];
process.stdout.write(JSON.stringify({
  labels: codes.map((code) => saasMerchantRoleLabel(code)),
  rows: saasMerchantRoleRows().map(({ role, label }) => ({ role, label })),
  panel: renderSaasMerchantPermissionPanel(),
}));
"""
    completed = subprocess.run(
        ["node", "-", str(APP_JS)],
        input=node_script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip() or "role UI contract could not run")
    return json.loads(completed.stdout)


def main() -> int:
    result = run_role_ui_contract()
    expected_labels = ["负责人", "管理员", "运营", "素材", "客服", "财务", "只读"]
    assert result["labels"] == expected_labels, "merchant role codes must map to the approved Chinese business labels"
    assert [row["label"] for row in result["rows"]] == expected_labels, "backend role labels must not override merchant-facing labels"

    panel = str(result["panel"])
    assert 'data-role-code="platform_internal_admin"' in panel, "the backend role code must remain available for scoped form/actions"
    parser = MerchantTextParser()
    parser.feed(panel)
    merchant_copy = html.unescape(" ".join(parser.text + parser.accessible_labels))
    assert "当前角色：管理员" in merchant_copy, "an internal platform admin must render as the merchant-safe administrator role"
    for internal_label in ["Owner", "Admin", "platform_internal_admin"]:
        assert internal_label not in merchant_copy, f"merchant-visible text or ARIA must not expose {internal_label}"

    print("PASS: merchant team roles keep backend codes while rendering merchant-safe Chinese labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
