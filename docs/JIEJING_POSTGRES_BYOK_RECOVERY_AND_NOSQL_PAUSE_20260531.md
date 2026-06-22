# Jiejing Postgres/BYOK Recovery and NoSQL Pause - 2026-05-31

## Scope

This note records the staging recovery after Tencent Cloud billing interruption and the cost-control decision to pause Redis/NoSQL while keeping managed Postgres as the system of record.

No password, token, eBay refresh token, model key, database password, or raw provider credential is recorded here.

## Current Public Staging

Public route:

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com
```

Verified after recovery:

```text
/health status=ok
environment=staging
database_startup_status=ready
real_platform_writes_enabled=true
requested_real_platform_writes=true
secret_exposed=false
```

Product readiness summary after recovery:

```text
database=ready
database_adapter=managed_adapter_live
queue=local_worker_queue_shape
queue_worker=local_worker_shape_ready
blocker_count=3
warning_count=2
production_ready=false
beta_ready=false
can_accept_real_customers=false
```

The remaining blockers are expected while Redis/NoSQL is intentionally paused:

```text
queue
queue_adapter_contract
infrastructure_drivers
```

## Managed Postgres Recovery

Postgres DNS and TCP connectivity were checked from the staging host after the user recharged Tencent Cloud.

Result:

```text
hk-postgres-b6chkvaj.sql.tencentcdb.com resolves
TCP port 22663 reachable
```

The public HTTPS compose now layers a server-private env file after the public staging env:

```text
deploy/jiejing-saas.staging-oauth.env
../../private/postgres-localqueue.env
```

The server-private `postgres-localqueue.env` is derived on the server from the existing private managed infra env, then overrides queue settings back to local worker:

```text
JIEJING_DATABASE_ENGINE=postgres
JIEJING_DATABASE_ADAPTER=postgres-managed
JIEJING_QUEUE_PROVIDER=local_worker
JIEJING_QUEUE_URL=
```

This restores managed Postgres without re-enabling Redis/NoSQL dependency.

## BYOK / Model State

After the Postgres cutover, readiness shows:

```text
model_secret_refs=5
model_configured=true
provider_status.model.mode=merchant_byok
provider_status.model.merchant_byok_configured=true
provider_status.model_value.ready_for_paid_value_claim=true
provider_status.model_value.live_model_report_types=["listing.package","market.report"]
```

This confirms the historical merchant BYOK model references are visible again through the backend readiness boundary. Raw model keys were not printed, copied, or written into repo files.

## eBay / Product Evidence

After Postgres recovery:

```text
read_only_authorized_connections=6
ebay_secret_refs=9
latest_ebay_packet_id=packet_2fc16b08e7bb4955
latest_ebay_packet_status=packet_cached_sanitized
latest_ebay_packet_source_mode=official_api
latest_ebay_packet_created_at=2026-05-25T13:20:22+00:00
report_count=152
confirmation_count=117
```

Do not repeat eBay OAuth just to check status.

## NoSQL / Redis Pause

The local Docker Redis container on the staging host was inspected before stopping:

```text
container=jiejing-hk-redis
key_count=1
stream=jiejing:queue
stream_length=15
consumer_group=jiejing-workers
pending=0
lag=0
dead_letter_stream_missing=true
```

The Redis data was backed up before stopping the container:

```text
/opt/jiejing-staging/backups/nosql-pre-stop-20260531T130922Z
```

Backup includes:

```text
redis-data-rdb-aof.tar.gz
redis-keyspace.txt
redis-jiejing-queue-xinfo.txt
redis-jiejing-queue-groups.txt
redis-jiejing-queue-xrange.txt
saas.sqlite
SHA256SUMS.txt
```

The local Docker Redis container was stopped after backup:

```text
jiejing-hk-redis Exited (0)
```

The public app remained healthy after the stop because current staging uses `local_worker`.

## Verification

Local checks passed before remote compose sync:

```text
python tools/test_jiejing_oauth_staging_deploy_contract.py
python tools/test_jiejing_managed_infra_readiness_cutover.py
python -m py_compile jiejing_saas/api_server.py jiejing_saas/postgres_repository_runtime.py jiejing_saas/model_value_gate.py jiejing_saas/model_value_rehearsal.py
```

Remote checks passed after cutover:

```text
container /health ok
public /health ok
public /readiness/product-saas reports managed Postgres live
node tools/codex_jiejing_all_modules_clean_smoke.js ok=true
```

Browser smoke output:

```text
output/browser-smoke/2026-05-31T13-26-07-297Z-all-modules-clean-ui
```

## Next Actions

1. Keep TencentDB Postgres running; it is the product system of record.
2. It is acceptable to keep TencentDB Redis/NoSQL stopped while cost control matters, because staging now runs local worker and Redis has no pending jobs.
3. For formal beta/paid launch, re-enable a managed queue or cloud queue and clear the 3 queue-related readiness blockers.
4. Verify real merchant login and AI CEO chat with the existing BYOK store context, because anonymous smoke sessions do not carry merchant BYOK refs.
5. Refresh eBay packet only when needed for a real test flow; do not repeat OAuth just for status.

## TencentDB Redis Billing Instance Release

The Tencent Cloud console still showed a paid Redis instance after the local Docker Redis pause. That was a separate pay-as-you-go TencentDB Redis resource, not the local Docker Redis container:

```text
region=ap-hongkong
instance_id=crs-jd4il28o
instance_name=Asd572493200
billing_mode=pay_as_you_go
created_at=2026-05-22 12:32:18
```

The instance was checked through the Tencent Cloud Redis API and then released through the official `DestroyPostpaidInstance` action. No Tencent API secret was printed or persisted.

```text
before_destroy.status=2
cloud_backup_count=0
destroy.task_id=65680730
destroy.http_status=200
destroy.error=null
task.status=succeed
after_destroy.status=-3
```

Tencent Cloud's Redis instance status code `-3` means the instance is no longer running and is waiting for deletion/recycle processing. If the console still shows the row briefly, refresh the page or check the recycle/deletion state; do not recreate this Redis instance unless the production queue cutover is being intentionally restored.

Post-release verification:

```text
public /health ok
database_startup_status=ready
secret_exposed=false
JIEJING_QUEUE_PROVIDER=local_worker
JIEJING_DATABASE_ADAPTER=postgres-managed
JIEJING_DATABASE_ENGINE=postgres
JIEJING_VAULT_PROVIDER=tencent_ssm
```
