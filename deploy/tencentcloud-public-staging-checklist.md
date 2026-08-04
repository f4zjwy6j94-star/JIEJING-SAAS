# Jiejing Public Staging Checklist on Tencent Cloud

This checklist is for the first real public staging validation:

seller OAuth -> backend token exchange -> Vault secret_ref -> official eBay read-only sync -> standard platform data packet.

It is not the final paid SaaS production deployment.

## Recommended Tencent Cloud Shape

Use the smallest setup that proves the real loop without pretending to be production:

- Compute: Tencent Cloud Lighthouse with a Docker application image, or CVM Ubuntu if Lighthouse is not available in the selected account/region.
- Region: Hong Kong or Singapore is usually simpler for early external staging. If you deploy in Mainland China, confirm ICP filing requirements before pointing a public domain at the server.
- Network: one public IPv4, inbound `80` and `443` only for public traffic, SSH restricted to your own IP.
- HTTPS: use a Tencent Cloud SSL certificate or another certificate managed by the fronting reverse proxy/load balancer.
- DNS: use DNSPod or your current DNS provider to point `staging.<domain>` to the staging server or load balancer.
- Secrets: use the current backend Tencent SSM resolver selected by `tencent-managed.env`. Vault enable/provider state belongs to that managed source; eBay/model/media/session secret material remains in the backend-only secret source.

Official reference links:

- Tencent Cloud Lighthouse: https://intl.cloud.tencent.com/product/lighthouse
- Tencent Cloud CVM: https://intl.cloud.tencent.com/products/cvm
- Tencent Cloud SSL Certificates: https://intl.cloud.tencent.com/product/ssl
- Tencent Cloud DNSPod: https://www.tencentcloud.com/document/product/1295/76654

## Cloud Console Tasks

1. Create a staging host.
   - Preferred: Lighthouse with Docker image.
   - Alternative: CVM Ubuntu 22.04/24.04, then run `deploy/bootstrap.public-staging.ubuntu.sh`.
   - Suggested early size: 2 vCPU / 4 GB RAM / 40 GB disk.

2. Configure firewall or security group.
   - Allow `80/tcp` from public internet.
   - Allow `443/tcp` from public internet once HTTPS is configured.
   - Allow `22/tcp` only from your own current IP.
   - Do not expose backend port `8788` publicly.

3. Configure domain and HTTPS.
   - Create DNS record: `staging.<domain>` -> public IP or load balancer.
   - Configure certificate for `staging.<domain>`.
   - eBay callback URL must be:

```text
https://staging.<domain>/oauth/ebay/callback
```

4. Prepare the backend secret resolver for staging.
   - Keep `JIEJING_VAULT_ENABLED` and `JIEJING_VAULT_PROVIDER` only in `tencent-managed.env`.
   - Keep Tencent region, SSM keyspace and managed resolver evidence in that same managed file.
   - Keep credentials and provider secrets backend-only; never paste them into chat, logs or committed files.
   - If an operator deliberately selects the HashiCorp Vault fallback, use the file-backed profile and its existing init/unseal runbook; do not mix both provider selections across env files.

5. Prepare eBay developer settings.
   - Set the RuName/callback to `https://staging.<domain>/oauth/ebay/callback`.
   - Use read-only scopes only.
   - Keep real platform writes disabled in Jiejing.

## Host Deployment Tasks

1. Copy the repo or upload the generated staging bundle into the active app directory.

```bash
mkdir -p /opt/jiejing-staging/app
cd /opt/jiejing-staging/app
unzip jiejing-public-staging-*.zip
```

2. Run the bootstrap from the extracted app tree. This initializes missing env
   files without overwriting existing private values, validates strict modes,
   and runs the value-free ownership check when the bundle is complete.

```bash
cd /opt/jiejing-staging/app
bash deploy/bootstrap.public-staging.ubuntu.sh
```

The canonical load order is `managed -> secret -> postgres`. This supersedes the older single-file OAuth staging instruction.

If the bootstrap cannot copy templates automatically, initialize only missing
files manually and never overwrite an existing private env:

