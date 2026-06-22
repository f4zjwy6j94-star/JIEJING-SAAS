# 捷境 Runtime 公开搜索 Provider 接入记录 2026-05-15

本记录只说明低风险公开搜索能力的工程入口，不代表已经接入真实 eBay 发布、采购付款、退款、广告或店铺政策修改。

## 1. 本轮完成

Runtime 的 `public_search_probe` 已从单纯占位升级为可选 Tavily 搜索 Provider：

- 默认仍然不跑真实搜索，避免误花额度或误把公开网页当成官方平台数据。
- 显式设置 `provider=tavily` 且开启 `live_enabled=True` 后，可以调用 `https://api.tavily.com/search`。
- 搜索结果统一归一化为 `title / url / snippet / domain / commerce_hint / score`。
- Tavily 的 `content` 字段会进入 Runtime 的 `snippet`，后续市场 Agent 可以拿它作为公开搜索信号。
- API key 只在后端 Runtime 进程内读取，不写入前端、不写入报告、不打印。

## 2. 密钥来源

搜索 key 的优先级：

1. `public_search_probe.api_key`
2. `JIEJING_SEARCH_API_KEY`
3. `TAVILY_API_KEY`
4. Windows 环境下读取 WSL Hermes 的 `/home/hermes/.hermes/.env` 里的 `TAVILY_API_KEY`

Runtime 报告只会显示：

- 是否配置成功
- endpoint host
- credential source
- `secret_exposed=False`

不会显示真实 key。

## 3. 自检方式

默认自检不消耗搜索额度：

```powershell
python tools\jiejing_runtime_self_check.py
```

需要跑一次真实 Tavily 搜索 smoke test 时：

```powershell
$env:JIEJING_SELF_CHECK_LIVE_SEARCH='1'
python tools\jiejing_runtime_self_check.py
```

## 4. 对捷境流程的意义

以前市场报告如果没有真实 eBay / 1688 / 公开网页数据，只能标记为推断或演示。

现在 Runtime 至少具备了第一层公开搜索入口：

商家目标
↓
market.data_packet
↓
Tavily 公开搜索信号
↓
市场经理写判断
↓
缺 eBay 官方数据、供应商资料、物流报价时继续保留缺口

这不会替代 eBay API、1688 API 或橙联报价，但能让市场报告从“纯规则推断”前进一步，变成“带公开网页来源的低风险初筛”。

## 5. 仍然不能做的事

- 不能把公开搜索结果当成 eBay 官方销量。
- 不能绕过平台反爬或登录限制。
- 不能把不确定的公开网页价格写成真实利润。
- 不能自动发布 Listing。
- 不能自动采购、付款、退款、开广告或改店铺政策。

## 6. 下一步

1. 给 `market.data_packet` 增加 eBay Browse / Taxonomy 只读 live smoke。
2. 给 `source.match` 增加 1688 链接或授权接口的读取适配。
3. 给 `asset.brief` 接真实图片/视频生成 Provider。
4. 把 Runtime 返回结果更深接入 SaaS 前端各模块，而不是只做静态演示。
