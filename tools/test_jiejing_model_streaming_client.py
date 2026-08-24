#!/usr/bin/env python3
"""Verify safe SSE parsing for the official DeepSeek-compatible text client."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.model_clients import OpenAICompatibleModelClient  # noqa: E402


class FakeStreamingResponse:
    def __init__(self) -> None:
        self.lines = [
            'data: {"choices":[{"delta":{"content":"候选商品"},"finish_reason":null}]}\n'.encode("utf-8"),
            b'data: {"choices":[{"delta":{"reasoning_content":"internal"},"finish_reason":null}]}\n',
            'data: {"choices":[{"delta":{"content":"卡片"},"finish_reason":"stop"}]}\n'.encode("utf-8"),
            b'data: {"choices":[],"usage":{"prompt_tokens":120,"completion_tokens":30,"total_tokens":150}}\n',
            b'data: [DONE]\n',
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.lines)


def main() -> None:
    captured: dict[str, object] = {}
    deltas: list[str] = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeStreamingResponse()

    client = OpenAICompatibleModelClient(
        endpoint="https://api.deepseek.com/chat/completions",
        api_key="unit-test-model-key",
        model="deepseek-v4-flash",
        timeout_seconds=30,
    )
    with patch("jiejing_runtime.model_clients.urllib.request.urlopen", fake_urlopen):
        result = client.generate_text(
            system_prompt="Return merchant-facing Chinese.",
            user_prompt="Generate candidate cards.",
            max_output_tokens=800,
            timeout_seconds=20,
            on_text_delta=deltas.append,
        )

    assert captured["payload"]["stream"] is True, captured
    assert captured["payload"]["stream_options"] == {"include_usage": True}, captured
    assert captured["payload"]["thinking"] == {"type": "disabled"}, captured
    assert result["text"] == "候选商品卡片", result
    assert result["finish_reason"] == "stop", result
    assert result["model_mode"] == "live_http_model_text_stream", result
    assert result["_usage"] == {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}, result
    assert deltas == ["候选商品", "卡片"], deltas
    assert "internal" not in json.dumps(result, ensure_ascii=False), result
    assert "unit-test-model-key" not in json.dumps(result, ensure_ascii=False), result
    print("PASS jiejing_model_streaming_client")


if __name__ == "__main__":
    main()
