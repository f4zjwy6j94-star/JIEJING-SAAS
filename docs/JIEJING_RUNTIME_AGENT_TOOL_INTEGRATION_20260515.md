# 捷境 Runtime Agent 大模型与工具接入记录 2026-05-15

本记录只说明自研 Runtime 的低风险执行能力，不表示已经执行真实 eBay 发布、采购付款、退款、广告或店铺政策修改。

## 已完成

1. 7 个自研 Agent 已接入真实大模型开关

- `jiejing-local`：默认本地规则版，稳定离线可跑。
- `jiejing-llm`：使用 `model_client_from_env()`，可走 OpenAI Responses 或 OpenAI-compatible chat endpoint。
- 真实模型输出不会直接替换安全骨架，而是合并进自研 Agent 的结构化报告里。
- 未配置模型 key / endpoint / model 时自动回退，不会卡死。

关键环境变量：

- `JIEJING_MODEL_PROVIDER=responses|chat|rules`
- `JIEJING_MODEL_API_KEY` 或 `OPENAI_API_KEY`
- `JIEJING_MODEL` 或 `OPENAI_MODEL`
- `JIEJING_MODEL_BASE_URL` / `OPENAI_BASE_URL` / `JIEJING_MODEL_ENDPOINT`

## 市场 Agent 工具

市场数据拆成 `market.data_packet`，并可回填到 `market.report`：

- eBay read-only / Browse / Taxonomy 信号
- Public search provider 信号
- 跨平台公开参考
- 货源可得性
- 物流估算

关键环境变量：

- `JIEJING_EBAY_READ_LIVE=1`
- `JIEJING_EBAY_READ_TOKEN` 或 `EBAY_ACCESS_TOKEN`
- `JIEJING_SEARCH_LIVE=1`
- 搜索工具需要通过 `public_search_probe.endpoint/api_key` 或后端配置接入

修复点：

- 之前工具返回 pending snapshot 时，市场数据包会误判 ready。
- 现在按 snapshot.status 识别，`pending_connector` / `pending_tool` 不会被当成已完成。

## 产品 Agent 工具

新增 `EbayListingMetadataAdapter`：

- Taxonomy：读取类目 item specifics。
- Account API：读取 fulfillment / payment / return policies。
- 只读，不创建/修改政策，不发布 Listing。

关键环境变量：

- `JIEJING_EBAY_LISTING_METADATA_LIVE=1`
- `JIEJING_EBAY_ACCOUNT_READ_TOKEN` / `JIEJING_EBAY_READ_TOKEN` / `EBAY_ACCESS_TOKEN`

## 素材 Agent 工具

新增 `MediaGenerationAdapter`：

- 可接收已生成的 asset manifest。
- 可调用配置好的图片/视频 provider endpoint。
- 没有 provider 或 manifest 时保持 `pending_provider`，不会声称图片/视频已经生成。

关键环境变量：

- `JIEJING_MEDIA_GENERATION_LIVE=1`
- `JIEJING_IMAGE_GENERATION_ENDPOINT`
- `JIEJING_VIDEO_GENERATION_ENDPOINT`
- `JIEJING_MEDIA_GENERATION_API_KEY` 或 `OPENAI_API_KEY`

## Hermes 同题双跑

新增 `RuntimeComparisonScorer` 和 CLI：

```powershell
python tools\jiejing_runtime_cli.py compare-results `
  --jiejing-result <jiejing_result.json> `
  --hermes-result <hermes_result.json> `
  --output-json <comparison.json>
```

评分维度：

- 报告必填章节覆盖率
- 来源记录数量
- 缺口数量
- 风险数量
- 确认项数量
- 是否出现真实执行越界声明

只有连续同题稳定、覆盖率足够、无越界声明时，才允许把低风险任务从 Hermes 逐步迁到自研 Agent。

## 当前真实状态

- 自研 Runtime 已具备真实模型和工具 Provider 的工程入口。
- 当前没有在本次任务中配置真实外部 key，也没有调用真实 eBay 写入。
- eBay / 搜索 / 图片 / 视频都按“后端显式配置后才 live”的原则实现。
- 真实发布、付款、退款、广告、政策修改仍必须走确认中心和执行服务。

## 验证

已通过：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
Get-ChildItem tools\test_jiejing_*.py | Sort-Object Name | ForEach-Object {
  python $_.FullName
}
```

新增专项：

- `tools/test_jiejing_live_tool_contracts.py`

