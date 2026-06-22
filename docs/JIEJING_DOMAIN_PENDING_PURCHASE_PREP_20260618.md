# 捷境域名审核期准备清单

更新时间：2026-06-18

目标域名：`jiejing.shop`

这份清单用于“腾讯云实名信息模板审核中、域名还没有正式购买”的阶段。它不触发真实扣费，不触发 eBay OAuth，不改 Stripe live 配置，也不做真实平台写入。

## 现在能做什么

可以先做：

- 确认品牌入口结构：`jiejing.shop` 作为主域，`app.jiejing.shop` 作为 SaaS 工作台。
- 预留回调地址：`https://app.jiejing.shop/oauth/ebay/callback`。
- 预留 Stripe 地址：
  - `https://app.jiejing.shop/billing/success`
  - `https://app.jiejing.shop/billing/cancel`
  - `https://app.jiejing.shop/settings/billing`
  - `https://app.jiejing.shop/billing/webhook`
- 选择边缘防护方案：Cloudflare 或腾讯云 EdgeOne/WAF。
- 准备源站锁定规则：正式切换后只允许边缘服务访问网站端口。
- 跑本地预检工具，确认系统仍把域名状态标为 blocked，而不是误判为 ready。

不能提前做：

- 不能验证 DNS，因为域名还没有正式购买。
- 不能验证 TLS，因为 DNS 还没有指向边缘。
- 不能把 eBay callback 正式切过去。
- 不能把 Stripe live webhook/Checkout/Portal 正式切过去。
- 不能开放真实收费。

## 香港服务器限制

当前服务器在香港。按腾讯云备案规则，使用中国香港或境外服务器开办网站通常不需要 ICP 备案，也不能用香港服务器去办理腾讯云备案。

如果以后把正式网站迁到中国大陆服务器，再按大陆服务器备案流程处理。

## 购买成功后的顺序

1. 腾讯云实名模板审核通过。
2. 下单购买 `jiejing.shop`。
3. 开启自动续费。
4. 等域名命名审核通过。
5. 选择 Cloudflare 或腾讯云 EdgeOne/WAF。
6. 添加 DNS：
   - `app.jiejing.shop` 指到边缘/WAF。
   - `jiejing.shop` 做官网或跳转入口。
   - `api.jiejing.shop` 先预留，后续如需拆 API 再启用。
7. 验证 HTTPS。
8. 验证安全响应头和 no-index/no-source-map 策略。
9. 锁源站，禁止绕过 WAF 直连。
10. 更新 eBay callback 和 Stripe URL。
11. 跑 no-real-charge 上线演练。

## 预检命令

```powershell
python tools\jiejing_domain_pending_purchase_preflight.py --domain jiejing.shop --registration-status realname_template_review
```

预期结果：

- `production_domain_ready=false`
- `domain_registered=false`
- blockers 包含 `domain_registration_not_confirmed`
- 推荐地址会出现 `app.jiejing.shop`
- 不会出现 token、client secret、API key 或支付密钥

购买成功但还没配置 DNS 时，可以改成：

```powershell
python tools\jiejing_domain_pending_purchase_preflight.py --domain jiejing.shop --registration-status registered
```

这只说明“域名已购买”，不代表 DNS/TLS/WAF/回调 ready。正式 ready 仍要等线上证据。

## 环境证据字段

这些字段只记录状态，不存秘密：

- `JIEJING_SELECTED_DOMAIN=jiejing.shop`
- `JIEJING_DOMAIN_REGISTRATION_STATUS=realname_template_review` 或 `registered`
- `JIEJING_PUBLIC_BASE_URL=https://app.jiejing.shop`
- `JIEJING_STABLE_DOMAIN=app.jiejing.shop`
- `JIEJING_CORS_ORIGIN=https://app.jiejing.shop`
- `JIEJING_DOMAIN_DNS_VERIFIED=1`
- `JIEJING_TLS_VERIFIED=1`
- `JIEJING_EBAY_CALLBACK_VERIFIED=1`
- `JIEJING_DEPLOYMENT_HARDENED=1`
- `JIEJING_SECURITY_HEADERS_VERIFIED=1`

## Step 2/3/4 no-write prep command

While the domain is still under review, WAF, origin-lock, eBay callback, and
Stripe URL preparation can be checked without touching real external systems:

```powershell
python tools\jiejing_edge_cutover_preflight.py --domain jiejing.shop --registration-status realname_template_review --provider cloudflare
```

Reference: `docs/JIEJING_EDGE_WAF_ORIGIN_CALLBACK_PREP_20260618.md`

Stripe secret key、webhook secret、eBay client secret、refresh token、模型 key 都不能写进这份清单或前端，只能放后端环境/Vault。
