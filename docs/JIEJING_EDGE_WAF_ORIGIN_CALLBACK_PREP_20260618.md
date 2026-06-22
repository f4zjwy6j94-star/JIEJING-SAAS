# Jiejing Edge WAF, Origin Lock, And Callback Prep

Updated: 2026-06-18

Target domain: `jiejing.shop`
Target app host: `app.jiejing.shop`
Current phase: domain registration, Cloudflare proxied DNS, HTTPS health,
root-domain edge redirect, Cloudflare free scanner-path block, auth endpoint
rate limit, managed robots/AI crawler controls, stable CORS, and origin web-port
lock are active. A targeted Cloudflare Managed Challenge for script-like
high-cost API traffic and a backend high-cost API limiter are now prepared and
tested. Callback registration, Stripe billing cutover, and eBay refresh-proof
recovery are not yet safe to mark complete.

This document covers steps 2, 3, and 4 after step 1 has completed:

- Step 2: Cloudflare or Tencent Cloud WAF.
- Step 3: origin direct-access lock.
- Step 4: eBay callback and Stripe URLs.

This is a no-write preparation checklist. It must not create Stripe Checkout sessions, trigger real charges, start eBay OAuth, publish to eBay, change inventory, or expose secrets.

## Plain Answer

Yes, step 1 is done. We can continue steps 2, 3, and 4 now, but only as
preparation until stable HTTPS works through the chosen edge provider.

Do now:

- Choose the edge provider path.
- Replace placeholder DNS with an edge/WAF route for `app.jiejing.shop`.
- Prepare WAF rules.
- Prepare the Tencent Cloud security group lock plan.
- Prepare the eBay and Stripe URL list.
- Run the no-write preflight tool.

Do not do yet:

- Do not lock the origin before `https://app.jiejing.shop/health` works through the WAF.
- Do not switch eBay callback before stable HTTPS works.
- Do not switch Stripe live URLs before stable HTTPS works.
- Do not run a real eBay OAuth test with the frozen account.
- Do not trigger real billing.

## Recommended Provider Path

Default recommendation: Cloudflare.

Reason: it is easier to understand and operate for the first production-grade edge layer. Tencent Cloud remains valid if you prefer to keep domain, DNS, WAF, and server under one provider.

Because the domain is being bought at Tencent Cloud, there are two clean options:

1. Cloudflare path:
   - Add `jiejing.shop` to Cloudflare.
   - Cloudflare gives you nameservers.
   - In Tencent Cloud domain DNS settings, change nameservers to Cloudflare.
   - Manage DNS and WAF in Cloudflare after propagation.

2. Tencent path:
   - Keep DNS in Tencent Cloud.
   - Add the domain to EdgeOne/WAF.
   - Manage DNS and WAF in Tencent Cloud.

## Current DNS Observation

Previous local DNS resolution during registration review:

```text
jiejing.shop      A 198.18.0.20
app.jiejing.shop  A 198.18.0.21
```

Current state: `app.jiejing.shop` is active through Cloudflare proxied DNS and
`https://app.jiejing.shop/health` returns the Jiejing health response. The bare
root `jiejing.shop` has a proxied Cloudflare `A @ -> 43.129.205.244` record and
a Cloudflare Single Redirect rule that sends `https://jiejing.shop/*` to
`https://app.jiejing.shop/${1}`. The host firewall now limits direct origin web
access to Cloudflare IP ranges.
`https://app.jiejing.shop/robots.txt` also returns Cloudflare Managed robots
content plus the Jiejing no-scrape policy. The backend CORS allowlist now
accepts `https://app.jiejing.shop` and temporarily keeps the old trycloudflare
origin for rollback checks. Continue to treat eBay callback, Stripe live URLs,
paid managed WAF rules, bot controls, expensive API rate limits, and
Turnstile/challenge as separate gates.

## Cloudflare Minimum Setup

When the domain is purchased:

