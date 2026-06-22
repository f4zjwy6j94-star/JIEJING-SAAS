# Jiejing Origin Lock Status

Updated: 2026-06-18

## Current Result

`app.jiejing.shop` is now the working HTTPS app entry through Cloudflare.

The origin server still has public IP `43.129.205.244`, but direct public web
traffic to ports `80` and `443` is blocked by the host firewall. Web traffic
must pass through Cloudflare first.

## Applied Free Controls

- Cloudflare Free proxied DNS is active for `app.jiejing.shop`.
- Host firewall `ufw` is active on the Hong Kong Lighthouse origin.
- Inbound web ports `80` and `443` allow Cloudflare current IP ranges.
- Direct public origin web access is denied after the Cloudflare allow rules.
- SSH ports `22` and `2222` remain available but are rate-limited for operator
  recovery.
- No Tencent paid WAF, high-defense, bot product, or paid firewall service was
  purchased for this step.

## Verification

Expected public path:

```powershell
curl.exe -i --max-time 30 https://app.jiejing.shop/health
curl.exe -i --max-time 30 https://app.jiejing.shop/health/deep
curl.exe -i --max-time 30 https://app.jiejing.shop/readiness/product-saas
```

Expected direct-origin block:

```powershell
curl.exe -k -i --max-time 10 --resolve app.jiejing.shop:443:43.129.205.244 https://app.jiejing.shop/health
curl.exe -i --max-time 10 -H "Host: app.jiejing.shop" http://43.129.205.244/health
```

The direct-origin probes should time out or fail, not return the normal Jiejing
health JSON.

## Remaining Before Paid Public Launch

- Cloudflare managed WAF/bot/rate-limit/AI crawler/Turnstile controls still
  need final console verification before marking WAF complete.
- SSH is rate-limited but not fully restricted to a fixed operator IP or VPN.
  Do not mark `ssh_operator_only` ready until that is true.
- Stripe live Products/Price IDs, Checkout, Portal, signed webhook secret, and
  subscription/quota lifecycle still need final live-provider cutover.
- eBay callback should move to
  `https://app.jiejing.shop/oauth/ebay/callback`, but do not start OAuth with
  the frozen old account.
- No new real eBay publish smoke until there is a clean new eBay account and
  fresh real test product assets.

