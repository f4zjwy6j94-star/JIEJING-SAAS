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
- Secrets: use HashiCorp Vault for this first staging OAuth loop because the repo already has a tested live Vault resolver. Tencent KMS remains an adapter contract until its managed client is implemented.

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

4. Prepare HashiCorp Vault for staging.
   - Enable KV v2 at the configured mount, default `secret`.
   - Create a policy that can read/write only the Jiejing staging keyspace.
   - Create a token for the SaaS backend with that policy.
   - Public staging uses file-backed Vault storage, not `vault server -dev`.
   - Start the compose profile, then run:
     `JIEJING_VAULT_PATCH_ENV=true sh deploy/staging-vault-init-unseal.sh`.
   - Do not paste Vault token values into chat or committed files.

5. Prepare eBay developer settings.
   - Set the RuName/callback to `https://staging.<domain>/oauth/ebay/callback`.
   - Use read-only scopes only.
   - Keep real platform writes disabled in Jiejing.

## Host Deployment Tasks

1. Copy the repo or upload the generated staging bundle to the host.

```bash
cd /opt/jiejing-staging
unzip jiejing-public-staging-*.zip
```

2. Create the private staging env file.

```bash
mkdir -p /opt/jiejing-staging/private
cp deploy/jiejing-saas.staging-oauth.env.example /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env
chmod 600 /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env
```

3. Fill these values manually on the host.

```text
JIEJING_SAAS_SESSION_SECRET
JIEJING_CORS_ORIGIN
JIEJING_VAULT_ADDR
JIEJING_VAULT_TOKEN
JIEJING_EBAY_CLIENT_ID
JIEJING_EBAY_RU_NAME
JIEJING_EBAY_CLIENT_SECRET
```

Keep the real file under `/opt/jiejing-staging/private/`. The `deploy/`
directory should only contain `jiejing-saas.staging-oauth.env.example`.

4. Start public staging.

```bash
JIEJING_PUBLIC_HTTP_PORT=80 docker compose -f deploy/docker-compose.public-staging.yml up -d --build
```

5. Verify health.

```bash
curl -fsS http://127.0.0.1/health
curl -fsS https://staging.<domain>/health
```

6. Run the operator flow from a machine that can reach the staging URL.

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
