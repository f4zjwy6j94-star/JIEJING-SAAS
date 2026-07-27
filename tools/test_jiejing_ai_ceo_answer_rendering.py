#!/usr/bin/env python3
"""Regression for merchant-facing AI CEO answer headings."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    marker = "function saasAiCeoHeadingIsMeaningful"
    assert marker in app_js, "missing orphan heading guard"
    start = app_js.index(marker)
    end = app_js.index("\nfunction renderSaasAiCeoAnswerMarkup", start)
    helper = app_js[start:end]

    script = f"""
const publicRuntimeText = (value = "") => String(value || "");
{helper}
for (const value of ["一", "二、", "1", "1.", "###"]) {{
  if (saasAiCeoHeadingIsMeaningful(value)) throw new Error(`orphan heading leaked: ${{value}}`);
}}
for (const value of ["市场机会", "一、市场机会", "Listing 草稿建议"]) {{
  if (!saasAiCeoHeadingIsMeaningful(value)) throw new Error(`meaningful heading hidden: ${{value}}`);
}}
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    render_start = app_js.index("function renderSaasAiCeoAnswerMarkup")
    render_end = app_js.index("\nfunction renderSaasAiCeoChatTurnMarkup", render_start)
    render_body = app_js[render_start:render_end]
    assert "saasAiCeoHeadingIsMeaningful(heading[1])" in render_body, render_body

    print("PASS jiejing_ai_ceo_answer_rendering")


if __name__ == "__main__":
    main()
