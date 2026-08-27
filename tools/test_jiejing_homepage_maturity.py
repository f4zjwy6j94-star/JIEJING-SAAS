#!/usr/bin/env python3
"""Contract checks for the public merchant homepage maturity pass."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def main() -> None:
    assert len(re.findall(r'data-home-section="[^"]+"', INDEX)) == 6
    assert INDEX.count('data-home-primary-cta="merchant_first_draft_v1"') == 1
    assert '>免费生成第一条草稿</button>' in INDEX
    assert re.search(r'id="heroWorkbenchLogin"[^>]*class="button-text"|class="button-text"[^>]*id="heroWorkbenchLogin"', INDEX)

    plans = re.findall(r'<button class="path-card[^"]*"[^>]*data-plan="(free|single|multi)"', INDEX)
    assert plans == ["free", "single", "multi"]

    assert 'data-home-draft-summary="merchant_first_draft_summary_v1"' in INDEX
    assert "已整理" in INDEX and "待补" in INDEX and "下一步" in INDEX
    assert 'id="signalCanvas"' not in INDEX
    assert 'class="flow-line"' not in INDEX
    assert 'class="role-node ' not in INDEX
    assert not re.search(r"\.reveal\s*\{[^}]*opacity:\s*0\s*;", INDEX, re.S)

    for retired_id in (
        "retired-public-home-sections",
        "merchant-guide",
        "ai-ceo-workbench-technical",
        "ai-ceo-workbench",
    ):
        assert f'id="{retired_id}"' not in INDEX

    for forbidden in ("Packing Cubes", "Hermes", "开发完成度", "项目完成度"):
        assert forbidden not in INDEX

    print("PASS jiejing_homepage_maturity")


if __name__ == "__main__":
    main()
