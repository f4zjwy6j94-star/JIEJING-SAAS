# Jiejing Tencent Resource Retirement Audit - 2026-05-19

This file started as the read-only audit before retiring Tencent Cloud resources. It now also records the final 2026-05-19 retirement outcome after user confirmation.

## Final Retirement Result

Completed on 2026-05-19 after a final HK data check:

- Guangzhou Lighthouse `lhins-bulffuz3` / `42.194.158.47`: refund/return submitted successfully.
- Guangzhou CVM `ins-01hsr6ti` / `159.75.102.10`: released from CVM recycle bin.
- Guangzhou PostgreSQL `postgres-8yuuxdqb`: destroyed and removed from PostgreSQL recycle bin.
- Guangzhou Redis `crs-bueo6vz7`: destroyed and removed from Redis recycle bin.
- Guangzhou CCN `ccn-3kgturgn`: all VPC attachments removed, then CCN deleted.
- Guangzhou VPC `vpc-njexozrh` / `Default-VPC`: deleted after CVM/PostgreSQL/Redis dependencies were cleared.

Post-retirement HK verification:

- `https://individually-buffalo-prescribed-blocking.trycloudflare.com/health`: `status=ok`, `real_platform_writes_enabled=false`.
- `http://43.129.205.244/health`: `status=ok`, `real_platform_writes_enabled=false`.
- Active HK containers are running on `43.129.205.244`.
- `/readiness` still reports `platform_data_packets=6`, `reports=44`, `confirmations=36`, `stores=3`, `platform_connections=6`, `secret_refs=6`, and `audit_logs=315`.
- Official packet `packet_5c69bcc5bf0e79ae` is still present with all six official eBay resource sections and `source_mode=official_api`.

Kept intentionally:

- HK Lighthouse, HK PostgreSQL, HK local Redis, HK VPC/subnets/security group, and HK Docker volumes.
- COS backup bucket, CLS logsets/topics/alarms/notices, SSM secrets, and KMS keys in Guangzhou because they remain part of the active project boundary.
- CVM snapshots are rollback evidence and were not deleted in this retirement pass.

Remaining cost decision:

- HK managed Redis `crs-b119e0fy` exists but is not active in the app path. The live app uses local Docker Redis `jiejing-hk-redis`. Release `crs-b119e0fy` only after a separate user confirmation.

## Current Active Runtime

- Active public HTTPS staging route: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`
- Active public IP route: `http://43.129.205.244`
- Active compute host: HK Lighthouse `lhins-lxff3wj3`, `43.129.205.244`
- Active database: HK PostgreSQL `postgres-b6chkvaj`
- Active queue/cache: HK local Docker Redis container `jiejing-hk-redis`
- Real platform writes: disabled
- eBay OAuth and official read-only sync: not repeated

## Current Data Checks

Verified from the active HK backend:

- tables: `17`
- `platform_data_packets`: `6`
- `reports`: `44`
- `confirmations`: `36`
- `stores`: `3`
- `platform_connections`: `6`
- `secret_refs`: `6`
- `packet_5c69bcc5bf0e79ae`: present
- packets by source mode: `official_api = 6`

Connection and secret-ref summary:

- `platform_connections`: eBay OAuth `read_only_authorized = 5`, `read_only_pending_or_demo = 1`
- `secret_refs`: eBay refresh-token refs `managed_vault_stored = 5`, one legacy/platform connection ref still marked `external_vault_required`

## Active HK Resources To Keep

Keep these for the current HK staging path:

- Lighthouse: `lhins-lxff3wj3`, `43.129.205.244`, `jiejing-route-a-edge-hk`
- PostgreSQL: `postgres-b6chkvaj`
  - private: `172.17.2.10:5432`
  - public endpoint: `hk-postgres-b6chkvaj.sql.tencentcdb.com:22663`
- VPC: `vpc-bkg6pc8k`, `jiejing-hk-vpc`, `172.17.0.0/16`
- Subnets:
  - `subnet-nqepis1v`, `jiejing-hk-subnet-az1`, `172.17.1.0/24`
  - `subnet-ghylmrft`, `jiejing-hk-subnet-az2`, `172.17.0.0/24`
  - `subnet-ipwf677z`, `jiejing-hk-subnet-az3`, `172.17.2.0/24`
- Security group: `sg-ppc6cluh`, `jiejing-hk-db-sg`
  - includes restricted PostgreSQL public endpoint access from `43.129.205.244/32`
- HK local Docker volumes:
  - `deploy_jiejing_public_staging_data`
  - `deploy_jiejing_public_staging_vault_data`
  - `jiejing_hk_redis_data`

## HK Resource That Exists But Is Not Active

