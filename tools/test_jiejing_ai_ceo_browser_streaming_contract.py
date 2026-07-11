#!/usr/bin/env python3
"""Guard the browser-visible AI CEO streaming transport and safe finalization."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    frontend = (ROOT / "app.js").read_text(encoding="utf-8")
    backend = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    model_client = (ROOT / "jiejing_runtime" / "model_clients.py").read_text(encoding="utf-8")

    frontend_markers = [
        "saasFetchNdjsonWithTimeout",
        "application/x-ndjson, application/json",
        "response.body.getReader()",
        "event.type === \"delta\"",
        "updateCeoAssistantStreamingMessage",
        "merchant-ceo/chat?stream=1",
        "streamRenderTimer = setTimeout(flushStreamRender, 48)",
    ]
    backend_markers = [
        "query = parse_qs(parsed.query)",
        "def _start_ndjson_stream",
        'self.send_header("x-accel-buffering", "no")',
        '"type": "delta"',
        '"type": "final"',
        "on_text_delta=emit_text_delta if stream_requested else None",
    ]
    model_markers = [
        "on_text_delta: Callable[[str], None] | None = None",
        "on_text_delta(content)",
    ]
    for marker in frontend_markers:
        assert marker in frontend, marker
    for marker in backend_markers:
        assert marker in backend, marker
    for marker in model_markers:
        assert marker in model_client, marker

    assert "frontend_gets_model_api_key" in backend
    assert '"secret_exposed": False' in backend
    print("PASS jiejing_ai_ceo_browser_streaming_contract")


if __name__ == "__main__":
    main()
