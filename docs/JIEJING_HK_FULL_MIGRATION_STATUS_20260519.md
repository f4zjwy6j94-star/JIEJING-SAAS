# Jiejing HK Full Migration Status - 2026-05-19

## Goal

Move the Jiejing staging compute path from Guangzhou Lighthouse to Hong Kong Lighthouse without losing data or weakening the SaaS resource boundaries.

## Current Facts

- Guangzhou Lighthouse `42.194.158.47` has been retired after the HK cutover and final data check.
- Hong Kong Lighthouse: `43.129.205.244`, `jiejing-route-a-edge-hk`.
- HK IP traffic has been cut over to the HK local SaaS containers through host Caddy -> `127.0.0.1:18080` -> Docker frontend -> backend.
- The current Cloudflare staging route is served from the HK host: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`.
- Real platform writes remain disabled.
- eBay OAuth and official read-only sync were not repeated.

## Final Guangzhou Retirement

Completed on 2026-05-19 after user confirmation:

- Guangzhou Lighthouse `lhins-bulffuz3` / `42.194.158.47`: refund/return submitted.
- Old CVM `ins-01hsr6ti` / `159.75.102.10`: released from recycle bin.
- Guangzhou PostgreSQL `postgres-8yuuxdqb`: destroyed and removed from recycle bin.
- Guangzhou Redis `crs-bueo6vz7`: destroyed and removed from recycle bin.
- Guangzhou CCN `ccn-3kgturgn`: detached and deleted.
- Guangzhou VPC `vpc-njexozrh` / `Default-VPC`: deleted after dependencies were cleared.

Kept intentionally: COS, CLS, SSM, KMS, active HK resources, HK Docker volumes, and CVM snapshot evidence.

Final HK verification after retirement:

- HTTPS tunnel health: `ok`.
- HK public IP health: `ok`.
- `real_platform_writes_enabled=false`.
- `/readiness` still reports `platform_data_packets=6`, `reports=44`, `confirmations=36`, `stores=3`, `platform_connections=6`, `secret_refs=6`, and `audit_logs=315`.
- Official packet `packet_5c69bcc5bf0e79ae` remains present with all six eBay official resource sections.

## Migrated To Hong Kong

- App directory copied to `/opt/jiejing-staging/app`.
- Private runtime config copied to `/opt/jiejing-staging/private`.
- Docker volumes copied:
  - `deploy_jiejing_public_staging_data`
  - `deploy_jiejing_public_staging_vault_data`
- Docker and Compose are installed on the HK host.
- HK local containers were built successfully and are running.
- HK PostgreSQL `postgres-b6chkvaj` is the active app database through the restricted public database endpoint.
- HK local Redis container `jiejing-hk-redis` is the active queue/cache endpoint because TencentDB Redis public/private access is currently blocked for this Lighthouse topology.
- Host Caddy is in `route-a-hk-local` mode and reverses public HTTP traffic to the local HK frontend.
- HK temporary Cloudflare tunnel is running as `jiejing-cloudflared-hk`.
- HK temporary tunnel URL: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`.
- Guangzhou `jiejing-cloudflared` and old app containers have been stopped, not deleted.

## Post-Cutover Verification

Verified on 2026-05-19 after HK cutover:

- Public `GET http://43.129.205.244/` returns the Jiejing frontend.
- Public response header includes `X-Jiejing-Edge: route-a-hk-local`.
- Public `GET http://43.129.205.244/health` returns `status=ok`, `environment=staging`, and `real_platform_writes_enabled=false`.
- Public `GET https://individually-buffalo-prescribed-blocking.trycloudflare.com/health` returns `status=ok`, `environment=staging`, and `real_platform_writes_enabled=false`.
- The HK tunnel returns `Access-Control-Allow-Origin: https://individually-buffalo-prescribed-blocking.trycloudflare.com`.
- Old Guangzhou tunnel `https://mentioned-shake-inter-critical.trycloudflare.com/health` returned Cloudflare `530` after the Guangzhou tunnel was stopped.
- Public `POST http://43.129.205.244/auth/demo-session` returns `403 Forbidden`.
- Active app database points at HK PostgreSQL, database `jiejing`.
- Active queue URL points at `redis://jiejing-hk-redis:6379/0`.
- Database verification from the HK backend container:
  - public tables: `17`
  - `platform_data_packets`: `6`
  - `reports`: `44`
  - `confirmations`: `36`
  - `packet_5c69bcc5bf0e79ae`: present
- Redis verification from the HK backend container:
  - `PING`: `PONG`
  - `DBSIZE`: `1`
