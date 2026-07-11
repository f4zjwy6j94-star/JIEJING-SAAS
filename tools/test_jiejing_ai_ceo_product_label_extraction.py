#!/usr/bin/env python3
"""Guard AI CEO product handoffs against generic prompt fragments."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    end = source.find("\nfunction ", start + len(marker))
    return source[start : end if end > start else len(source)]


def require(body: str, marker: str, label: str) -> None:
    if marker not in body:
        raise AssertionError(f"missing {label}: {marker}")


def reject(body: str, marker: str, label: str) -> None:
    if marker in body:
        raise AssertionError(f"forbidden {label}: {marker}")


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    invalid_label = function_body(app_js, "saasIsInvalidMarketProductLabel")
    for marker in ["产品名", "商品名", "两条理由"]:
        require(invalid_label, marker, "generic prompt-fragment product guard")

    concise_label = function_body(app_js, "saasAiCeoConciseAnswerProductLabel")
    for marker in ["assistant_text", "lines[0]", "理由", "saasIsConcreteProductLabel"]:
        require(concise_label, marker, "concise model answer product extraction")

    market_label = function_body(app_js, "saasAiCeoMarketProductLabel")
    require(market_label, "saasAiCeoConciseAnswerProductLabel(latest)", "answer-first product extraction")
    require(market_label, "(?:是|为|:|：)", "explicit merchant product delimiter")
    reject(market_label, "[:：]?\\s*([^\\n。；;]{2,80})", "optional product delimiter")

    print("PASS jiejing_ai_ceo_product_label_extraction")


if __name__ == "__main__":
    main()
