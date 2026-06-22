# Jiejing Route A Edge Domain Runbook - 2026-05-19

## Goal

Route A gives Jiejing a stable beta domain without pointing the formal domain directly at a mainland China server.

Target shape:

```text
Merchant browser
  -> https://app.<domain>
  -> overseas edge node, Caddy TLS
  -> current public staging tunnel
  -> Jiejing staging backend/frontend on 42.194.158.47
```

This does not repeat eBay OAuth and does not rerun the official eBay sync. It only prepares a stable HTTPS entrypoint.

## Current Facts

- Current public staging URL: `https://mentioned-shake-inter-critical.trycloudflare.com`
- Direct public ports on `42.194.158.47` are not open for HTTP/HTTPS from the outside.
- The stable edge should therefore proxy to the existing public tunnel until a cleaner origin link is created.
- Current official eBay packet remains `packet_5c69bcc5bf0e79ae`.
- Real platform writes remain disabled.

## 2026-05-19 HK Edge Deployment Status

- HK edge instance: `lhins-lxff3wj3`
- HK edge public IP: `43.129.205.244`
- Hostname: `VM-0-15-ubuntu`
- Caddy service: `active`
- Current mode: HTTP edge proxy to `https://mentioned-shake-inter-critical.trycloudflare.com`
- External check passed: `http://43.129.205.244/health`
- Response includes `X-Jiejing-Edge: route-a-hk`

This is an edge-only deployment. It does not migrate the app database, tokens, model keys, Tencent credentials, or SaaS secrets to the HK node.

## Files Added

- `deploy/Caddyfile.route-a-edge`
- `deploy/docker-compose.route-a-edge.yml`
- `deploy/jiejing-route-a-edge.env.example`

The Route A edge node only needs these deploy files. It must not receive:

- eBay access tokens or refresh tokens
- model provider keys
- database URLs
- Tencent SecretId/SecretKey
- SaaS session secrets

## Deployment Steps

1. Create an overseas edge node.

   Recommended beta choices:

   - Hong Kong, if latency to China sellers matters most.
   - Singapore, if Hong Kong capacity/cost is poor.
   - United States, only if buyer-side/global testing matters more than China latency.

2. Install Docker and Docker Compose on the edge node.

3. Copy only these files to the node:

   ```text
   deploy/Caddyfile.route-a-edge
   deploy/docker-compose.route-a-edge.yml
   deploy/jiejing-route-a-edge.env.example
   ```

4. Create the private env file:

   ```bash
   cp deploy/jiejing-route-a-edge.env.example deploy/jiejing-route-a-edge.env
   ```

5. Edit `deploy/jiejing-route-a-edge.env`:

   ```text
   JIEJING_EDGE_DOMAIN=app.<your-domain>
   JIEJING_EDGE_UPSTREAM_HOST=mentioned-shake-inter-critical.trycloudflare.com
   JIEJING_TLS_EMAIL=<your-ops-email>
   ```

6. Point DNS:

   ```text
   app.<your-domain> A <overseas-edge-public-ip>
   ```

7. Start the edge:

   ```bash
   docker compose -f deploy/docker-compose.route-a-edge.yml -p jiejing-route-a-edge up -d
   ```

8. Verify:

   ```bash
   curl -fsS https://app.<your-domain>/health
   curl -fsS https://app.<your-domain>/readiness/product-saas
   curl -I https://app.<your-domain>/
   ```

Expected:

- `/health` returns the Jiejing SaaS health JSON.
- `/readiness/product-saas` still says paid launch is not ready while model value proof/billing remain pending.
- Browser URL stays on `https://app.<your-domain>`.

## CORS And Frontend

Because the frontend and backend are served under the same Route A domain, browser requests should be same-origin.

Still update staging CORS to include the new domain before beta testing:

```text
JIEJING_CORS_ORIGIN=https://mentioned-shake-inter-critical.trycloudflare.com,https://app.<your-domain>
```

Then restart only the SaaS backend/worker on staging. Do not repeat OAuth and do not rerun eBay sync.

## eBay Callback

Do not change the eBay callback until the Route A URL passes `/health` and `/readiness/product-saas`.

When ready, the callback URL to register in eBay developer settings is:

```text
https://app.<your-domain>/oauth/ebay/callback
```

This is only a RuName/callback configuration change for future authorizations. It does not invalidate the existing stored read-only packet or require a fresh sync just to check current state.

## Cutover Gate

Route A is considered ready when all are true:

- DNS resolves `app.<your-domain>` to the overseas edge public IP.
- TLS is valid for `app.<your-domain>`.
- `/health` returns status `ok`.
- `/readiness/product-saas` is reachable.
- Staging CORS includes both the trycloudflare URL and Route A URL.
- eBay callback page loads at `/oauth/ebay/callback` without exposing tokens.
- Real platform writes remain disabled.

## Deferred Work

After Route A is stable:

- Replace the temporary trycloudflare upstream with a cleaner private origin path or a named Cloudflare Tunnel.
- Update eBay RuName/callback for the Route A domain.
- Keep model value proof and billing as separate blockers; Route A does not make the SaaS paid-launch ready by itself.
