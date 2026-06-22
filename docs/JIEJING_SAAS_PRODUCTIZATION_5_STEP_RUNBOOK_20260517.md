# Jiejing SaaS Productization Runbook 2026-05-17

This note records the current 5-step productization path. It keeps the project on the eBay-first AI CEO SaaS direction.

## 1. Staging page global self-check

Goal: the public page must read like a real SaaS workbench, not a demo page.

Checks:
- Home, eBay sync, standard data packet, AI CEO reports, and confirmation center must not expose Hermes.
- Merchant-facing copy must use Jiejing, AI CEO, work records, source records, standard data packets, and confirmation center.
- If a result is not real, the UI says waiting for authorization, waiting for sync, source gap, or controlled draft. It does not say fake success.
- Real eBay writes remain off.

Current code action:
- `app.js` has a product-mode copy sanitizer for legacy demo/mock wording.
- `index.html` now defaults the public shell to product/staging state labels.

## 2. eBay sync status panel

Goal: after clicking sync, the merchant can see what is happening and which resources are ready.

Required six resources:
- store profile
- account business policies
- inventory and offers
- orders and fulfillment
- finances
- taxonomy listing metadata

Current code action:
- `renderSaasEbaySyncStatusPanel()` renders overall status, source type, last sync time, standard packet id, six resource cards, and failure reasons.
- The panel is inserted in the SaaS backend workbench next to the live snapshot.

## 3. AI CEO report details

Goal: reports are not only summary cards. The merchant can expand a report and see sections, source rows, status, and confidence.

Current code action:
- `saasWorkbenchReportDetailMarkup()` adds expandable details to report cards.
- It reads existing SaaS backend `reports` payloads and keeps Runtime text sanitized.

## 4. Stable deployment channel

Goal: stop depending on repeated Tencent Cloud QR/SSH safety challenges for every deployment.

Current code action:
- `tools/jiejing_prepare_stable_deploy_key.ps1` prepares a local ed25519 deploy key.
- `deploy/install-stable-deploy-key.sh` installs the public key on the server once through Tencent Cloud WebShell or one approved SSH session.

Operator flow:
1. On Windows:
   `powershell -ExecutionPolicy Bypass -File tools\jiejing_prepare_stable_deploy_key.ps1 -Server 42.194.158.47 -User root`
2. Copy the printed `export JIEJING_DEPLOY_PUBLIC_KEY=...` command into Tencent Cloud WebShell.
3. Run:
   `cd /opt/jiejing-staging/app && bash deploy/install-stable-deploy-key.sh`
4. Test from Windows:
   `ssh -i output\deploy-keys\jiejing_staging_ed25519 root@42.194.158.47 "echo JIEJING_DEPLOY_KEY_OK"`
5. Deploy frontend changes without QR:
   `powershell -ExecutionPolicy Bypass -File tools\jiejing_deploy_frontend_staging_with_key.ps1 -Server 42.194.158.47 -User root`

## 5. Production infrastructure package

Goal: make the later cloud move explicit and repeatable.

Current code action:
- `deploy/jiejing-saas.production.env.example` defines production env boundaries.
- `deploy/docker-compose.production-pilot.yml` defines a first production-pilot shape for frontend, backend, and TLS proxy.
- `deploy/Caddyfile.production` defines same-origin HTTPS routing.

Production cloud target:
- Compute: Tencent Cloud CVM or Lighthouse for first pilot.
- Database: TencentDB for PostgreSQL.
- Queue/cache: TencentDB for Redis or cloud queue.
- Secrets: HashiCorp Vault first, then Tencent Cloud KMS/Secrets Manager if we implement the adapter.
- Logs: Tencent Cloud CLS or Sentry plus backend safe access logs.
- Domain/TLS: DNS + Caddy/SSL or Tencent Cloud certificate.
- Billing: external subscription first, then plan/quota checks in SaaS backend.

Hard boundary:
- This is not paid-SaaS ready until production OAuth, managed database, managed queue, managed secret storage, monitoring, backups, billing, and real model-backed Agent value are verified end to end.