1. Add `jiejing.shop` as a Cloudflare site.
2. Point `app.jiejing.shop` to the app route.
   - Preferred production shape: named Cloudflare Tunnel public hostname.
   - Acceptable simpler shape: proxied `A` or `CNAME` record to the origin route.
3. Point the root `jiejing.shop` to the same Cloudflare edge path and keep it
   proxied. Free option: add DNS record `A`, name `@`, value `43.129.205.244`,
   proxy enabled. The Caddy origin redirects this root host to
   `https://app.jiejing.shop/`.
4. Keep the orange-cloud proxy enabled for `app.jiejing.shop` and `jiejing.shop`.
5. Enable managed WAF rules only if the plan supports them without surprise
   cost. Current Cloudflare UI showed Managed Rules behind a Pro upgrade, so it
   is not part of the free baseline.
6. Enable bot protection or managed challenge for abnormal traffic only after
   confirming Stripe/eBay callbacks will not be challenged. Current free
   baseline uses AI bot blocking, managed robots, and the targeted custom rule
   `Jiejing challenge scripted expensive API`.
7. Add rate limits:
   - `/auth/login`
   - `/auth/register`
   - `/auth/password*`
   - `/tasks*`
   - `/reports*`
   - `/model/*`
   - `/commercial/*`
   - `/data-packets/*`
   - `/ebay-read-only/*`
   - `/ebay-write/*`
8. Keep managed robots / AI crawler controls active. Current live evidence:
   `https://app.jiejing.shop/robots.txt` includes Cloudflare Managed content
   signals with AI training denied and known AI crawler user-agents disallowed.
9. Add Turnstile or managed challenge for signup, login, and high-cost trial actions.

Current Cloudflare free baseline:

- Custom rule `Jiejing block scanner paths`: blocks paths containing `/.env`,
  `/.git`, `/wp-`, `/wordpress`, `/phpmyadmin`, `/adminer`, `/xmlrpc.php`, or
  `/cgi-bin` on `jiejing.shop` and `app.jiejing.shop`.
- Live scanner proof: `https://app.jiejing.shop/.env` returns Cloudflare `403`.
- Rate limiting rule `Jiejing auth endpoint rate limit`: `app.jiejing.shop`
  `/auth/login`, `/auth/register`, and `/auth/demo-session`; 20 requests per 10
  seconds per IP; block for 10 seconds.
- Custom rule `Jiejing challenge scripted expensive API`: Managed Challenge for
  script-like user agents hitting `/tasks`, `/reports`, `/model`,
  `/commercial`, `/data-packets`, `/ebay-read-only`, or `/ebay-write`.
  `/billing/webhook` and `/oauth/ebay/callback` are explicitly excluded.
- Live challenge proof: curl-style traffic to
  `https://app.jiejing.shop/reports` returns Cloudflare `403` with
  `Cf-Mitigated: challenge`.
- Backend high-cost API limiter: enabled by default in `jiejing_saas/api_server.py`.
  It protects high-cost route groups per IP and exposes safe non-secret evidence
  at `/security/rate-limit/status` after the staging patch is deployed.

Use Cloudflare rate limiting for abuse control and Cloudflare IP ranges when the origin security group needs to allow only edge traffic.

## Tencent EdgeOne/WAF Equivalent

When using Tencent Cloud instead of Cloudflare:

1. Add `jiejing.shop` to EdgeOne or WAF.
2. Point `app.jiejing.shop` through EdgeOne/WAF.
3. Enable managed web protection rules.
4. Enable bot behavior analysis.
5. Add custom rate limiting for the same paths listed above.
6. Enable CC attack protection or platform-managed rate limiting.
7. Keep the origin protected so direct IP visitors cannot bypass the edge.

## Origin Direct-Access Lock

Current origin IP: `43.129.205.244`

Do not apply this until the stable domain works through the edge:

```powershell
curl.exe -I https://app.jiejing.shop/health
```

After the edge path is verified, lock the Tencent Cloud security group:

- If using Cloudflare proxied DNS to the origin:
  - Allow inbound `80,443` only from current Cloudflare IP ranges.
  - Deny direct `80,443` from `0.0.0.0/0`.
  - Keep `22` restricted to trusted operator access only.

- If using a named Cloudflare Tunnel:
  - Public inbound `80,443` can be closed because cloudflared connects outward.
  - Keep `22` restricted to trusted operator access only.

- If using Tencent EdgeOne/WAF:
  - Allow inbound `80,443` only from Tencent EdgeOne/WAF origin-pull ranges or use Tencent's origin protection method.
  - Deny direct `80,443` from the public internet.
  - Keep `22` restricted to trusted operator access only.

Direct-origin probe after lock:

```powershell
curl.exe -I --max-time 10 http://43.129.205.244/health
```

Expected result: it should not return the normal Jiejing app health response.

## eBay Callback URLs

Prepare this URL only after stable HTTPS works:

```text
https://app.jiejing.shop/oauth/ebay/callback
```

This belongs in the eBay Developer authorization callback/RuName configuration. Registering the URL is not the same as starting OAuth. Do not run OAuth until a new clean eBay account test is explicitly approved.

## Stripe URLs

Prepare these URLs only after stable HTTPS works:

```text
https://app.jiejing.shop/billing/success
https://app.jiejing.shop/billing/cancel
https://app.jiejing.shop/settings/billing
https://app.jiejing.shop/billing/webhook
```

Stripe secrets, webhook secret, live secret key, Price IDs, and customer/subscription state must stay backend-only in Vault/env. The frontend must not receive Stripe secret keys or webhook secrets.

Use Stripe Billing + Checkout Sessions for subscription checkout, Customer Portal for subscription management, and signed webhooks for subscription state changes.

## No-Write Preflight

Run this now that the domain is active but DNS/WAF/TLS are still pending:

```powershell
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare
python tools\jiejing_edge_cutover_preflight.py --domain jiejing.shop --registration-status registered --provider cloudflare
```

Expected now:

- `status=blocked`
- `domain_registered=true`
- `edge_dns_https_ready=true`
- `root_bare_domain_redirect_ready=true`
- `managed_robots_ai_crawler_control_ready=true`
- `scanner_path_block_rule_ready=true`
- `scripted_expensive_api_challenge_ready=true`
- `backend_expensive_api_rate_limit_ready=true` after the current backend patch
  is deployed and `https://app.jiejing.shop/security/rate-limit/status` returns
  the rate-limit status packet
- `cloudflare_free_waf_baseline_ready=true` when the command includes the
  non-secret `--auth-rate-limit-console-evidence` flag after console
  verification
- `origin_direct_lock_ready=true`
- `cors_stable_origin_ready=true`
- `public_paid_launch_allowed=false`
- `charge_now_allowed=false`
- `triggers_ebay_oauth=false`
- `triggers_real_platform_write=false`
- `target_app_host=app.jiejing.shop`
- remaining blockers include callback evidence, Stripe live provider evidence,
  and eBay token refresh success proof

If Tencent or Cloudflare console work changes DNS, rerun:

```powershell
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare
python tools\jiejing_edge_cutover_preflight.py --domain jiejing.shop --registration-status registered --provider cloudflare
```

After visually verifying the Cloudflare auth rate-limit rule in the console,
include the non-secret evidence flag:

```powershell
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare --auth-rate-limit-console-evidence
```

After the backend high-cost API limiter is deployed, include the no-secret bot
and rate-limit evidence flags:

```powershell
python tools\jiejing_registered_domain_cutover_status.py --domain jiejing.shop --registration-status registered --provider cloudflare --auth-rate-limit-console-evidence --bot-protection-console-evidence --expensive-api-rate-limit-console-evidence
```

This only means the domain is active. It still does not mean WAF, origin lock,
eBay callback, or Stripe are ready.

## Safe Evidence Flags

