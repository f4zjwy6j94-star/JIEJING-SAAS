# Jiejing Tencent Cloud Resource Audit - 2026-05-19

This is a read-only audit of the Tencent Cloud resources visible in the console and the current Jiejing staging runtime. No purchases, deletions, password changes, OAuth actions, or eBay syncs were performed.

## Current Runtime Truth

- Public staging: `https://mentioned-shake-inter-critical.trycloudflare.com`
- Staging host: Lighthouse `lhins-bulffuz3`, public IP `42.194.158.47`
- App path: `/opt/jiejing-staging/app`
- Running containers: `jiejing-saas`, `jiejing-worker`, `jiejing-frontend`, `jiejing-vault`, `jiejing-cloudflared`
- Real platform writes: `false`
- Latest official eBay packet: `packet_5c69bcc5bf0e79ae`
- Runtime database: managed Postgres is selected and live-probed
- Runtime queue: Redis Streams is selected and live-probed
- Runtime secret resolver: Tencent SSM/KMS is selected and ready
- Runtime monitoring: Tencent CLS safe access logs are configured
- Runtime backup target: Tencent COS is configured and live-probed

## Tencent Cloud Inventory

| Resource | Count | Observed resource | Jiejing use | Judgment |
|---|---:|---|---|---|
| Lighthouse | 1 | `lhins-bulffuz3`, public IP `42.194.158.47`, running | Hosts current public staging Docker stack | Keep. Rename from old/Hermes wording to `jiejing-staging` later. |
| CVM | 1 | `ins-01hsr6ti`, public IP `159.75.102.10`, running | No evidence current staging uses it | Candidate extra cost. Do not delete until backed up and confirmed not holding needed old data. |
| TencentDB PostgreSQL | 1 | `postgres-8yuuxdqb`, running | Primary SaaS database | Keep. Correct product. |
| TencentDB Redis | 1 | `crs-bueo6vz7`, running | Redis Streams queue/runtime delivery | Keep. Correct product. |
| COS | 1 | `jiejing-staging-backup-1423900563` | Backup and restore drill storage | Keep. Correct product. |
| CLS | 2 logsets / 2 topics | `jiejing-staging`, `jiejing-saas-runtime`, plus `qcloud_track`/COS topic | Jiejing runtime logs and Tencent generated COS tracking | Keep Jiejing logset/topic. `qcloud_track` appears service-generated; do not delete without checking COS/CLS linkage. |
| SSM | 4 credentials | three `jiejing-staging-secret_*`, one `jiejing-staging-runtime-probe` | Backend-only secret_ref storage and runtime probe | Keep. Correct product. |
| KMS | 1 key | KMS key present and linked by SSM credentials | Encryption backing SSM | Keep. Correct product. |
| VPC | 1 | `Default-VPC` | TencentDB private network | Keep. |
| Cloud Connect Network | 1 | `ccn-3kgturgn`, name `jiejing` | Connects Lighthouse/network boundary to TencentDB private network | Keep for now. Can remove only if app is moved into the same VPC as Postgres/Redis. |
| Host Security | dashboard warnings only | many security events shown in console | Security product signal, not SaaS runtime component | Not a core architecture product. Review separately; not proof of extra SaaS infra. |
| Smart Advisor | advisory findings only | risk suggestions | Advisory, not a runtime dependency | Not core. Use for cleanup/security suggestions only. |
| Hunyuan image | 0 package/resources in dashboard | no runtime usage observed | Not part of current SaaS path | No action needed unless buying model/media capability later. |

## Runtime Checks Performed

- `/health`: `ok`, staging, real writes disabled.
- `/readiness/product-saas`: Postgres, Redis, Tencent SSM/KMS, CLS, COS are ready; paid launch still blocked by model value proof and external billing provider.
- `/infrastructure/drivers`: Postgres and Redis live checks pass; cutover blockers empty.
- `/vault/secret-resolver/status`: provider `tencent_ssm`, managed live resolution ready.
- `/backup/plan`: COS target ready with latest successful probe.
- `/monitoring/status`: Tencent CLS configured, safe logging excludes bodies, Authorization headers, and raw tokens.
- Remote Tencent integration test: `PASS jiejing_tencent_cloud_integrations`.

## Redundancy / Cost Findings

1. **CVM `ins-01hsr6ti` is the only clear extra-cost candidate.**
   - It is running and has public IP `159.75.102.10`.
   - Current Jiejing staging uses Lighthouse `42.194.158.47`, not this CVM.
   - Port check showed SSH open, HTTP/HTTPS closed, so it is not serving the current SaaS website.
   - Recommendation: snapshot/check contents first, then stop it for a few days before releasing.

2. **HashiCorp Vault container is still running as transitional fallback.**
   - Runtime now reports Tencent SSM/KMS as selected.
   - Keep briefly until all secret refs are proven resolvable through Tencent SSM over time.
   - Then remove the container from staging compose.

3. **Docker disk has reclaimable build cache.**
   - Root disk is about 76% used.
   - Docker build cache is large and mostly reclaimable.
   - Recommendation: after confirming no rollback build is needed, prune build cache only; do not prune volumes.

4. **`qcloud_track` CLS/COS resources look Tencent-generated.**
   - They may come from COS/client log analysis.
   - Do not delete blindly; low priority to investigate later.

## Architecture Judgment

The Tencent Cloud architecture is directionally correct for the current Jiejing SaaS stage:

`Lighthouse + Docker + Cloudflare tunnel -> SaaS backend/worker/frontend -> TencentDB Postgres + TencentDB Redis + Tencent SSM/KMS + CLS + COS`

This is not overbuilt for an early staging SaaS. The only likely paid resource that is not part of the current runtime path is the separate CVM instance.

## Next Safe Actions

1. Rename cloud resources to remove old Hermes/OpenClaw ambiguity:
   - Lighthouse: `jiejing-staging`
   - Postgres: `jiejing-postgres-staging`
   - Redis: `jiejing-redis-staging`
   - CVM: `candidate-old-unused-cvm`

2. Audit CVM `ins-01hsr6ti` before stopping:
   - snapshot disk
   - inspect `/opt`, Docker containers, and project directories
   - if no needed data, stop it first, then release after a waiting period

3. Clean staging server disk:
   - remove Docker build cache only
   - keep volumes and active images

4. Keep product work focused on:
   - model-backed Market Report and Listing Package proof
   - external billing provider
   - stable domain/TLS/eBay callback/CORS
   - final frontend removal of demo/mock fallbacks