- Product readiness:
  - `production_ready=false`
  - `beta_ready=false`
  - `can_accept_real_customers=false`
  - `blocker_count=1`
  - remaining blocker: live model-backed `model_value_proof`

## Active HK Resources

- HK Lighthouse: `43.129.205.244`
- HK PostgreSQL: `postgres-b6chkvaj`
- HK Redis managed instance: `crs-b119e0fy` exists but is not active in the app path due Tencent WAN/CCN restrictions.
- HK local Redis container: `jiejing-hk-redis`, active app queue/cache endpoint.
- HK VPC: `vpc-bkg6pc8k`
- HK subnets:
  - `subnet-nqepis1v`, Zone 1
  - `subnet-ghylmrft`, Zone 2
  - `subnet-ipwf677z`, Zone 3
- HK database security group: `sg-ppc6cluh`

## Runtime Config Notes

- `JIEJING_DATABASE_URL` points at HK PostgreSQL.
- `JIEJING_QUEUE_URL` points at HK local Redis.
- `JIEJING_TENCENT_REGION` remains `ap-guangzhou` because SSM/KMS/CLS/COS resources are still in Guangzhou.
- `JIEJING_COS_REGION` remains `ap-guangzhou`.
- `JIEJING_CLS_REGION` remains `ap-guangzhou`.
- Database passwords, eBay tokens, model keys, and Tencent SecretKeys are not recorded in this document.

## Current Cutover Boundary

The HK IP route is now local-HK. The old trycloudflare public staging URL is still served by the Guangzhou source unless separately moved.