These fields store only yes/no operational evidence. They must not contain secrets.

```text
JIEJING_EDGE_PROVIDER=cloudflare
JIEJING_EDGE_DOMAIN_ADDED=1
JIEJING_EDGE_DNS_PROXIED=1
JIEJING_WAF_MANAGED_RULES_ENABLED=0
JIEJING_BOT_PROTECTION_ENABLED=1
JIEJING_WAF_RATE_LIMITS_ENABLED=1
JIEJING_AI_CRAWLER_CONTROL_ENABLED=1
JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED=1
JIEJING_ORIGIN_HTTP_HTTPS_EDGE_ONLY=1
JIEJING_ORIGIN_DIRECT_IP_BLOCKED=1
JIEJING_ORIGIN_SSH_OPERATOR_ONLY=0
JIEJING_ORIGIN_EDGE_IP_ALLOWLIST_SOURCE=cloudflare_current_ip_ranges
JIEJING_EBAY_CALLBACK_VERIFIED=0
JIEJING_STRIPE_CALLBACK_URLS_VERIFIED=0
```

Current SSH note: public web ports are locked behind Cloudflare, but SSH is not
yet strict operator-only because `sshd -T` still reports
`passwordauthentication yes`. Before paid launch, turn password login off and
prefer fixed operator source IP or VPN/bastion access.

Do not write raw eBay tokens, refresh tokens, model keys, Stripe secret keys, webhook secrets, client secrets, passwords, or API keys into docs, frontend code, or public readiness payloads.

On the staging host, real runtime env values live under
`/opt/jiejing-staging/private/jiejing-saas.staging-oauth.env`. The project
`deploy/` directory should keep only `jiejing-saas.staging-oauth.env.example`
so bundle creation and patch deploys do not carry private values.

## Final Cutover Order

1. Domain registered: done.
2. Add the domain to Cloudflare or Tencent EdgeOne/WAF.
3. Replace placeholder DNS for `app.jiejing.shop` with the edge/WAF route.
4. Add the proxied root `@` record for `jiejing.shop` and verify it redirects
   to `https://app.jiejing.shop/`.
5. Verify `https://app.jiejing.shop/health`.
6. Turn on free WAF baseline rules. Current status: scanner path block, managed
   robots/AI crawler controls, auth endpoint rate limit, and targeted
   script-like expensive API Managed Challenge are active. Backend high-cost API
   rate limiting is implemented and should be verified at
   `/security/rate-limit/status` after deploy. Managed
   WAF rules showed as Pro-paid in the current Cloudflare UI and must not be
   enabled without cost approval.
7. Lock direct origin access: done for web ports through host `ufw`; SSH is
   rate-limited but not fixed-IP/VPN-only yet.
8. Register eBay callback and Stripe URLs.
9. Run no-real-charge billing cutover rehearsal.
10. Run readiness and browser smoke.
11. Only then consider new eBay account low-risk smoke.

## Official References

- Cloudflare rate limiting: `https://developers.cloudflare.com/waf/rate-limiting-rules/`
- Cloudflare origin IP allowlisting: `https://developers.cloudflare.com/fundamentals/concepts/cloudflare-ip-addresses/`
- Cloudflare IP ranges: `https://www.cloudflare.com/ips/`
- Tencent Cloud security groups: `https://www.tencentcloud.com/document/product/213/12452`
- Tencent Cloud security group rules: `https://www.tencentcloud.com/document/product/213/34272`
- Tencent EdgeOne managed rate limiting: `https://www.tencentcloud.com/document/product/1145/55936`
- Tencent EdgeOne custom rate limiting: `https://www.tencentcloud.com/document/product/1145/55943`
- Stripe webhooks: `https://docs.stripe.com/webhooks`
- Stripe Checkout success/cancel URLs: `https://docs.stripe.com/payments/checkout/custom-success-page`
- eBay authorization callback/RuName: `https://developer.ebay.com/develop/guides-v2/authorization`
