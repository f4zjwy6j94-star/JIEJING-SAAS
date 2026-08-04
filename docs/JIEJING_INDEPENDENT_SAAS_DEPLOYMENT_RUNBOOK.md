# Jiejing Independent SaaS Deployment Runbook

This runbook is for running Jiejing without Hermes as a required dependency.
It is not a claim that production is ready today. The current repo can run the
independent SaaS backend and owned Runtime locally, while real cloud drivers and
live platform adapters are still gated.

## Current Independent Chain

User browser
-> Jiejing frontend
-> Jiejing SaaS backend
-> Jiejing worker
-> Jiejing Runtime
-> Provider Jobs
-> Confirmation Center
-> ExecutionService
-> future eBay / sourcing / logistics / media adapters

Hermes is not required in this chain. By default `JIEJING_ALLOW_HERMES_ADAPTERS`
is false and the SaaS backend only accepts:

- `mock`
- `jiejing-local`
- `jiejing-llm`
- `jiejing-deepseek`

## Staging Bootstrap

Run the local pre-cloud gate before touching a public domain:

```powershell
python tools\jiejing_precloud_deployment_gate.py
```

Expected local status:

```text
status=pass_local_checks
ready_for_public_staging_code_handoff=true
ready_for_paid_commercial_launch=false
```

If `external_blockers` includes `docker_cli_not_available_on_this_machine`,
the code gate can still pass, but the actual staging host or operator machine
must provide Docker or an equivalent deployment runner before starting compose.

For a Tencent Cloud handoff, use:

```text
deploy/tencentcloud-public-staging-checklist.md
deploy/bootstrap.public-staging.ubuntu.sh
```

If the code is moved to the host by upload instead of Git, create a secret-safe
bundle:

```powershell
python tools\jiejing_prepare_public_staging_bundle.py
```

The bundle excludes filled env files, SQLite databases, logs and local output.

For iterative code-only staging updates after the app has already been placed
under `/opt/jiejing-staging/app`, use the whitelisted patch path instead of
copying the whole project:

```powershell
python tools\jiejing_precloud_deployment_gate.py
python tools\jiejing_staging_deploy.py --patch output\jiejing-staging-patch-YYYYMMDD-HHMMSS.zip
```

The patch script backs up only whitelisted code/config files, rebuilds the SaaS
image, restarts `jiejing-saas`, `jiejing-worker` and `jiejing-frontend`, and
does not remove Docker volumes, Vault files, SQLite data or secrets.

If Tencent Cloud shows a QR-code security login during batch SSH, the deploy
tool must stop with `deploy_channel_ready=false`. Fix the server deploy channel
first by installing the stable public key from
`deploy/tencentcloud-install-jiejing-ssh-key.sh` through Tencent Cloud
OrcaTerm/web terminal, then rerun:

```powershell
python tools\jiejing_deploy_channel_doctor.py --host 42.194.158.47 --user root --timeout 8
```

1. Copy `deploy/jiejing-saas.env.example` to a private environment file.
2. Replace placeholder values with secret-manager references, not raw secrets in Git.
3. Build the container:

```powershell
docker compose -f deploy/docker-compose.staging.yml build
```

4. Run readiness first:

```powershell
docker compose -f deploy/docker-compose.staging.yml run --rm jiejing-saas python tools/jiejing_saas_backend_cli.py readiness --host 0.0.0.0 --port 8788 --db /data/saas.sqlite --runtime-db /data/runtime.sqlite --output-root /data/output
```

5. Start only after blockers are expected and understood:

```powershell
docker compose -f deploy/docker-compose.staging.yml up
```

## Required Before Real Merchants

- Managed Postgres deployed, migrated and rehearsed with staging data import.
- Redis/cloud queue deployed with the standalone `jiejing-worker` service and
  dead-letter stream enabled.
- Tencent KMS / Aliyun KMS / Vault live resolver implemented.
- eBay OAuth callback writes refresh token to KMS, not SQLite.
- eBay read-only adapter reads live store/listing/order/fee/policy data.
- Provider jobs for 1688, logistics, search and media use backend-only credentials.
- ExecutionService remains the only write boundary.
- Real writes stay disabled until sandbox publish/revise/refund tests pass.

## eBay Read-Only Connection Path

The independent SaaS now has a backend-only eBay read client for official GET
routes. It is designed for reading store context, listings, orders, fees,
business policies and taxonomy facts into sanitized data packets for Runtime.
It does not publish, revise, refund, change ads, change policies or place
procurement orders.

