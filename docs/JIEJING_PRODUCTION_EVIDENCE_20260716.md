# 捷境生产化证据闭环（2026-07-16）

## 当前结论

- 固定上线门禁：`107/107` 通过。
- 正式生产门禁：`3/8` 组就绪；这是门禁组计数，不是项目完成百分比。
- `beta_ready=true`。
- `production_ready=false`。
- `can_accept_real_customers=false`。
- `public_charging_allowed=false`。
- `real_platform_writes_enabled=false`。
- `ebay_token_refresh_success_count=0`。

## 已闭环的三组正式生产门禁

1. 部署包、部署演练、回滚点、部署后健康检查、秘密扫描和浏览器冒烟。
2. 托管 PostgreSQL、Postgres durable queue、Vault/KMS 秘密边界和实时队列探针。
3. 私有备份、隔离恢复、核心表计数核对、COS 加密分片和全量回读。

## 最新部署基线

- 部署包：`output/jiejing-public-staging-bundle/jiejing-public-staging-20260716-153857.zip`
- 文件数：`274`
- SHA256：`05a0bdf4778554f6da27da6d4428d6cf470039f9a4863e0dfeade8acfe640e18`
- 远端回滚点：`staging-patch-backup-20260716-234136`
- 部署状态：成功
- 部署后 API、worker、frontend：运行中，重启计数均为 0
- 本次监控门禁代码、配置工具和回归测试与远端 SHA256：一致

## CLS 数据面真实性证据

- 修复前只存在控制面探测时间，不能证明日志主题实际收到数据；新门禁不再把控制面访问误报为数据面就绪。
- 线上主题此前未创建索引；已创建 14 个匿名监控字段的最小键值索引，关闭全文索引，不包含内部字段或元数据。
- 已写入一条不含商家、请求、模型正文或秘密的合成探针；上传被接受，并通过 SearchLog 回查命中 1 条。
- 现有运行时错误告警共 1 条且已启用、已绑定通知；其查询在新索引上执行成功。未制造 5xx，也未发送测试通知。
- 控制面和数据面证据统一使用 24 小时有效期；两个时间戳均可解析、均未越过未来时钟偏差边界、均处于有效期内。
- 过期、非法、超过 5 分钟的未来时间戳现在会分别阻塞 CLS 就绪；非法、非有限或非正数阈值会安全回退到 24 小时。
- 运行时状态：CLS 控制面就绪、索引与数据面探针就绪、CLS blocker 为空。
- `production_monitoring_ready=false` 仍保持不变；持续指标采集管道、provider latency 告警和 provider cost 告警尚未完成，不能用一次性探针冒充持续监控。

## 线上验证

- `https://app.jiejing.shop/health`：HTTP 200，TLS 校验通过。
- `https://app.jiejing.shop/health/deep`：HTTP 200，TLS 校验通过。
- `https://app.jiejing.shop/readiness/product-saas`：HTTP 200，TLS 校验通过。
- `https://ops.jiejing.shop/`：HTTP 200，TLS 校验通过。
- `https://ops.jiejing.shop/owner/operations-overview`：无会话 HTTP 401 JSON。
- `https://ops.jiejing.shop/backup/plan`：非白名单路由 HTTP 404。
- `https://app.jiejing.shop/ops.html`：HTTP 404。
- `https://jiejing.shop/`：HTTP 301 跳转到 `https://app.jiejing.shop/`，TLS 校验通过。
- Cloudflare DoH：`ops.jiejing.shop` 状态 0，A 记录为 `43.129.205.244`。
- 主站通过 `--resolve` 绕过 Cloudflare 直连源站时返回 404；源站主站路由不可直接访问。
- 运营后台按当前 DNS only 方案直连可访问，且保持独立 Host、独立静态面和严格 API 白名单。

## 浏览器证据

- 真实 Chrome 内置控制桥在初始化前报 `failed to write kernel assets: path not found`，不是捷境页面错误。
- 按前端测试技能允许的回退路径，使用仓库现有 Playwright 端到端脚本。
- 商家七模块冒烟通过；1440x920 视口无横向溢出、无控件裁切、无 5xx、无登录遮挡、无内部诊断文案暴露。
- Listing 页面没有直接发布按钮；测试未触发真实 eBay 写入或真实收费。

## 启动竞争处理

- 一次同时重建 API/worker 时，PostgreSQL 初始化发生瞬时死锁，worker 自动重启 1 次后恢复。
- 根因是两个容器同时执行初始化，不是业务队列或数据损坏。
- 改为顺序单独重建 worker 后，worker 运行且重启计数归零。
- 本次加载 CLS 新鲜度配置时继续按 API 健康通过后再单独重建 worker 的顺序执行，三个容器最终重启计数均为 0。

## 仍未通过的五组正式生产门禁

1. 稳定域名/边缘回调：DNS、TLS、CORS、安全头、WAF 免费基线和主站源站锁定已完成；仍缺 eBay 回调域名与支付控制台回调验证。
2. 订阅计费：仍缺正式支付商户、签名 webhook、配额和异常路径的真实外部证明；禁止真实扣款测试。
3. eBay 新账号证明：刷新成功次数仍为 0；禁止重复旧 OAuth、冻结账号和未经批准的真实写入。
4. 监控：CLS 控制面、最小索引、匿名数据面探针、运行时错误告警、事件手册和内部 provider metrics 已就绪；仍缺持续匿名指标采集管道，以及供应商延迟与成本两类正式告警。
5. 主理人最终批准：只能在前四组完成后记录；当前收费和真实写入开关继续关闭。

## 不得误读

- `107/107` 只代表固定代码与部署前门禁全部通过，不代表正式收费上线。
- 正式生产门禁 `3/8` 只表示三组证据闭环，不是 37.5% 的项目完成度。
- `beta_ready=true` 不等于可以接收真实付费客户。
