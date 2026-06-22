# Jiejing Public WAF And Anti-Scrape Runbook

Updated: 2026-06-18

This runbook keeps Jiejing public launch defensive by default. It is written for the owner/operator, not for developers.

## Plain-language summary

We cannot make browser code impossible to copy. Anything sent to a browser can be seen.

What we can do:

- Keep the real moat on the backend: eBay workflows, Vault tokens, AI CEO execution logic, merchant memory, billing state, audit evidence, and confirmation center.
- Make scraping expensive: WAF, bot challenges, rate limits, no-index headers, no source maps, and account/API quotas.
- Keep the server hidden behind Cloudflare or Tencent Cloud WAF so attackers cannot bypass the firewall and hit the origin directly.

## What is already handled in code

- `robots.txt` disallows all crawlers on staging/app surfaces.
- HTML, static assets, and API responses return `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet, noimageindex`.
- The stable systemd Caddy entry for `app.jiejing.shop` serves `/robots.txt` directly from the deployment root with `Cache-Control: no-store`.
- Cloudflare Managed robots content is active on `https://app.jiejing.shop/robots.txt`; the live response includes Cloudflare content signals with AI training denied and known AI crawler user-agents blocked.
- Cloudflare free custom rule `Jiejing block scanner paths` is active and blocks common scanner paths such as `/.env`, `/.git`, `/wp-`, `/wordpress`, `/phpmyadmin`, `/adminer`, `/xmlrpc.php`, and `/cgi-bin`.
- Cloudflare free rate limiting rule `Jiejing auth endpoint rate limit` is active for `/auth/login`, `/auth/register`, and `/auth/demo-session`: 20 requests per 10 seconds per IP, block for 10 seconds.
- Cloudflare free custom rule `Jiejing challenge scripted expensive API` is active for script-like user agents on high-cost API paths including `/tasks`, `/reports`, `/model`, `/commercial`, `/data-packets`, and eBay workflow paths. Live proof: `curl`-style traffic to `https://app.jiejing.shop/reports` returns Cloudflare `403` with `Cf-Mitigated: challenge`.
- The backend has its own high-cost API per-IP, per-route-group limiter. Its status packet is behind `/security/rate-limit/status` and now requires a logged-in platform-internal admin. Default: 180 requests per 60 seconds for each protected route group, configurable by `JIEJING_EXPENSIVE_API_RATE_LIMIT_*`.
- Backend JSON responses use `Cache-Control: no-store`.
- Public nginx blocks `.map` source map requests with `404`.
- BYOK, eBay tokens, refresh tokens, Stripe secrets, and client secrets stay behind the backend/Vault boundary.

## What the owner must do in an external console

These steps require account login, DNS ownership, or billing ownership. Codex cannot safely do them without your session.

The domain `jiejing.shop` is now registered. `app.jiejing.shop` is active
through Cloudflare proxied DNS and returns the Jiejing health response over
HTTPS. The origin host firewall now blocks direct public web access to ports
`80` and `443` except from Cloudflare IP ranges. Backend CORS now allows
`https://app.jiejing.shop` as the stable origin.

For the step 2/3/4 preparation packet, use
`docs/JIEJING_EDGE_WAF_ORIGIN_CALLBACK_PREP_20260618.md` and:

```powershell
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare
python tools\jiejing_edge_cutover_preflight.py --domain jiejing.shop --registration-status registered --provider cloudflare
```

This command is intentionally no-write: it does not call Stripe, does not create Checkout,
does not run eBay OAuth, and does not change the cloud security group.

1. Buy or choose the stable domain. Current status: done for `jiejing.shop`.
2. Put the domain behind Cloudflare or Tencent Cloud EdgeOne/WAF.
3. Turn on WAF managed rules only if the selected plan supports them without surprise cost. Cloudflare showed this as a Pro upgrade, so it is not enabled in the free baseline.
4. Turn on bot protection only after confirming it will not break Stripe/eBay callbacks. Bot Fight Mode was not visible as a final verified toggle in the current Cloudflare UI, so the free baseline uses AI bot blocking, managed robots, and a targeted Managed Challenge rule instead.
5. Add rate limits for login, register, app, and API paths. Current free baseline uses the single available Cloudflare rate limiting rule for auth endpoints plus backend high-cost API rate limiting.
6. Add a Turnstile challenge for signup/login/high-cost trial actions.
7. Lock the origin server firewall so only the edge provider can reach HTTP/HTTPS.
8. Add the stable domain callback URL in eBay developer settings.
9. Add the stable domain return URLs in Stripe Checkout and Portal.

## Cloudflare minimum rules

Use these as rule names and intent. Keep the exact expressions simple in the console.

### Rule 1: Block direct bad bot traffic

Action: Managed Challenge or Block.

Paths:

- `/app.html`
- `/assets/*`
- `/commercial/*`
- `/model/*`
- `/data-packets/*`
- `/reports/*`
- `/audit-logs/*`