For a local smoke test only, a short-lived access token can be supplied to the
backend process in `local_dev`:

```powershell
$env:JIEJING_EBAY_READ_ONLY_LIVE="true"
$env:JIEJING_EBAY_ACCESS_TOKEN="<short-lived-access-token>"
```

That path is only for local verification because the token expires and should
not become a product dependency. In staging and production, do not configure
`JIEJING_EBAY_ACCESS_TOKEN`, `EBAY_ACCESS_TOKEN`, `JIEJING_EBAY_REFRESH_TOKEN`
or `EBAY_REFRESH_TOKEN`. The backend intentionally blocks those env-token paths
in production-like environments.

The staging/production path is:

```powershell
$env:JIEJING_EBAY_READ_ONLY_LIVE="true"
$env:JIEJING_EBAY_TOKEN_REFRESH_LIVE="true"
$env:JIEJING_EBAY_CLIENT_ID="<ebay-app-id-from-deployment-secret>"
$env:JIEJING_EBAY_CLIENT_SECRET="<client-secret-from-deployment-secret>"
$env:JIEJING_VAULT_PROVIDER="tencent_ssm"
$env:JIEJING_VAULT_ENABLED="true"
```

The seller refresh token is created by the eBay OAuth callback and stored behind
a `secret_ref` in Vault/KMS. The SaaS backend resolves that `secret_ref`,
refreshes a short-lived access token, calls official eBay APIs, redacts raw
responses, persists only normalized data packets, and passes sanitized facts to
Runtime. Frontend and agents never receive tokens.

### First Real Staging OAuth Loop

Use this path for the first real seller authorization. Do not use the legacy
Hermes bridge for this validation.

1. Deploy the SaaS backend behind a real staging URL, for example:

```text
https://staging.jiejing.example
```

2. Configure the eBay developer portal RuName/callback so the seller browser
returns to:

```text
https://staging.jiejing.example/oauth/ebay/callback
```

3. The active staging contract uses three private env files in canonical
`managed -> secret -> postgres` order:

```text
deploy/jiejing-saas.tencent-managed.env.example
deploy/jiejing-saas.staging-oauth.env.example
deploy/jiejing-saas.postgres-localqueue.env.example
```

This supersedes the older single-file OAuth staging instruction. The current
managed source selects the implemented Tencent SSM resolver:

```powershell
$env:JIEJING_VAULT_PROVIDER="tencent_ssm"
$env:JIEJING_VAULT_LIVE_RESOLVE_ENABLED="true"
$env:JIEJING_EBAY_OAUTH_EXCHANGE_LIVE="true"
$env:JIEJING_EBAY_TOKEN_REFRESH_LIVE="true"
$env:JIEJING_EBAY_READ_ONLY_LIVE="true"
$env:JIEJING_ENABLE_HERMES_EBAY_BRIDGE="false"
```

HashiCorp Vault remains a deliberate fallback profile. If it is selected, keep
its address/token only in the secret source and keep provider/enabled state only
in the managed source; never configure both providers in different env files.

When the HashiCorp fallback is deliberately selected, public staging must not
run Vault in `vault server -dev` mode. The public staging compose profile uses
`deploy/vault.public-staging.hcl` with file-backed storage in the
`jiejing_public_staging_vault_data` Docker volume. After the Vault container is
first created, initialize and unseal it from the server:

```bash
cd /opt/jiejing-staging/app
JIEJING_VAULT_PATCH_ENV=true sh deploy/staging-vault-init-unseal.sh
docker compose -f deploy/docker-compose.public-staging.yml up -d --force-recreate jiejing-saas
```

The script writes initialization material under `/opt/jiejing-staging/private/`
with `0600` permissions and patches only the private staging env file when
`JIEJING_VAULT_PATCH_ENV=true`. Do not copy those files into the repo or chat.
If the Vault container restarts later, run the same script again without
recreating OAuth; it will unseal the existing file-backed Vault.

Start this backend-only validation profile from three sibling private files.
The copy commands below are initialization examples only; never overwrite an
existing private file:

```powershell
New-Item -ItemType Directory -Force ..\private | Out-Null
if (-not (Test-Path ..\private\tencent-managed.env)) { Copy-Item deploy\jiejing-saas.tencent-managed.env.example ..\private\tencent-managed.env }
if (-not (Test-Path ..\private\jiejing-saas.staging-oauth.env)) { Copy-Item deploy\jiejing-saas.staging-oauth.env.example ..\private\jiejing-saas.staging-oauth.env }
if (-not (Test-Path ..\private\postgres-localqueue.env)) { Copy-Item deploy\jiejing-saas.postgres-localqueue.env.example ..\private\postgres-localqueue.env }
python tools\jiejing_runtime_env_overlap_guard.py check `
  --compose deploy\docker-compose.oauth-staging.yml `
  --managed-env ..\private\tencent-managed.env `
  --secret-env ..\private\jiejing-saas.staging-oauth.env `
  --postgres-env ..\private\postgres-localqueue.env `
  --required-runtime-service jiejing-saas `
  --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python tools\jiejing_runtime_env_overlap_guard.py migrate `
  --compose deploy\docker-compose.oauth-staging.yml `
  --managed-env ..\private\tencent-managed.env `
  --secret-env ..\private\jiejing-saas.staging-oauth.env `
  --postgres-env ..\private\postgres-localqueue.env `
  --required-runtime-service jiejing-saas `
  --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker compose -f deploy/docker-compose.oauth-staging.yml build
docker compose -f deploy/docker-compose.oauth-staging.yml up
```

Both guard reports are value-free. `migrate` is a dry-run unless an operator
separately supplies the explicit apply flag and confirmation; do not use apply
in this OAuth startup path. Stop before the first Compose operation when either
guard command returns nonzero.

That backend-only compose file is useful for internal API validation, but the
first public staging URL should normally use the same-origin frontend/proxy
profile:

```powershell
docker compose -f deploy/docker-compose.public-staging.yml build
docker compose -f deploy/docker-compose.public-staging.yml up
```

`deploy/docker-compose.public-staging.yml` exposes Nginx as the public entrypoint
and keeps the SaaS backend on the Docker network. Set `JIEJING_PUBLIC_HTTP_PORT=80`
when the host binds public HTTP directly, or keep the default `8080` behind a
cloud load balancer/reverse proxy. The eBay callback remains:

```text
https://staging.jiejing.example/oauth/ebay/callback
```

Set `JIEJING_CORS_ORIGIN` to the exact public staging origin, for example
`https://staging.jiejing.example`; do not use `*` in staging or production.

These staging profiles intentionally use the SaaS backend's current
SQLite/local-worker runtime inside a Docker volume. They are for proving the
first real eBay OAuth and official read-only packet loop only. They are not the
final paid SaaS deployment shape; managed Postgres and a cloud queue remain
required before real merchants.

`deploy/docker-compose.staging-infra.yml` is the next profile after public
OAuth staging. It starts Postgres, Redis, migration, `jiejing-saas`,
`jiejing-worker` and the frontend. Use it only after the code-only staging loop
is stable and a cutover rehearsal has been reviewed:

```powershell
python tools\jiejing_infra_cutover_rehearsal.py --sqlite-db output\jiejing-saas-backend\saas.sqlite
docker compose -f deploy/docker-compose.staging-infra.yml up -d --build
```

The worker command consumes queued jobs in the background:

```powershell
python tools\jiejing_worker_cli.py --db /data/saas.sqlite --runtime-db /data/runtime.sqlite --output-root /data/output run-loop --idle-sleep 2 --json-lines
```

This removes the staging dependency on manually calling `/workers/run-next`.

Contract note: this is not the final paid SaaS deployment.

If the frontend is served from the same staging origin as the SaaS backend, it
will infer that origin automatically. If the frontend is served separately,
configure the API base by one of these supported frontend injection points:

```html
<meta name="jiejing-saas-api-base" content="https://staging.jiejing.example" />
```

```javascript
window.JIEJING_CONFIG = {
  saasApiBase: "https://staging.jiejing.example",
  runtimeApiBase: "https://runtime-staging.jiejing.example"
};
```

For local operator testing, URL query or localStorage overrides are also
supported: `?saasApiBase=https://staging.jiejing.example`.

The frontend will only auto-create the local demo SaaS session on `file://`,
`localhost`, `127.0.0.1`, or `::1`. On a public/staging origin it requires an
existing SaaS session and will show a public auth gate instead of silently
creating `demo@jiejing.local`. For a short operator-only staging test, the demo
bootstrap can be explicitly enabled, but do not enable this for merchant-facing
public pages:

```html
<meta name="jiejing-saas-demo-bootstrap" content="true" />
```

```javascript
window.JIEJING_CONFIG = {
  saasDemoBootstrapEnabled: true
};
```