```bash
install -d -m 0700 /opt/jiejing-staging/private
test -e /opt/jiejing-staging/private/tencent-managed.env || install -m 0600 deploy/jiejing-saas.tencent-managed.env.example /opt/jiejing-staging/private/tencent-managed.env
test -e /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env || install -m 0600 deploy/jiejing-saas.staging-oauth.env.example /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env
test -e /opt/jiejing-staging/private/postgres-localqueue.env || install -m 0600 deploy/jiejing-saas.postgres-localqueue.env.example /opt/jiejing-staging/private/postgres-localqueue.env
chmod 600 /opt/jiejing-staging/private/tencent-managed.env /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env /opt/jiejing-staging/private/postgres-localqueue.env
stat -c '%a %n' /opt/jiejing-staging/private/tencent-managed.env /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env /opt/jiejing-staging/private/postgres-localqueue.env
```

3. Fill placeholders through the backend-only operator path.

```text
tencent-managed.env: Tencent region/SSM settings and managed Vault evidence
jiejing-saas.staging-oauth.env: session, eBay, model, search, media and payment-provider secrets
postgres-localqueue.env: PostgreSQL and queue connection URLs
```

`JIEJING_SAAS_ENV`, CORS and other stable public route settings remain Compose
static configuration, not secret-file values. Keep all three real files under
`/opt/jiejing-staging/private/`; `deploy/` contains examples only.

4. Before any build, copy or container operation, run the ownership check and
   migration dry-run. Neither command changes private files.

```bash
cd /opt/jiejing-staging/app
sudo -n python3 tools/jiejing_runtime_env_overlap_guard.py check \
  --compose deploy/docker-compose.public-staging.yml \
  --managed-env /opt/jiejing-staging/private/tencent-managed.env \
  --secret-env /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env \
  --postgres-env /opt/jiejing-staging/private/postgres-localqueue.env \
  --json
sudo -n python3 tools/jiejing_runtime_env_overlap_guard.py migrate \
  --compose deploy/docker-compose.public-staging.yml \
  --managed-env /opt/jiejing-staging/private/tencent-managed.env \
  --secret-env /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env \
  --postgres-env /opt/jiejing-staging/private/postgres-localqueue.env \
  --json
```

5. Start public staging only after both commands pass.

```bash
cd /opt/jiejing-staging/app
JIEJING_PUBLIC_HTTP_PORT=80 docker compose -f deploy/docker-compose.public-staging.yml up -d --build
```

6. Verify health.

```bash
curl -fsS http://127.0.0.1/health
curl -fsS https://staging.<domain>/health
```

7. Validate the merged env shape without printing values, then run the operator
   flow from a machine that can reach the staging URL.

```bash
docker compose -f deploy/docker-compose.public-staging.yml exec -T jiejing-saas \
  python tools/jiejing_staging_ebay_oauth_readonly_flow.py check-env
```

```bash
python tools/jiejing_staging_ebay_oauth_readonly_flow.py doctor \
  --base-url https://staging.<domain> \
  --email staging-oauth@jiejing.local \
  --register-if-needed

python tools/jiejing_staging_ebay_oauth_readonly_flow.py prepare \
  --base-url https://staging.<domain> \
  --email staging-oauth@jiejing.local \
  --register-if-needed

python tools/jiejing_staging_ebay_oauth_readonly_flow.py status \
  --base-url https://staging.<domain> \
  --email staging-oauth@jiejing.local

python tools/jiejing_staging_ebay_oauth_readonly_flow.py sync \
  --base-url https://staging.<domain> \
  --email staging-oauth@jiejing.local \
  --run-mode local_worker_now
```

## Do Not Change These For First Staging

```text
JIEJING_ENABLE_REAL_PLATFORM_WRITES=false
JIEJING_ENABLE_HERMES_EBAY_BRIDGE=false
JIEJING_EBAY_ACCESS_TOKEN=
JIEJING_EBAY_REFRESH_TOKEN=
```

Runtime/Agents must receive only sanitized standard data packets. They must not receive eBay tokens.