Trigger when:

- Bot score is low, or
- Request has no normal browser headers, or
- Request rate is high, or
- The country/ASN is clearly not part of expected customer traffic.

### Rule 2: Login and signup rate limit

Action: Managed Challenge, then Block if repeated.

Paths:

- `/auth/login`
- `/auth/register`
- `/auth/password*`

Starting threshold:

- 5 to 10 attempts per minute per IP.
- Also rate limit by email/account where the app supports it.

Current Cloudflare free baseline:

- Rule name: `Jiejing auth endpoint rate limit`.
- Match: `app.jiejing.shop` and `/auth/login`, `/auth/register`, `/auth/demo-session`.
- Threshold: 20 requests per 10 seconds per IP.
- Action: block for 10 seconds.
- Reason for this shape: the free zone showed one available rate limiting rule and the action list only exposed `Block` for rate limiting.

### Rule 3: Expensive API rate limit

Action: Managed Challenge or 429.

Paths:

- `/tasks*`
- `/reports*`
- `/model/*`
- `/commercial/*`
- `/data-packets/*`
- `/ebay-read-only/*`
- `/ebay-write/*`

Starting threshold:

- Low anonymous quota.
- Higher authenticated quota.
- Company/store quota enforced by backend billing plan.

Current free baseline:

- Edge challenge rule name: `Jiejing challenge scripted expensive API`.
- Action: Managed Challenge for script-like user agents on high-cost API path groups.
- Callback exclusions: `/billing/webhook` and `/oauth/ebay/callback` are excluded from this edge challenge rule.
- Backend limiter: enabled by default, protects the same high-cost API groups per IP and route group.
- Backend status endpoint: `https://app.jiejing.shop/security/rate-limit/status` after staging deploy, available only to a logged-in platform-internal admin.

### Rule 4: No AI crawler training

Enable:

- AI Crawl Control
- Managed robots.txt

Policy:

- Search indexing remains disabled until public launch approval.
- AI training and bulk scraping are not allowed.

### Rule 5: Origin lock

On the server firewall, only allow HTTP/HTTPS from Cloudflare or Tencent Cloud edge IP ranges.

Keep SSH restricted to trusted operator access and key login only.

### Rule 6: Scanner path block

Current Cloudflare free baseline:

- Rule name: `Jiejing block scanner paths`.
- Action: Block.
- Match: `app.jiejing.shop` or `jiejing.shop` plus paths containing `/.env`, `/.git`, `/wp-`, `/wordpress`, `/phpmyadmin`, `/adminer`, `/xmlrpc.php`, or `/cgi-bin`.
- Live proof: `https://app.jiejing.shop/.env` returns Cloudflare `403`.

## Tencent Cloud WAF / EdgeOne equivalent

If using Tencent Cloud instead of Cloudflare:

- Enable Web Application Firewall.
- Enable Bot behavior analysis.
- Enable custom bot rules.
- Enable custom rate limiting.
- Use JA3 / client fingerprint signals if available.
- Add the same path groups and thresholds above.
- Configure origin protection so visitors cannot bypass EdgeOne/WAF.

## What should stay blocked before public paid launch

- No public paid launch until stable domain WAF is active.
- No real Stripe charging until live Price IDs, Checkout, Portal, signed webhook, and quota lifecycle are verified.
- No new eBay publish smoke until there is a clean new eBay account and fresh product/SKU/assets.
- No direct origin exposure.
- No source maps.
- No public detailed readiness/admin data.

## Operator checklist

- [x] Stable domain chosen and registered: `jiejing.shop`.
- [x] `app.jiejing.shop` no longer resolves to placeholder DNS and passes HTTPS health.
- [x] Domain proxied through Cloudflare or Tencent Cloud WAF.
- [ ] WAF managed rules enabled. Current Cloudflare UI showed this behind Pro; do not enable without approval for cost.
- [x] Bot/challenge baseline enabled. Managed robots / AI crawler control is active, and the targeted `Jiejing challenge scripted expensive API` rule was verified against curl-style traffic. The separate Bot Fight Mode toggle was not visible in the current Cloudflare UI.
- [x] Managed robots / AI crawler content signals enabled on `https://app.jiejing.shop/robots.txt`.
- [x] Scanner path block active for `/.env`, `/.git`, `/wp-`, `/phpmyadmin`, `/adminer`, `/xmlrpc.php`, `/cgi-bin`.
- [x] Rate limits added for login/signup/auth demo endpoints.
- [x] Extra protection added for expensive APIs: targeted Cloudflare Managed Challenge for script-like traffic plus backend high-cost API limiter.
- [ ] Turnstile or equivalent challenge enabled for signup/login/high-cost actions.
- [x] Origin server HTTP/HTTPS only accepts edge provider traffic.
- [ ] eBay callback moved to stable domain.
- [ ] Stripe Checkout/Portal/webhook URLs moved to stable domain.
- [ ] No-charge launch rehearsal rerun after the above.