As of the later 2026-05-19 cutover, the public staging tunnel was moved to HK using a new temporary trycloudflare URL:

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com
```

The old Guangzhou tunnel is intentionally stopped. It cannot be preserved as the same hostname because it was an ephemeral trycloudflare hostname, not a named Cloudflare tunnel or a real domain.

Do not release Guangzhou yet. Keep it running until:

1. HK IP route is observed for 24-72 hours.
2. A real domain/TLS/CORS/callback route is selected and verified, or the temporary HK Cloudflare tunnel is accepted as staging-only.
3. Backup and restore evidence remains available after the HK cutover.
4. A final data delta check confirms no new records need to be copied from Guangzhou.

## Historical Guangzhou Stop State

Before final retirement, these containers were stopped on Guangzhou Lighthouse:

- `jiejing-cloudflared`
- `deploy-jiejing-worker-1`
- `deploy-jiejing-saas-1`
- `deploy-jiejing-frontend-1`
- `deploy-jiejing-vault-1`

The user accepted that the old `mentioned-shake...trycloudflare.com` staging URL is retired, and the Guangzhou Lighthouse was released afterward.

Before releasing any managed Guangzhou database resource, create or verify an out-of-band backup and confirm the HK counts still match:

- tables: `17`
- `platform_data_packets`: `6`
- `reports`: `44`
- `confirmations`: `36`
- `packet_5c69bcc5bf0e79ae`: present

## Historical Blocker - Resolved

The following was the blocker before HK PostgreSQL was provisioned and the app was switched to the HK data path. It is kept as historical context only.

The HK host could not reach the old managed database resources because they were private Guangzhou addresses:

- PostgreSQL target: `172.16.0.12:5432`
- Redis target: `172.16.0.15:6379`

Connectivity check:

- Guangzhou host to PostgreSQL: OK
- Guangzhou host to Redis: OK
- Hong Kong host to PostgreSQL: FAIL
- Hong Kong host to Redis: FAIL

Tencent Cloud Lighthouse inner-network documentation states that Lighthouse can use CCN for internal access to cloud databases, but Lighthouse does not support cross-border private interconnection through CCN. That prevents HK Lighthouse from privately reaching Guangzhou private database addresses.

## Historical Pre-Provision Inventory

This was the read-only Tencent Cloud API inventory before HK PostgreSQL/Redis resources were created:

- Guangzhou PostgreSQL: `postgres-8yuuxdqb`, status `running`, region `ap-guangzhou`, VPC `vpc-njexozrh`, subnet `subnet-dz8fnm7u`.
- Guangzhou Redis: `crs-bueo6vz7`, status `2`, region id `1`, private endpoint `172.16.0.15:6379`.
- Hong Kong PostgreSQL: none found.
- Hong Kong Redis: none found.

## Historical Source Data Size Snapshot

Read-only size check from the current Guangzhou app path:

- PostgreSQL database: `jiejing`
- PostgreSQL size: about `12 MB`
- PostgreSQL public tables: `17`
- Redis DB size: `1` key
- Redis used memory: about `66.57 MB`

The data volume is small enough for a controlled dump/restore migration, but the target HK managed PostgreSQL/Redis instances do not exist yet.

## Historical Resource Impact

Moving only the Lighthouse compute host does not delete or modify:

- TencentDB PostgreSQL
- TencentDB Redis
- CLS
- KMS/SSM
- COS backup bucket

However, after the app runs in Hong Kong, it must have a valid path to PostgreSQL and Redis. CLS, KMS/SSM, and COS use Tencent public APIs and are not blocked by the same private-network issue.

## Historical Options

### Recommended: HK Managed PostgreSQL + HK Managed Redis

Create new managed PostgreSQL and Redis instances in Hong Kong, restore the current data, point HK app config to the new private endpoints, validate, then cut traffic.

Pros:

- Preserves the managed SaaS architecture.
- Allows Guangzhou Lighthouse to be retired after observation.
- Avoids public database exposure.

Cons:

- Requires buying or provisioning HK PostgreSQL and HK Redis.
- Requires same-region private-network setup between HK Lighthouse and the HK managed databases.

### Faster But Weaker: Expose Guangzhou PostgreSQL/Redis To HK IP

Enable public access on the Guangzhou PostgreSQL/Redis and restrict security rules to the HK Lighthouse IP `43.129.205.244`.

Pros:

- Fastest way to retire Guangzhou Lighthouse while keeping current databases.
- No database migration needed.

Cons:

- Database remains in Guangzhou.
- Public database exposure is weaker than private networking.
- Redis public access has more operational risk.

### Not Recommended For Production: Local PostgreSQL/Redis On HK Lighthouse

Run PostgreSQL and Redis inside the HK Lighthouse and restore data there.

Pros:

- Fast and cheap.
- Avoids Tencent managed-network setup.

Cons:

- Weakens the current managed SaaS architecture.
- Backups, monitoring, restore, scaling, and failure recovery become worse.

## Historical Safe State

HK backend and worker containers were stopped after the connectivity failure to avoid repeated database retry loops.

Running on HK:

- `deploy-jiejing-frontend-1`
- `deploy-jiejing-vault-1`
- Host Caddy route-a edge proxying to the existing staging upstream

Stopped on HK until database networking is resolved:

- `deploy-jiejing-saas-1`
- `deploy-jiejing-worker-1`

## Historical Next Step

Provision HK managed PostgreSQL and HK managed Redis, then perform:

1. Fresh PostgreSQL dump from Guangzhou.
2. Restore into HK PostgreSQL.
3. Redis export/restore or queue-safe reset if the single Redis key is non-critical.
4. Update HK private runtime config to HK endpoints.
5. Start HK backend and worker.
6. Validate health/readiness/resource drivers.
7. Switch HK Caddy from old upstream to local HK app.
8. Observe 24-72 hours.
9. Stop Guangzhou Lighthouse.
10. Observe again before release/refund.

## Purchase Page Follow-up

The first HK database purchase attempt exposed two console blockers:

- PostgreSQL purchase page already selected HK and `jiejing-hk-vpc`, but checkout was blocked because no security group was available/selected.
- Redis purchase page defaulted to multi-AZ with the primary node in Hong Kong Zone 1, while only a Hong Kong Zone 2 subnet existed. The page therefore showed `current zone has no valid subnet`.

Fixed without creating paid database resources:

- Created Hong Kong Zone 1 subnet: `jiejing-hk-subnet-az1`, `subnet-nqepis1v`, `172.17.1.0/24`.
- Confirmed Hong Kong Zone 2 subnet: `jiejing-hk-subnet-az2`, `subnet-ghylmrft`, `172.17.0.0/24`.
- Created Hong Kong Zone 3 subnet: `jiejing-hk-subnet-az3`, `subnet-ipwf677z`, `172.17.2.0/24`.
- Created database security group: `jiejing-hk-db-sg`, `sg-ppc6cluh`.
- Security group ingress only opens PostgreSQL/Redis ports for private CIDR ranges, not public internet.

Price probes:

- PostgreSQL 18 minimum HK spec `pg.it.small2`, 1 vCPU / 2GB / 10GB, pay-as-you-go: about `0.98 CNY/hour`.
- Redis 7.0 master-slave supports smaller sizes by API; 256MB pay-as-you-go price probe returned about `0.06 CNY/hour`, while the console default 4GB option showed about `0.98 CNY/hour`.

Do not buy MySQL, TDSQL-C, RabbitMQ, RocketMQ, CKafka, or COS as replacements for the current PostgreSQL/Redis requirement.
