# 捷境 Runtime DeepSeek 接入与自检记录 2026-05-15

本记录说明本次工程推进内容。没有执行真实 eBay 发布、采购付款、退款、广告修改或店铺政策修改。

## 1. DeepSeek 接入

已新增 `DeepSeekModelClient`：

- 默认模型：`deepseek-v4-pro`
- 默认 endpoint：`https://api.deepseek.com/v1/chat/completions`
- 默认 timeout：`120` 秒。`deepseek-v4-pro` 可能比普通草稿模型慢，正式 SaaS 不能同步阻塞等待，后续要走异步任务队列。
- 可作为 `jiejing-deepseek` adapter 使用
- 也可通过 `JIEJING_MODEL_PROVIDER=deepseek` 让 `jiejing-llm` 使用 DeepSeek

密钥来源顺序：

1. `JIEJING_MODEL_API_KEY`
2. `DEEPSEEK_API_KEY`
3. `JIEJING_HERMES_AUTH_JSON`
4. Windows 下默认通过 WSL 读取 `/home/hermes/.hermes/auth.json`

密钥只进入进程内存，不写入前端、不写入报告、不打印。

可关闭 WSL 自动发现：

```powershell
$env:JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP='0'
```

## 2. 新增运行方式

```powershell
python tools\jiejing_runtime_cli.py run-workflow `
  --product "Stainless Steel Travel Tumbler" `
  --goal "Run DeepSeek-backed Jiejing workflow smoke test." `
  --adapter jiejing-deepseek `
  --output-dir output\deepseek-smoke
```

默认自检不消耗模型额度。需要真实 DeepSeek 调用时：

```powershell
$env:JIEJING_SELF_CHECK_LIVE_MODEL='1'
python tools\jiejing_runtime_self_check.py
```

## 3. 自检结果

本次已运行：

```powershell
python tools\jiejing_runtime_self_check.py
```

输出：

- `output/jiejing-agent-runtime-samples/self-check/jiejing_runtime_self_check_latest.json`
- `output/jiejing-agent-runtime-samples/self-check/jiejing_runtime_self_check_latest.md`

结果：

- DeepSeek credential 可发现：`True`
- Secret exposed：`False`
- Runtime sample workflow：`completed_with_blocks`
- Live model smoke：已用 `JIEJING_SELF_CHECK_LIVE_MODEL=1` 显式运行过一次；`deepseek-v4-pro` 成功返回，`model_assist.status=applied`，`model_mode=live_http_model`
- 经验：第一次 45 秒 timeout，改成 120 秒后成功。正式 SaaS 必须用异步队列和进度反馈，不能让网页同步等待长模型响应。

## 4. 当前真实进度

相比上一版：

- Runtime 底座：从约 `85%-88%` 提升到约 `88%-90%`
- 自研 Agent 替代 Hermes 的真实能力：从约 `40%-45%` 提升到约 `48%-52%`
- 接入 SaaS 模拟端：仍约 `82%-86%`，因为前端多数模块还需要从静态演示改成 Runtime 数据驱动
- SaaS 演示网站 / 前端闭环：仍约 `88%-92%`

还不能报 100%，原因：

- DeepSeek 已接入，但默认没有跑 live 额度测试
- 搜索 Provider、eBay 只读、1688、橙联、图片/视频 Provider 尚未全部做真实稳定联调
- 正式 SaaS 的后端、多租户、数据库、队列、密钥保险柜、云端部署还没完成

## 5. 下一步

优先级建议：

1. 打开 `JIEJING_SELF_CHECK_LIVE_MODEL=1` 跑一次 DeepSeek 小任务，验证真实模型响应。
2. 接搜索 Provider，先做市场数据真实采集。
3. 接 OpenAI GPT Image 或其他图片 Provider，让素材工坊真实出图。
4. 接 Sora / Runway / Kling 的视频 Provider。
5. 把 SaaS 前端模块逐步改成读取 Runtime API 输出，而不是静态演示数据。
