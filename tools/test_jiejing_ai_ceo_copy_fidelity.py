#!/usr/bin/env python3
"""Guard AI CEO conversation text from presentation-time copy rewriting."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.js").read_text(encoding="utf-8")


def scope(start_marker: str, end_marker: str) -> str:
    start = APP.index(start_marker)
    end = APP.index(end_marker, start + len(start_marker))
    return APP[start:end]


def main() -> None:
    assert "function merchantConversationText" in APP

    normalization = scope("function normalizeSaasAiCeoLatestTurn", "function normalizeSaasAiCeoSourceRecords")
    assert "merchantConversationText(" in normalization
    assert "productizeJiejingProductCopy(" not in normalization

    answer = scope("function renderSaasAiCeoAnswerMarkup", "function renderSaasAiCeoChatTurnMarkup")
    assert "merchantConversationText(" in answer
    assert "productizeJiejingProductCopy(" not in answer

    productized_answer = scope("function saasAiCeoProductizedAnswerText", "function classifySaasLocalClockRequest")
    assert "merchantConversationText(" in productized_answer
    assert "productizeJiejingProductCopy(" not in productized_answer

    streaming = scope("function updateCeoAssistantStreamingMessage", "function updateCeoAssistantMessage")
    assert "merchantConversationText(" in streaming
    assert "productizeJiejingProductCopy(" not in streaming

    assert 'assistant_text: merchantConversationText(text)' in APP
    print("PASS jiejing_ai_ceo_copy_fidelity")


if __name__ == "__main__":
    main()