- HK TencentDB Redis: `crs-b119e0fy`
  - private endpoint: `172.17.1.14:6379`
  - app is not using it right now because Lighthouse cannot reach it through the current Tencent networking limits.
  - active queue/cache is the HK local Redis container instead.

Decision needed: keep this Redis for a later CVM/VPC compute move, or release it to avoid paying for an unused instance.

## Guangzhou Resources Retired After Final Confirmation

These no longer serve the active HK route and were retired after user confirmation and final data checks.

- Guangzhou Lighthouse: `lhins-bulffuz3`, `42.194.158.47`
  - refund/return submitted successfully.
- Guangzhou PostgreSQL: `postgres-8yuuxdqb`
  - old private endpoint: `172.16.0.12:5432`
  - migrated to HK PostgreSQL and no longer used by active HK config
- Guangzhou Redis: `crs-bueo6vz7`
  - old private endpoint: `172.16.0.15:6379`
  - one key was migrated to HK local Redis
- Old CVM: `ins-01hsr6ti`, `159.75.102.10`
  - previously audited as not serving current Jiejing SaaS
  - released from the CVM recycle bin after snapshot evidence existed
- CVM system disk: `disk-fmmjj0o6`
  - attached to `ins-01hsr6ti`
- CVM snapshots:
  - `snap-rq3ysy51`, `jiejing-cvm-preaudit-ins-01hsr6ti-20260519`
  - `snap-pj4oyc0r`, unnamed
- Guangzhou VPC resources tied to old DB/CVM:
  - VPC `vpc-njexozrh`, `Default-VPC`, `172.16.0.0/16`
  - subnet `subnet-dz8fnm7u`, `Default-Subnet`
  - security group `sg-jw87hmwx`, default group
  - VPC deletion completed after dependencies were cleared
- CCN: `ccn-3kgturgn`
  - attached to Guangzhou Lighthouse VPC `vpc-8i1750st`
  - attached to Guangzhou VPC `vpc-njexozrh`
  - both attachments were removed and CCN was deleted

## Guangzhou Region Resources To Keep For Now

These are in `ap-guangzhou` but are still part of the active project boundary. Do not release them just because the compute moved to HK.

- COS backup bucket: `jiejing-staging-backup-1423900563`
  - region: `ap-guangzhou`
  - prefix: `jiejing/staging/backups`
  - currently contains:
    - `probes/jiejing-cos-probe-2026-05-18T203907Z0000.json`
    - `restore-drills/jiejing-restore-drill-2026-05-18T215026.332056Z0000.json`
- CLS logset: `edee5162-3b8f-49f2-a02a-ab2eaa09a207`, `jiejing-staging`
- CLS topic: `8bbb90fc-4492-40e3-b6f8-93504b85190c`, `jiejing-saas-runtime`
- CLS alarm: `alarm-5280cf4a-567a-49d3-98b8-4bcfa00cb54d`, `jiejing-staging-saas-runtime-error-count`
- CLS notice: `notice-a873583f-a918-4012-8867-3462a437a5a7`
- CLS COS SDK tracking logset/topic:
  - logset `819726a1-35ac-48ae-a73a-46827c4d00a1`, `qcloud_track`
  - topic `ed438b40-49fb-491f-b6c7-7f8c72c115a6`, `qcloud_track_jiejing__cos_topic`
- SSM secrets:
  - `jiejing-staging-secret_64ec41dba61dc026`
  - `jiejing-staging-secret_7f9d7305faa804ee`
  - `jiejing-staging-secret_20d8d390b3aaa172`
  - `jiejing-staging-runtime-probe`
- KMS:
  - listed key `91716a98-52b2-11f1-873a-5254003701c1`
  - SSM metadata references Tencent default KMS key id `9df038ba-52f9-11f1-82fd-52540058c57f`

## DNS And Domain Status

- DNSPod domain list returned zero domains.
- No stable real domain is currently configured for Jiejing.
- Current HK HTTPS route is a temporary trycloudflare URL, not a permanent production domain.

## Historical Release Order

This was the release order used after user confirmation:

1. Run one final HK data check.
2. Keep a copy of this audit and the restore drill evidence.
3. Release old CVM `ins-01hsr6ti` only after confirming snapshots are sufficient.
4. Release Guangzhou Lighthouse `lhins-bulffuz3`.
5. Release Guangzhou PostgreSQL `postgres-8yuuxdqb`.
6. Release Guangzhou Redis `crs-bueo6vz7`.
7. Clean up Guangzhou CCN/VPC/SG only after the above resources are gone.
8. Decide separately whether to release unused HK TencentDB Redis `crs-b119e0fy`.

SSM, KMS, COS, CLS, and the active HK resources were not released during the Guangzhou cleanup.
