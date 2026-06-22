# Jiejing Domain Active DNS/WAF Next Steps

Updated: 2026-06-18

Current domain: `jiejing.shop`

Current registrar status from Tencent Cloud: service status is normal. Treat this
as domain registration active, not as a pending purchase.

Current live probe from this workstation:

- `https://app.jiejing.shop/health` returns the Jiejing health response through
  Cloudflare.
- `https://jiejing.shop/` redirects to `https://app.jiejing.shop/`.
- Cloudflare scanner block is active for common leak paths such as `/.env`.
- Cloudflare targeted challenge is active for curl-style traffic on high-cost
  API paths such as `/reports`.
- Origin direct public web access to `43.129.205.244:80/443` is locked behind
  Cloudflare edge ranges.

Interpretation: the stable domain is active for private staging. This is still
not a paid public launch because Stripe live provider cutover, eBay callback
evidence, new eBay account smoke, and eBay token refresh success proof are not
complete.

This document records only non-secret launch state. It must not contain Stripe
secrets, eBay tokens, eBay refresh tokens, client secrets, model keys, API keys,
or BYOK values.

## Current Gate Meaning

- Domain ownership: active.
- DNS/TLS: stable app host is active through Cloudflare.
- WAF/edge: free baseline is active for scanner path block, auth rate limit,
  AI crawler controls, and targeted script challenge.
- Origin direct-access lock: applied for public web ports.
- eBay callback and Stripe URLs: prepare only until the external provider
  consoles are updated and a no-real-charge rehearsal passes.
- Paid public launch: still blocked.

## Runtime Evidence To Record

These values are safe non-secret staging evidence:

```env
JIEJING_SELECTED_DOMAIN=jiejing.shop
JIEJING_DOMAIN_REGISTRATION_STATUS=registered
JIEJING_TARGET_APP_HOST=app.jiejing.shop
```

These stable-domain values are now the target production/staging cutover values,
but provider callback verification is still separate:

```env
JIEJING_PUBLIC_BASE_URL=https://app.jiejing.shop
JIEJING_STABLE_DOMAIN=app.jiejing.shop
JIEJING_CORS_ORIGIN=https://app.jiejing.shop
```

Do not set these proof flags until the external provider consoles and no-write
rehearsals verify them:

```env
JIEJING_EBAY_CALLBACK_VERIFIED=1
JIEJING_STRIPE_CALLBACK_URLS_VERIFIED=1
```

## Next External Console Steps

1. Keep Cloudflare as the current edge provider.
2. Keep `app.jiejing.shop` and root `jiejing.shop` orange-cloud proxied.
3. Keep free WAF baseline active: scanner block, auth rate limit, managed
   robots/AI crawler controls, and the targeted expensive-API challenge rule.
4. Deploy the backend high-cost API limiter and verify
   `https://app.jiejing.shop/security/rate-limit/status`.
5. Update eBay callback and Stripe URLs only in the external provider consoles.
6. Run no-real-charge launch rehearsal and browser smoke before any paid public launch.

## Local No-Write Checks

```powershell
python tools\jiejing_domain_pending_purchase_preflight.py --domain jiejing.shop --registration-status registered
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare
python tools\jiejing_edge_cutover_preflight.py --domain jiejing.shop --registration-status registered --provider cloudflare
```

Expected:

- `domain_registered=true`
- stable app HTTPS and Cloudflare edge checks pass
- `production_domain_ready=false` or equivalent paid-launch gate remains blocked
- `status=blocked`
- blocked keys still include callback / live billing / eBay refresh evidence
- no charge, no Checkout session, no eBay OAuth, no platform write

## Exact Owner Console Values

Use these values when you are logged into the external console:

```text
Root domain: jiejing.shop
App host: app.jiejing.shop
Current origin IP: 43.129.205.244
Temporary staging URL: https://individually-buffalo-prescribed-blocking.trycloudflare.com
eBay callback after stable HTTPS: https://app.jiejing.shop/oauth/ebay/callback
Stripe success after stable HTTPS: https://app.jiejing.shop/billing/success
Stripe cancel after stable HTTPS: https://app.jiejing.shop/billing/cancel
Stripe portal return after stable HTTPS: https://app.jiejing.shop/settings/billing
Stripe webhook after stable HTTPS: https://app.jiejing.shop/billing/webhook
```

Do not paste Stripe secrets, webhook secrets, eBay tokens, eBay refresh tokens,
client secrets, model keys, BYOK values, passwords, or API keys into this file.
