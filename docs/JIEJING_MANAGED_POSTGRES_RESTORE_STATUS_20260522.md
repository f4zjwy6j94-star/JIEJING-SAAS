# Jiejing Managed PostgreSQL Restore Status - 2026-05-22

## Result

Hong Kong staging has been moved back from cost-saver SQLite mode to managed PostgreSQL.

Active public route:

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com
```

Active backend state after cutover:

```text
environment=staging
database_engine=postgres
database_adapter=postgres-managed
real_platform_writes_enabled=false
beta_ready=true
production_ready=false
can_accept_real_customers=false
blocker_count=0
warning_count=2
```

## Data Recovery

Before cutover, the current SQLite runtime database was snapshotted:

```text
/data/output/cost-saver-snapshots/20260522-123655-before-managed-cutover
total_rows=508
business_rows=507
```

The managed PostgreSQL instance already contained a larger historical dataset. The SQLite rows were imported with `on conflict do nothing`, so existing PostgreSQL rows were not overwritten.

Post-cutover public readiness counts:

```text
users=148
companies=147
team_members=148
stores=87
platform_connections=78
secret_refs=12
oauth_authorization_requests=21
platform_data_packets=7
tasks=25
queue_jobs=13
task_steps=44
reports=54
confirmations=45
merchant_memory=19
audit_logs=702
schema_migrations=2
```

Latest product evidence:

```text
latest_ebay_packet_id=packet_0b5dd20476f71eab
model_secret_refs=5
merchant_memory=19
```

## Redis Status

The newly opened TencentDB Redis instance exists in Hong Kong, but it is reachable only through private VPC networking from the current API view. The current staging host cannot reach that private Redis endpoint from the existing Lighthouse topology.

For safety, staging continues to use the existing `jiejing-hk-redis` queue endpoint instead of exposing managed Redis to the public internet.

## Safety Notes

- Demo session bootstrap remains disabled.
- Real platform writes remain disabled.
- Raw eBay tokens and model keys are not exposed in public responses.
- PostgreSQL URL and cloud credentials remain only in server-private env files.

## Verification

Verified after restart:

```text
GET /health -> 200
POST /auth/demo-session -> 403
GET /readiness -> beta_ready=true, blocker_count=0
Postgres live check -> ok
Redis current queue live check -> ok
```

## 2026-05-22 True Publish Enablement Update

After the first real eBay publish adapter was added, staging briefly fell back to
the cost-saver SQLite compose override because `deploy/apply-staging-patch.sh`
automatically included `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml`
whenever that file existed. That behavior has been fixed: the override is now
used only when `JIEJING_USE_COST_SAVER_OVERRIDE=true` is explicitly set.

Current verified runtime after redeploy:

```text
database_engine=postgres
database_adapter=postgres-managed
queue_provider=redis_streams
database_url_configured=true
queue_url_configured=true
requested_real_platform_writes=true
real_platform_writes_enabled=true
ebay_write_live_enabled=true
ebay_token_refresh_live_enabled=true
```

The eBay write adapter is now enabled for only one live write action:

```text
live_actions_supported=["publish_listing"]
blocked_by=[]
```

The merchant account `zongshuding4@gmail.com` is present again on managed
PostgreSQL and can log in. Its current eBay store record is:

```text
store_id=store_bdce2f90f8259912
store_name=zongshuding4
marketplace=EBAY_US
```

Current remaining blocker for actual eBay publish:

```text
eBay connection status=read_only_authorized
missing write scope=https://api.ebay.com/oauth/api_scope/sell.inventory
```

Next required step is merchant browser authorization through the new publish
OAuth flow. The workbench now exposes a publish authorization action that calls
`POST /stores/{store_id}/ebay-oauth/publish-plan`, requests the `sell.inventory`
scope, and redirects the merchant to eBay. After callback, Jiejing should create
a `publish_authorized` connection. Only then can confirmation center execution
attempt a real Inventory API `publish_listing`.

## 2026-05-22 Confirmation and Publish OAuth Follow-up

The merchant completed the publish OAuth flow after the write adapter was
enabled. The store now has `publish_authorized` eBay connections with
`sell.inventory` scope and backend-managed `secret_ref` values.

Two follow-up fixes were deployed:

1. Confirmation endpoints now URL-decode dynamic path segments. This fixes
   confirmation IDs containing `::` when the frontend calls
   `encodeURIComponent(...)`.
2. The eBay OAuth callback page now labels completed callbacks as either
   `eBay 发布授权已完成` or `eBay 只读授权已完成` based on the authorized scope.

The `倒流香炉` workflow records are present under task
`task_1b45f78057023799`, created at `2026-05-22T09:18:02+00:00`
(`2026-05-22 17:18:02` China time). Persisted report types include market
packet, market report, source match, listing package, asset brief, customer
learning, finance review, confirmation package, and AI CEO final report.

The real publish preflight now reaches the confirmation record correctly, but
it still blocks real eBay publishing because the draft lacks required platform
facts:

```text
listing.description_html
listing.condition
listing.price
listing.quantity
listing.merchant_location_key
supplier_facts.package_weight_g
supplier_facts.package_dimensions_cm
supplier_facts.material
supplier_facts.item_location
asset_manifest.assets
finance_review.net_profit_money
```

Frontend confirmation execution was also changed to stop after preflight when
required facts are missing, instead of continuing to the execution endpoint and
showing a generic failure toast.
