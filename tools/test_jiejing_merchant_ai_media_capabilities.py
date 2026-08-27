#!/usr/bin/env python3
"""Merchant-facing contract for truthful AI and media capabilities."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_scope(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"function {next_name}(", start)
    return source[start:end]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    panel = function_scope(
        app_js,
        "renderSaasMerchantModelProviderPanel",
        "renderSaasMerchantMemoryPanel",
    )

    if 'data-ai-media-capability-grid="merchant_ai_media_capabilities_v1"' not in panel:
        raise AssertionError("AI 与素材页缺少商家四能力卡")

    labels = re.findall(
        r'data-ai-media-capability="[^"]+"[\s\S]*?<span>([^<]+)</span>',
        panel,
    )
    expected = ["文字分析", "图片识别", "联网搜索", "图片生成"]
    if labels != expected:
        raise AssertionError(f"四能力卡必须按商家任务展示: {labels}")

    boundary = "不支持图片的模型不会被要求猜图，图片先由支持视觉的服务提取事实，再交给 AI CEO 分析与填写 Listing。"
    if boundary not in panel:
        raise AssertionError("AI 与素材页没有说明文本模型与视觉服务的真实分工")

    for state_source in (
        "saasPrimaryTextAiState()",
        "saasImageRecognitionState()",
        "saasPublicSearchState()",
        "saasMediaGenerationState()",
    ):
        if state_source not in panel:
            raise AssertionError(f"能力卡没有读取真实连接状态: {state_source}")

    recognition = function_scope(app_js, "saasImageRecognitionState", "saasPrimaryTextAiState")
    if "saasMediaCapabilities?.product_image_recognition?.configured" not in recognition:
        raise AssertionError("图片识别状态没有读取商家安全的独立视觉能力证据")
    for false_signal in ("media_configured", "saasMediaGenerationState()", "mediaConnection.liveReady"):
        if false_signal in recognition:
            raise AssertionError(f"图片生成能力不能冒充图片识别已连接: {false_signal}")

    if '"/independence/status"' in app_js or "saasIndependence" in app_js:
        raise AssertionError("商家端不能读取内部独立运行与部署诊断")
    if '"/media/capabilities"' not in app_js:
        raise AssertionError("商家端没有读取最小图片识别能力投影")

    capability_markup = panel[panel.index('data-ai-media-capability-grid="') : panel.index('</div>', panel.index('data-ai-media-capability-grid="'))]
    for forbidden in ("provider_cost", "secret_ref", "contract_version", "api_key", "美元", "USD"):
        if forbidden.lower() in capability_markup.lower():
            raise AssertionError(f"商家能力卡泄露内部字段: {forbidden}")

    print("PASS jiejing_merchant_ai_media_capabilities")


if __name__ == "__main__":
    main()
