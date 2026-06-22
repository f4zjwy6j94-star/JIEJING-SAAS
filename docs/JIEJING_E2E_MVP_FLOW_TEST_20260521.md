# Jiejing E2E MVP Flow Test - 2026-05-21

## Scope

Tested the active Hong Kong staging route:

`https://individually-buffalo-prescribed-blocking.trycloudflare.com`

The test used a temporary merchant account and did not enter real eBay credentials, real model keys, or trigger any platform write.

## Flow Tested

1. Open public homepage with register entry.
2. Register a temporary merchant account.
3. Select merchant identity: existing eBay store.
4. Complete the onboarding entry and enter AI CEO workbench.
5. Verify workbench navigation and account menu.
6. Verify settings page boundaries: eBay read-only, BYOK, secret_ref, real writes off.
7. Verify confirmation center boundary.
8. Log out.
9. Log back in with the same merchant account.
10. Verify returning merchant goes directly to workbench instead of repeating identity selection.

## Result

Passed with one product/UI warning.

Evidence output:

- `output/browser-smoke/20260521-e2e-1779309792014-result.json`
- `output/browser-smoke/20260521-e2e-1779309792014-onboarding.png`
- `output/browser-smoke/20260521-e2e-1779309792014-workbench.png`
- `output/browser-smoke/20260521-e2e-1779309792014-settings-connect.png`
- `output/browser-smoke/20260521-e2e-1779309792014-confirm-center.png`
- `output/browser-smoke/20260521-e2e-1779309792014-repeat-login.png`

## Fix Applied During Test

Problem found:

Returning merchants who had already completed the entry guide were still sent back to identity selection after logging in again.

Fix:

The public login entry now remembers completed onboarding per account in browser storage and routes returning merchants directly to the AI CEO workbench. The route preserves merchant stage:

`app.html?start=app&view=workflow&stage=store_opened`

Production follow-up:

This state should move from browser storage into the backend account profile before paid beta, so it works across devices and browsers.

## What Works Now

- Register creates a SaaS account and session.
- First-time merchant sees onboarding once.
- Workbench opens without the old blocking splash.
- Sidebar modules are present:
  - 今日经营
  - AI 工作流
  - Listing 工厂
  - 素材工坊
  - 铺货质检
  - AI CEO 汇报
  - 决策队列
  - 客服物流
  - 设置
- Account menu includes settings, refresh, switch account, logout, BYOK boundary, and real-write boundary.
- Company/account name is shown as account identity, not as an eBay store name.
- Store state stays as `待连接 eBay 店铺` until official eBay read-only authorization.
- BYOK panel exists and states that raw model key is not returned to the frontend.
- `real_platform_writes_enabled=false` is visible.
- Market Report + Listing Package action is blocked when eBay packet/BYOK proof is missing.
- Confirmation center explains that publication, payment, refunds, ads, policy edits, and sensitive promises require merchant confirmation.
- Logout clears session.
- Returning login now goes straight into the workbench.

## Current MVP Progress

Controlled staging readiness: 78%

Minimum commercial MVP readiness: 68%

Production-grade paid SaaS readiness: 52%

These are intentionally separate:

- Controlled staging can support real read-only testing.
- Commercial MVP still needs live model value proof on official eBay data.
- Paid SaaS still needs production infra, monitoring, backup restore proof, hardened sessions, and billing/domain readiness.

## Remaining Issues

### P0

- `model_value_proof` remains the current blocker.
- Need run the real value loop: official eBay packet -> merchant BYOK -> live Market Report -> live Listing Package -> confirmation center quality review.

### P1

- Settings page has a transient login-state inconsistency: top account menu can show the logged-in merchant while the settings body still shows `需要登录 / 待登录` until backend state catches up.
- Onboarding completion is currently remembered in browser storage, not backend account state.
- Some old product-demo words still exist in hidden/inactive frontend branches. They are not visible on the core tested route, but should be removed from source as cleanup.
- Session token is still browser storage based. Production should move toward HttpOnly secure cookies or equivalent hardened session handling.

### P2

- Setup Guide still references borrowed SaaS ideas such as Shopify as an internal product analogy. It should remain clearly marked as borrowed UX pattern, not Jiejing scope.
- The workbench still needs tighter empty-state polish for new accounts with no eBay connection.

## Next Step

Use the already connected real merchant path, not another dummy account:

1. Merchant login.
2. Confirm official eBay packet is visible.
3. Save real BYOK model key through the backend secret boundary.
4. Run live model-backed Market Report + Listing Package.
5. Review report quality, listing usefulness, confirmation items, and merchant memory writeback.