4. Check the merged staging process environment without printing secrets:

```powershell
docker compose -f deploy/docker-compose.public-staging.yml exec -T jiejing-saas `
  python tools/jiejing_staging_ebay_oauth_readonly_flow.py check-env
```

5. Check the running backend guardrails before seller OAuth:

```powershell
python tools/jiejing_staging_ebay_oauth_readonly_flow.py doctor `
  --base-url https://staging.jiejing.example `
  --email staging-oauth@jiejing.local `
  --register-if-needed
```

Expected:

```text
DOCTOR_STATUS=ready_for_oauth_prepare
ENVIRONMENT=staging
VAULT_RESOLVER_LIVE=True
EBAY_HTTP_CLIENT_STATUS=live_ready
EBAY_LIVE_ADAPTER_STATUS=live_ready
REAL_PLATFORM_WRITES_ENABLED=False
```

6. Generate a seller read-only authorization URL:

```powershell
python tools/jiejing_staging_ebay_oauth_readonly_flow.py prepare `
  --base-url https://staging.jiejing.example `
  --email staging-oauth@jiejing.local `
  --register-if-needed
```

Open the printed `AUTHORIZATION_URL` in the seller browser. This is the only
human-login step. The browser should return to the staging callback endpoint;
the callback exchanges the code in the backend and writes only the seller
refresh token through the Vault resolver.

7. Confirm that callback storage completed and the store is ready to sync:

```powershell
python tools/jiejing_staging_ebay_oauth_readonly_flow.py status `
  --base-url https://staging.jiejing.example `
  --email staging-oauth@jiejing.local
```

Expected:

```text
OAUTH_LATEST_STATUS=callback_exchange_completed
PREFLIGHT_STATUS=ready_for_official_read
CAN_QUEUE_SYNC=True
TOKEN_MODE=backend_jiejing_secret_ref_resolver
```

8. Run the official read-only sync and verify a sanitized data packet:

```powershell
python tools/jiejing_staging_ebay_oauth_readonly_flow.py sync `
  --base-url https://staging.jiejing.example `
  --email staging-oauth@jiejing.local `
  --run-mode local_worker_now
```

Expected:

```text
LIVE_REQUEST_PERFORMED=True
DATA_PACKET_ID=packet_...
SOURCE_MODE=official_api
REAL_PLATFORM_WRITES_ENABLED=False
SECRET_EXPOSED=False
```

The tool writes sanitized summaries under:

```text
output/jiejing-saas-backend/staging-ebay-oauth-readonly/
```

### Product-Level Sync Endpoint

Before sync, the frontend or operator can ask the backend for one unified answer
about whether official eBay read-only data can be pulled:

```http
POST /stores/{store_id}/ebay-read-only/credential-preflight
```

The response returns `status`, `token_mode`, `blocked_by` and
`merchant_next_step`. It never returns access tokens, refresh tokens, client
secrets, cookies or Authorization headers. This same preflight is embedded in
the sync endpoint below, so a blocked sync is visible to the merchant instead of
looking like a dead button.

For product code, prefer the single merchant-facing sync endpoint instead of
making the frontend assemble probe plans and route requests:

```http
POST /stores/{store_id}/ebay-read-only/sync
```

Typical body:

```json
{
  "resources": [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata"
  ],
  "run_mode": "queued"
}
```

If credentials or live-read switches are missing, the endpoint creates a
merchant-visible blocked task and returns `merchant_next_step`; it does not
queue a worker that will silently spin. If the backend is properly authorized,
it queues the read job and can optionally run it inline in local development
with `run_mode: "inline"`.

Local operator check:

```powershell
python tools/jiejing_ebay_credential_preflight.py
```

It writes sanitized JSON and Markdown to
`output/jiejing-saas-backend/ebay-credential-preflight/` and prints only
status, token mode and blocker names.

## Deployment Guardrails

- Frontend never receives raw token, password, API key, refresh token or cookie.
- Runtime receives sanitized packets, not platform credentials.
- Agents cannot call eBay write APIs.
- Publish, refund, payment, ad budget, policy edit and sensitive buyer promises require confirmation.
- Repeated execution uses idempotency keys and duplicate-prevention hashes.

## Current Blockers

- This repo still uses SQLite/local worker for the local MVP.
- Postgres/Redis/KMS are described by contracts but not fully wired.
- Real eBay write adapter is contract-only.
- 1688 and Orange Connex production adapters are not implemented.
- Media generation requires a production queue, quota guard and review workflow.
