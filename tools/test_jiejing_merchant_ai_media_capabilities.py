#!/usr/bin/env python3
"""Merchant-facing contract for truthful AI and media capabilities."""

from __future__ import annotations

import re
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


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

    generation = function_scope(app_js, "saasMediaGenerationState", "saasImageRecognitionState")
    for marker in (
        "state.saasMediaCapabilities?.image_generation",
        "capability.live_image_generation_enabled === true",
        "capability.live_provider_calls_allowed === true",
        "capability.live_video_generation_enabled === true",
    ):
        if marker not in generation:
            raise AssertionError(f"图片生成状态必须优先读取当前后端能力，而不是等待历史成功任务: {marker}")

    if '"/independence/status"' in app_js or "saasIndependence" in app_js:
        raise AssertionError("商家端不能读取内部独立运行与部署诊断")
    if '"/media/capabilities"' not in app_js:
        raise AssertionError("商家端没有读取最小图片识别与生成能力投影")

    sys.path.insert(0, str(ROOT))
    from jiejing_saas import ai_ceo_chat
    for enabled in (False, True):
        for configured in (False, True):
            for fallback in (False, True):
                environment = {
                    "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": str(enabled),
                    "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": str(fallback),
                    "JIEJING_AI_CEO_SEARCH_PROVIDER": "fixture-provider",
                }
                with patch.dict(os.environ, environment), patch.object(
                    ai_ceo_chat.PublicSearchProbeAdapter, "provider_status",
                    return_value={"configured": configured, "credential_source": "private-fixture"},
                ) as provider_status, patch.object(ai_ceo_chat.urllib.request, "urlopen", side_effect=AssertionError("no live probe")):
                    capability = ai_ceo_chat.build_public_search_capability_status()
                    expected = "disabled" if not enabled else "configured" if configured else "fallback_only" if fallback else "not_configured"
                    assert capability["status"] == expected
                    assert capability["available"] is (enabled and (configured or fallback))
                    assert capability["live_probe_performed"] is False
                    assert capability["secret_exposed"] is False
                    assert "credential" not in json.dumps(capability) and "private-fixture" not in json.dumps(capability)
                    if enabled:
                        provider_status.assert_called_once_with("fixture-provider")
                    else:
                        provider_status.assert_not_called()
                        answer = ai_ceo_chat._ai_ceo_capability_answer({})
                        assert "实时搜索已暂停" in answer and "兜底已启用" not in answer

    search = function_scope(app_js, "saasPublicSearchState", "saasMediaGenerationState")
    behavior = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const sandbox = {state: {saasLastPublicSearchHandoff: {status:'success',result_count:99}, saasAiCeoThread:[{source_records:[{url:'https://example.invalid'}]}]}};
vm.runInNewContext(SOURCE + ';this.readSearch = saasPublicSearchState;', sandbox);
for (const [status, available, label] of [
 ['configured',true,'联网搜索已配置'], ['fallback_only',true,'基础联网搜索已启用'],
 ['disabled',false,'联网搜索已暂停'], ['not_configured',false,'联网搜索未配置']]) {
 sandbox.state.saasMediaCapabilities = {public_search:{status,available,enabled:status!=='disabled'}};
 const result = sandbox.readSearch();
 assert.equal(result.title,label); assert.equal(result.configured,available);
}
for (const capability of [null, {}, {status:'configured'}, {status:'future-unknown',available:true}]) {
 sandbox.state.saasMediaCapabilities={public_search:capability};
 assert.equal(sandbox.readSearch().title,'联网搜索状态待确认');
 assert.equal(sandbox.readSearch().configured,false);
}
console.log('PASS merchant search capability 8 UI states; history cannot imply current readiness');
'''.replace("SOURCE", json.dumps(search))
    result = subprocess.run(["node", "-e", behavior], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    print(result.stdout.strip())

    capability_markup = panel[panel.index('data-ai-media-capability-grid="') : panel.index('</div>', panel.index('data-ai-media-capability-grid="'))]
    for forbidden in ("provider_cost", "secret_ref", "contract_version", "api_key", "美元", "USD"):
        if forbidden.lower() in capability_markup.lower():
            raise AssertionError(f"商家能力卡泄露内部字段: {forbidden}")

    print("PASS jiejing_merchant_ai_media_capabilities")


if __name__ == "__main__":
    main()
