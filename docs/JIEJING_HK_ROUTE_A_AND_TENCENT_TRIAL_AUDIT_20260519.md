# Jiejing HK Route A And Tencent Trial Audit - 2026-05-19

This records the current Route A migration state and a first pass on Tencent Cloud cost/trial mapping. No eBay OAuth, eBay sync, real platform write, database migration, or source-host shutdown was performed.

## HK Route A Edge Status

- Edge instance: `lhins-lxff3wj3`
- Edge public IP: `43.129.205.244`
- Region: `China Hong Kong | Hong Kong Zone 2`
- OS: Ubuntu Server 24.04 LTS
- Hostname: `VM-0-15-ubuntu`
- SSH user: `ubuntu`
- SSH key: `output/route-a-edge-ssh/jiejing_route_a_edge_ed25519`
- Caddy version: `2.6.2`
- Caddy service: `active`
- Current mode: HTTP edge proxy only, no app/database/secret migration yet.

Current edge flow:

```text
Browser
  -> http://43.129.205.244
  -> Caddy on HK Lighthouse
  -> https://mentioned-shake-inter-critical.trycloudflare.com
  -> existing Guangzhou staging source on 42.194.158.47
```

External verification passed:

```text
GET http://43.129.205.244/health
status: ok
service: jiejing-saas-backend-mvp
environment: staging
real_platform_writes_enabled: false
```

Response headers include:

```text
Server: Caddy,cloudflare
X-Jiejing-Edge: route-a-hk
```

The edge node must continue to avoid storing:

- eBay access tokens or refresh tokens
- model provider keys
- database URLs
- Tencent SecretId/SecretKey
- SaaS session secrets

## Migration Decision

Do not release the Guangzhou Lighthouse yet.

Current split:

- `42.194.158.47`: current real staging source, Docker app stack, Cloudflare tunnel, backend/worker/frontend/Vault.
- `43.129.205.244`: new HK edge proxy, currently only forwards to the existing source.

Safe migration sequence:

1. Keep HK edge proxy live and verify it repeatedly.
2. Point beta domain DNS to `43.129.205.244`.
3. Enable Caddy TLS for the real domain.
4. Add the real domain to staging CORS.
5. Only after domain/TLS/CORS pass, decide whether to migrate the full app stack to HK.
6. If full app migration is chosen, do a backup/restore rehearsal into HK or a managed DB path first.
7. Observe 24-72 hours.
8. Stop Guangzhou first, observe again, then release.

## Current Tencent Cost Snapshot

Observed in Tencent Cloud Expense Center on 2026-05-19. The console says the 2026-05 bill is current through 2026-05-18 and some pay-as-you-go resources may not be fully settled.

| Product | 2026-05 observed cost |
| --- | ---: |
| Total | 29.57 RMB |
| Lighthouse | 20.00 RMB |
| TencentDB Redis | 5.34 RMB |
| TencentDB PostgreSQL | 4.26 RMB |
| CLS | 0.00 RMB |
| KMS | 0.00 RMB |
| Monthly precision adjustment | -0.03 RMB |

This does not fully reflect the HK Lighthouse purchased on 2026-05-19.

## Current Architecture Cost Buckets

| Resource | Current role | Cost posture | Trial/optimization judgment |
| --- | --- | --- | --- |
| Guangzhou Lighthouse `42.194.158.47` | Current source host | Paid, monthly Lighthouse | Keep until HK path is source-complete and observed. Release later. |
| HK Lighthouse `43.129.205.244` | Route A edge | Paid, 38 RMB/month purchase | Keep as beta domain edge. Can replace Guangzhou after full migration. |
| Old CVM `159.75.102.10` | Not current staging | Candidate extra cost | Snapshot exists; stop/release after final dependency check. |
| TencentDB PostgreSQL | Primary SaaS database | Small pay-as-you-go/monthly cost observed | Keep. Do not replace with a throwaway trial DB unless restore and secret boundaries are proven. |
| TencentDB Redis | Queue/Redis Streams | Small pay-as-you-go/monthly cost observed | Keep. Do not collapse into local Redis for beta if async jobs matter. |
| COS | Backup target | No visible May cost in summary | Keep; backup/restore drill already depends on it. |
| CLS | Runtime logs | 0.00 RMB observed | Keep; no optimization needed now. |
| SSM/KMS | Secret boundary | KMS 0.00 RMB observed | Keep; this is a security boundary, not a cost target. |
| Cloudflare tunnel | Current public staging tunnel | External dependency, temporary | Can be removed after stable domain points to HK edge/source. |

## Tencent Trial Mapping

Official free/trial pages checked:

- Tencent Cloud China free trial center: `https://cloud.tencent.com/act/free`
- Tencent Cloud International free tier: `https://www.tencentcloud.com/act/pro/FreeTier`

Useful matches:

1. **Lighthouse free trial**
   - China free center shows Lighthouse free trials such as `2C2G3M` for `1 month`.
   - This maps directly to our app host or staging host.
   - However, Tencent states product trials are for product-new users. Because this account already has Lighthouse usage, eligibility may be blocked.

2. **CVM free trial**
   - China free center shows CVM trial options.
   - This can be used for short-lived experiments, but it is not the preferred Route A domain entry if the instance is mainland China, because formal public domain usage can trigger ICP filing requirements.

3. **Cloud DNS trial**
   - China free center shows DNSPod/Cloud DNS professional/enterprise trial for `1 month`.
   - Useful only if the real domain will be managed in Tencent DNS. It does not replace compute, database, Redis, logs, or secrets.

4. **COS free tier/trial**
   - International free tier page shows COS trial/free-tier style storage allowances.
   - This maps to Jiejing backup storage, but current COS cost is not the main cost pressure.
   - Keep backup bucket and restore drill evidence intact.

5. **CLS free tier/trial**
   - International free tier page includes Cloud Log Service free-tier style allowance.
   - This maps to Jiejing safe runtime logs.
   - Current May cost is already `0.00 RMB`, so no urgent action.

6. **Tencent AI Agent / OrcaTerm trials**
   - Free center shows Tencent Cloud AI Agent development platform and OrcaTerm professional trials.
   - These do not replace Jiejing Runtime/Agents or the production SaaS stack. Treat as optional tooling only.

Not good trial targets right now:

- Replacing managed PostgreSQL with a temporary/free database without a restore drill.
- Replacing Redis Streams with local Redis just to save a few RMB while provider jobs/model jobs depend on queue behavior.
- Moving secrets away from SSM/KMS to save cost. KMS cost is currently 0 and the boundary is important.
- Deleting CLS/COS just because they are infrastructure. They are part of paid-launch safety evidence.

## Recommended Cost Actions

Immediate:

1. Keep HK edge running.
2. Keep Guangzhou running until HK is fully promoted.
3. Stop/release old CVM after the already-created snapshot is verified and no hidden dependency is found.
4. Do not buy more database/Redis resources until model value proof is ready.

After Route A domain works:

1. Decide whether HK becomes full source host or remains edge-only.
2. If HK becomes full source, migrate app stack and then stop Guangzhou for observation.
3. After observation, release Guangzhou Lighthouse before its next renewal.

Trial use:

- Try to claim Lighthouse free trial only if Tencent still marks the account eligible. Do not restructure the architecture around a trial that may be unavailable because the account has existing Lighthouse usage.
- Use DNS trial if choosing Tencent DNS for the final domain.
- Keep COS/CLS/SSM/KMS as-is because they are low/no visible cost and protect backup, logging, and secret boundaries.
