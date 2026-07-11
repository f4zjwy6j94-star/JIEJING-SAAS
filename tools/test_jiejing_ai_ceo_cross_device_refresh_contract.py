"""Frontend contract for foreground and polling-based account chat refresh."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    repository = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")
    checks = {
        "account revision": "ai_ceo_chat_history_revision",
        "stale merge marker": "conflict_merged",
        "frontend base revision": "base_revision: state.saasAiCeoHistoryRevision",
        "foreground refresh": 'document.addEventListener("visibilitychange"',
        "window focus refresh": 'window.addEventListener("focus"',
        "active polling": "saasAiCeoCrossDeviceSyncTimer",
        "same-browser tab signal": "BroadcastChannel",
        "server richer-turn merge": "_ai_ceo_chat_turn_merge_score",
    }
    corpus = "\n".join((app, api, repository))
    missing = [label for label, marker in checks.items() if marker not in corpus]
    if missing:
        print(f"FAIL AI CEO cross-device refresh contract missing: {missing}")
        return 1
    print("PASS jiejing_ai_ceo_cross_device_refresh_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
