#!/usr/bin/env python3
"""Regression contract for AI CEO chat scroll retention."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def function_body(source: str, name: str, next_name: str) -> str:
    start_marker = f"function {name}("
    end_marker = f"function {next_name}("
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        return ""
    return source[start:end]


def main() -> int:
    source = (ROOT / "app.js").read_text(encoding="utf-8")

    required_markers = [
        "SAAS_AI_CEO_BOTTOM_FOLLOW_THRESHOLD",
        "isSaasAiCeoChatNearBottom",
        "bindSaasAiCeoScrollIntent",
        "captureSaasAiCeoScrollState",
        "restoreSaasAiCeoScrollState",
        "state.saasAiCeoAutoFollow = false",
    ]
    for marker in required_markers:
        if marker not in source:
            return fail(f"missing scroll retention marker: {marker}")

    merge_body = function_body(source, "mergeSaasAiCeoHistoryFromBackend", "syncSaasAiCeoCloudDomState")
    if "captureSaasAiCeoScrollState(chat)" not in merge_body or "restoreSaasAiCeoScrollState(chat, scrollSnapshot)" not in merge_body:
        return fail("cross-device history refresh must preserve the merchant's scroll position")

    streaming_body = function_body(source, "updateCeoAssistantStreamingMessage", "updateCeoAssistantMessage")
    if "captureSaasAiCeoScrollState(chat)" not in streaming_body or "restoreSaasAiCeoScrollState(chat, scrollSnapshot)" not in streaming_body:
        return fail("streaming answer updates must preserve scroll position")

    final_body = function_body(source, "updateCeoAssistantMessage", "updateCeoAssistantPendingMessage")
    if "captureSaasAiCeoScrollState(chat)" not in final_body or "restoreSaasAiCeoScrollState(chat, scrollSnapshot)" not in final_body:
        return fail("final answer updates must preserve scroll position")

    pending_body = function_body(source, "updateCeoAssistantPendingMessage", "isMediaGenerationRequest")
    if "captureSaasAiCeoScrollState(chat)" not in pending_body or "restoreSaasAiCeoScrollState(chat, scrollSnapshot)" not in pending_body:
        return fail("pending-state updates must preserve scroll position")

    send_body = function_body(source, "addCeoMessage", "syncSaasAiCeoFixedChatViewportState")
    if "forceBottom: true" not in send_body:
        return fail("sending a new message should deliberately resume bottom following")

    print("PASS AI CEO keeps history position while the merchant reads older messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
