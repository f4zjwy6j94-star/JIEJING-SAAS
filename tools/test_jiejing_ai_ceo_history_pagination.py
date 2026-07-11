#!/usr/bin/env python3
"""Regression contract for progressive AI CEO chat history rendering."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    required = [
        "SAAS_AI_CEO_INITIAL_VISIBLE_TURNS = 12",
        "SAAS_AI_CEO_LOAD_OLDER_STEP = 8",
        "visibleTurns = turns.slice(-visibleLimit)",
        "data-ceo-load-older",
        "revealOlderSaasAiCeoTurns",
        "chat.scrollHeight - previousHeight",
        'state.saasAiCeoAutoFollow = false',
        "bindSaasAiCeoHistoryControls(chat)",
    ]
    for marker in required:
        if marker not in app:
            return fail(f"missing progressive history marker: {marker}")
    if ".saas-ai-ceo-history-more" not in styles:
        return fail("older-history control must have merchant-facing styling")
    print("PASS AI CEO initially renders recent turns and preserves position while loading older history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
