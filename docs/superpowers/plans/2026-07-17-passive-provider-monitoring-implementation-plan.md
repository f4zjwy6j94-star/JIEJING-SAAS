# Passive Provider Monitoring Implementation Plan

## Status and objective

Approved design: `docs/superpowers/specs/2026-07-17-passive-provider-monitoring-design.md`.

This plan implements a worker-native, passive provider monitoring scheduler for Jiejing. It evaluates already-recorded real-business telemetry, preserves `insufficient_data` when no eligible samples exist, exports one privacy-safe aggregate event to Tencent CLS, and requires fresh scheduler/export/alarm evidence before provider observability can be ready.

This work must not initiate model, public-search, media-generation, payment, eBay or other business-provider requests. It must not change paid-launch, public-charging, eBay authorization or real-write truth.

## Non-negotiable repository and release constraints

- Preserve the current dirty worktree as the latest project state. Never reset, clean, checkout, stash, broad-format or overwrite unrelated changes.
- Add no new bundled runtime, operator or test files. Extend existing files so the staging bundle stays at exactly 274 unique files.
- Add no new precloud check entry. Strengthen existing checks so the fixed full gate stays exactly 107/107.
- Never invent a cost budget. Missing or invalid warning/critical thresholds remain a readiness blocker.
- Never expose prompts, replies, search queries, raw errors, credentials, cloud resource IDs, merchant/user/store/order/task IDs or provider names in CLS events, status payloads, logs or evidence.
- Never use `curl -k` or any other TLS bypass for deployment verification.
- Deploy API health before the worker, and ensure observability failure cannot delay or fail merchant queue processing.

## Phase 0: Allowed APIs, copy sources and prohibited patterns

### Allowed repository/runtime APIs

Use these existing repository patterns instead of inventing parallel state machines:

- `jiejing_saas/operations_metering.py:276-360` — `build_reliability_alert_summary()` and its minimum-five-samples `insufficient_data` behavior.
- `jiejing_saas/operations_metering.py:363-502` — `reconcile_reliability_alert_state()` two-breach/two-recovery lifecycle.
- `jiejing_saas/repository.py:6019-6092` — durable `reconcile_provider_reliability_alerts()` persistence.
- `jiejing_saas/repository.py:6094-6147` — lifecycle read model.
- `jiejing_saas/repository.py:7651-7699` — cross-SQLite/Postgres atomic `INSERT ... ON CONFLICT ... RETURNING` pattern.
- `tools/jiejing_worker_cli.py:106-156` — periodic maintenance timing and exception isolation.
- `jiejing_saas/monitoring.py:391-416` — timezone-aware, future-skew-aware evidence freshness.
- `tools/jiejing_configure_tencent_runtime_env.py:442-506` — finite numeric validation and derived redacted status.

### Allowed Tencent CLS control-plane APIs

Use the installed `tencentcloud-sdk-python-cls` v20201016 API surface with lazy imports inside the existing configurator:

- `ClsClient.DescribeIndex(DescribeIndexRequest)` for read-only index validation.
- `ClsClient.DescribeAlarms(DescribeAlarmsRequest)` for name/topic filtering and mandatory read-back.
- `ClsClient.CreateAlarm(CreateAlarmRequest)` only under explicit `--apply-provider-alarms`.
- `ClsClient.ModifyAlarm(ModifyAlarmRequest)` only under explicit apply and only when one exact alarm match differs.
- `ClsClient.SearchLog(SearchLogRequest)` for a privacy-safe `probe=true` ingestion lookup.

Official API contracts:

- CreateAlarm: https://cloud.tencent.com/document/api/614/56466
- ModifyAlarm: https://cloud.tencent.com/document/product/614/56459
- DescribeAlarms: https://cloud.tencent.com/document/api/614/56461
- CLS alarm data structures: https://cloud.tencent.com/document/api/614/56471

Use documented fields, especially `Status`, `QueryString` and `QuerySyntax`. Do not rely on ambiguous compatibility fields such as `Enable`, `SearchLog.Query` or `SyntaxRule` when the documented counterpart exists.

### CLS ingestion decision

The final repository search found no reusable CLS uploader or protobuf model. Do not handcraft protobuf bytes. Add the official dedicated `tencentcloud-cls-sdk-python>=1.0.4,<2` dependency to `requirements.saas.txt` and use `tencentcloud.log.logclient.LogClient`, `tencentcloud.log.cls_pb2.LogGroupList` and `put_log_raw()` for one bounded synchronous five-minute aggregate event inside the monitoring background runner. Keep the existing CloudAPI SDK for DescribeIndex, DescribeAlarms, CreateAlarm, ModifyAlarm and SearchLog. Lock both clients behind focused fakes so unit tests make no network calls.

Official upload SDK contract: https://intl.cloud.tencent.com/document/product/614/74216

### Prohibited implementation patterns

- Do not put the scheduler inside `LocalQueueWorker.run_next()`; API inline/manual execution also calls that method.
- Do not execute the aggregate query or CLS call synchronously on the merchant queue loop.
- Do not use the process-local `_PLATFORM_RELIABILITY_ALERT_LOCK` as a distributed lease.
- Do not use a static worker ID as lease ownership; derive and hash a per-process nonce.
- Do not compare differently offset ISO timestamps lexicographically for lease expiry; use UTC epoch integers.
- Do not call the 30-day `platform_operations_overview()` from the scheduler.
- Do not allow the three legacy provider booleans to prove readiness by themselves.
- Do not let a CLI `record-now` option fabricate alarm verification evidence.
- Do not auto-modify CLS index configuration in this pass. `DescribeIndex` may report missing fields; incomplete index contracts block apply/readiness until safely corrected.
- Do not choose the first alarm when an exact name matches more than once; duplicate names are a hard operator blocker.
- Do not send a test notification or bind a new notice route implicitly.

## Phase 1: Cost evaluation and safe aggregate contract

### Files

- Modify `jiejing_saas/operations_metering.py`.
- Extend `tools/test_jiejing_operations_metering.py`.

### RED

Add table-driven tests for a new provider-neutral cost evaluator and aggregate event sanitizer:

1. Missing, blank, non-numeric, non-finite, zero, negative, or `critical < warning` budgets return `provider_cost_budget_not_configured` and never healthy.
2. With valid budgets, incomplete coverage returns attention before numeric spend is considered.
3. With complete coverage, `total == critical` is critical; otherwise `total == warning` is attention.
4. Critical wins over warning.
5. Below warning with complete coverage is healthy.
6. The aggregate event has a flat allowlist, `probe` is boolean, and no nested/raw identifiers or disallowed fields survive.
7. Reliability `insufficient_data` remains unchanged in the aggregate event.

Run and confirm the new tests fail for missing symbols:

```powershell
python tools/test_jiejing_operations_metering.py
```

### GREEN

Implement in `operations_metering.py`:

- `build_provider_cost_alert_summary(...)` with explicit minor-unit budgets and the approved priority order.
- A private strict positive-integer parser that rejects booleans, non-finite values and implicit defaults.
- `build_provider_monitoring_aggregate_event(...)` that emits only allowlisted scalar keys required by the two CLS queries.
- A single event contract version and event type constant shared by exporter/tests/configurator alarm queries.

The safe event may include only aggregate fields such as event type/version, environment class, `probe`, evaluated scope count, reliability state, cost state, cost coverage boolean, budget-configured boolean, bounded counts, and scheduler/export result classes. It must not include raw timestamps; CLS supplies ingestion time.

Re-run the focused test to green before proceeding.

## Phase 2: Focused 30-minute/24-hour snapshot and durable singleton state

### Files

- Modify `jiejing_saas/repository.py`.
- Modify `jiejing_saas/migrations/001_initial_schema_postgres.sql`.
- Extend `tools/test_jiejing_reliability_alert_lifecycle.py`.
- Extend `tools/test_jiejing_postgres_repository_cutover.py`.
- Extend `tools/test_jiejing_operations_metering.py` only for shared fixture coverage if needed.

### RED: focused snapshot eligibility

Add repository fixtures proving:

- Merchant model, public-search, media and payment telemetry inside 30 minutes contributes to reliability.
- Cost records inside 24 hours contribute to cost totals/coverage.
- Older telemetry is excluded independently by the two windows.
- Synthetic accounts are excluded.
- Model tasks whose `task_type` is rehearsal/verification/acceptance are excluded.
- Payment telemetry joined by `reference_type=payment_provider_call` and order reference excludes mock/non-commercial providers and `order_json.live_acceptance_test=true`.
- Zero eligible samples returns four real scopes with zero counts and `insufficient_data`, never healthy.
- Unknown cost/unmetered rows make coverage incomplete.
- The method does not call or construct any provider client.

The focused method contract is:

```python
provider_monitoring_snapshot(
    *,
    reliability_window_minutes: int = 30,
    cost_window_hours: int = 24,
    now_utc: datetime | None = None,
) -> dict[str, Any]
```

It must not call `platform_operations_overview()`.

### RED: lease/state

Add SQLite tests proving:

- First caller atomically acquires a named lease.
- A second owner before expiry gets no lease and no duplicate evaluation.
- The same or another owner can acquire after expiry.
- Completion requires the matching owner hash.
- Successful evaluation and successful export timestamps are persisted separately.
- Query or export failure records only a safe outcome class and does not advance the corresponding success timestamp.
- State reads expose only derived aggregate state, not owner hashes or snapshots with identifiers.

Add Postgres adapter/static contract tests for the same `ON CONFLICT ... WHERE ... RETURNING` statement and schema availability.

### GREEN

Add an idempotent `platform_provider_monitor_state` table beside the reliability alert tables in SQLite and Postgres. Keep snapshot storage as `text` in both engines to avoid a new JSONB adapter exception. Suggested columns:

- `scheduler_key` primary key;
- `lease_owner_hash` text;
- `lease_expires_at_epoch` integer;
- `last_evaluated_at` text;
- `last_exported_at` text;
- `last_outcome` text;
- `snapshot_json` text containing only the aggregate contract;
- `updated_at` text.

Register an SQLite schema migration record and add only the index needed for lease expiry/status reads.

Implement:

- `provider_monitoring_snapshot(...)` using dedicated SQL and bounded row processing copied from `platform_operations_overview()`.
- `acquire_provider_monitoring_lease(...)` as one atomic upsert-returning statement.
- `complete_provider_monitoring_evaluation(...)` guarded by scheduler key and owner hash.
- `provider_monitoring_state()` returning a privacy-safe state model.

Run:

```powershell
python tools/test_jiejing_reliability_alert_lifecycle.py
python tools/test_jiejing_postgres_repository_cutover.py
python tools/test_jiejing_operations_metering.py
```

## Phase 3: Non-blocking worker-native scheduler and one aggregate export

### Files

- Modify `jiejing_saas/monitoring.py`.
- Modify `tools/jiejing_worker_cli.py`.
- Modify `jiejing_saas/api_server.py`.
- Extend `tools/test_jiejing_worker_cli_contract.py`.
- Extend `tools/test_jiejing_reliability_alert_api.py`.

### RED

Add tests proving:

- Scheduler configuration defaults to 300 seconds and is bounded to 60..3600.
- Reliability and cost windows default to 30 minutes and 24 hours.
- Disabled scheduler performs no lease/query/export work.
- Due execution obtains the durable lease, reads the focused snapshot, uses existing reliability classification/lifecycle, evaluates cost, builds one aggregate, exports at most once, and commits safe state.
- Lease contention returns a safe skipped outcome.
- Query failure and CLS failure are contained and classified without raising into the queue loop.
- A deliberately blocked fake scheduler/export does not delay a following `worker.run_next()` call.
- Shutdown does not wait indefinitely for a stuck export.
- The worker owns at most one monitoring future/thread at a time.
- The owner manual reconcile endpoint uses the same focused 30-minute snapshot rather than the old 30-day overview.

### GREEN

Implement `ProviderMonitoringScheduler` in existing `jiejing_saas/monitoring.py` so no new bundled file is needed. Responsibilities:

1. Parse bounded scheduler configuration.
2. Generate a per-process nonce from worker label, process start, PID and randomness; persist only its SHA-256 hash.
3. Check due state and acquire a short durable lease.
4. Read the focused snapshot.
5. Call existing `build_reliability_alert_summary()` and `reconcile_provider_reliability_alerts()`.
6. Call the new cost evaluator.
7. Build one safe aggregate event.
8. Attempt one bounded CLS export.
9. Persist evaluation/export success separately.

In `jiejing_worker_cli.py`, create a `ThreadPoolExecutor(max_workers=1)` or equivalent single daemon background runner once per worker process. The queue loop only schedules when no monitoring future is active and immediately continues to queue recovery/job processing. Poll completed futures without blocking. On shutdown, cancel pending work and use non-waiting executor shutdown.

Use explicit CLS connect/read timeouts. All scheduler logging must be a fixed allowlist of outcome/status/count fields and exception class only.

Change the owner reconcile endpoint to the same focused snapshot and existing lifecycle, preserving the internal-admin permission boundary.

Run:

```powershell
python tools/test_jiejing_worker_cli_contract.py
python tools/test_jiejing_reliability_alert_api.py
```

## Phase 4: Evidence-based monitoring readiness and public-safe propagation

### Files

- Modify `jiejing_saas/monitoring.py`.
- Modify `jiejing_saas/readiness.py`.
- Modify `jiejing_saas/production_release_gate.py`.
- Modify `jiejing_saas/production_evidence_ledger.py` only if a test proves propagation is insufficient.
- Extend `tools/test_jiejing_monitoring_runbook_gate.py`.
- Extend `tools/test_jiejing_production_release_gate.py`.
- Extend `tools/test_jiejing_production_evidence_ledger.py`.
- Extend `tools/test_jiejing_managed_infra_readiness_cutover.py`.
- Extend `tools/test_jiejing_tencent_cloud_integrations.py`.

### RED

Add a readiness matrix proving:

- The three legacy booleans alone cannot make provider observability ready.
- Scheduler disabled is blocked.
- Missing/invalid cost budgets are blocked.
- Missing, invalid, future-dated or stale evaluation/export evidence is blocked with a precise non-secret key.
- Missing, invalid, future-dated or stale latency/cost alarm read-back timestamps are blocked.
- Exact freshness boundaries are accepted.
- Fresh infrastructure evidence plus zero samples can make monitoring infrastructure ready while explicitly reporting `insufficient_data` and evaluated scope count zero.
- Raw evidence timestamps, alarm IDs and provider/cloud names are absent from monitoring status, release ledger and public readiness.
- Public `/readiness/product-saas` reflects a generic monitoring-evidence blocker without exposing internal diagnostics.

### GREEN

Change `_provider_observability_status()` to accept repository state and `now_utc`. Require all of:

- `JIEJING_PROVIDER_METRICS_ENABLED=true`;
- `JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED=true`;
- fresh successful evaluation state;
- fresh successful CLS export state;
- valid explicit warning/critical cost budgets;
- fresh latency alarm read-back timestamp;
- fresh cost alarm read-back timestamp;
- existing safe access log and CLS target readiness.

Add bounded configuration support for the approved environment keys. Keep old latency/cost booleans only as migration diagnostics; they may never prove ready.

Update production release `env_keys` and external evidence keys so the ledger inherits the new evidence contract without reimplementing freshness. Update public readiness to a generic aligned state while keeping detailed blockers on the internal-admin `/monitoring/status` endpoint.

Run:

```powershell
python tools/test_jiejing_monitoring_runbook_gate.py
python tools/test_jiejing_production_release_gate.py
python tools/test_jiejing_production_evidence_ledger.py
python tools/test_jiejing_managed_infra_readiness_cutover.py
python tools/test_jiejing_tencent_cloud_integrations.py
```

## Phase 5: Tencent CLS alarm operator, read-back evidence and private env path

### Files

- Modify `tools/jiejing_configure_tencent_runtime_env.py`.
- Modify `deploy/jiejing-saas.tencent-managed.env.example`.
- Modify `deploy/docker-compose.public-https-staging.yml` and other active compose variants consistently.
- Extend `tools/test_jiejing_configure_tencent_runtime_env.py`.
- Extend `tools/test_jiejing_tencent_cloud_integrations.py`.
- Extend `tools/test_jiejing_staging_patch_apply_contract.py` if compose assertions change.

### RED

With fake CLS clients, prove:

- Default/status and dry-run perform only DescribeIndex/DescribeAlarms.
- Dry-run reports create/modify/noop/blocked without IDs or query text.
- Apply is impossible without an explicit flag.
- Zero exact matches creates; one exact match modifies only differing documented fields; duplicate exact matches block.
- Create/modify is always followed by DescribeAlarms read-back.
- Read-back validates uniqueness, enabled `Status`, topic binding, query contract, time window, trigger count, alarm period and an existing notice route.
- The latency and cost query contracts both explicitly require `probe:false` and the relevant attention/critical status.
- Verification timestamps are written only after both independent read-backs pass.
- A failure never records a timestamp.
- No test notification is sent.
- The probe event contains only the safe aggregate schema, is searchable, and cannot match either alarm query.
- Existing fulltext-off index configuration is never rewritten.

### GREEN

Extend the existing configurator rather than adding another file:

- Add all approved provider monitoring keys to `KNOWN_KEYS` and redacted status groups.
- Add lazy SDK client construction using only the existing backend secret boundary.
- Add default read-back/status, explicit dry-run and explicit apply modes.
- Define deterministic latency/cost alarm names and query contracts from the shared event constants, with no merchant/provider fields.
- Use `DescribeAlarms` pagination up to a safe fixed limit and local exact-name matching.
- On apply, create/modify minimal documented fields, preserve the existing notice route on modify, and require an operator-provided existing notice reference for create without printing it.
- After successful read-back of both alarms, atomically update the two verification timestamps in the active private environment file.

Fix the active compose environment path: API and worker must consume the same private Tencent-managed env that the configurator updates, or deployment must explicitly target the currently consumed private env. Prefer adding the private Tencent-managed env to both API and worker `env_file` lists so scheduler/export configuration cannot drift, and update compose contract tests. Never print env values.

Update the env example with disabled/no-budget placeholders that preserve blocked readiness until explicit operator values are supplied.

Run:

```powershell
python tools/test_jiejing_configure_tencent_runtime_env.py
python tools/test_jiejing_tencent_cloud_integrations.py
python tools/test_jiejing_staging_patch_apply_contract.py
```

## Phase 6: Local release gates and immutable bundle proof

Run all targeted tests from Phases 1-5 first. Then run the fixed precloud gate without adding a check:

```powershell
python tools/jiejing_precloud_deployment_gate.py
```

Acceptance:

- exactly 107 checks discovered;
- exactly 107 passed;
- no skipped/failed checks;
- paid launch and public charging remain false unless their unrelated real evidence has changed independently;
- no real provider/network business calls occurred.

Generate the staging bundle using the existing builder, then verify:

- exactly 274 unique files;
- no missing whitelist entries;
- SHA256 computed independently with `Get-FileHash -Algorithm SHA256`;
- secret scan passes;
- bundle includes only the expected modifications.

Do not report success if the bundle count differs from 274.

## Phase 7: Safe deploy and live validation

### Pre-deploy cloud read-only checks

1. Run configurator status/read-back against CLS with no apply.
2. Confirm the existing index is enabled, fulltext remains off, and required aggregate keys are present.
3. Confirm alarm exact-name cardinality and existing notice route without printing IDs.
4. Confirm the live private env file is the one consumed by both API and worker without printing values.

If required index keys are missing, stop alarm apply and report the exact non-secret key names; do not overwrite the index automatically.

### Alarm configuration

1. Run dry-run and require a clean create/modify/noop plan.
2. Apply only the two provider aggregate alarms.
3. Read both back and validate their full contracts.
4. Record verification timestamps only after read-back success.
5. Upload one privacy-safe `probe=true` aggregate and confirm it is searchable.
6. Prove both alarm queries exclude the probe; do not send any notification test.

### Application deployment

1. Apply the 274-file bundle through the existing staging patch path with rollback backup.
2. Recreate API first.
3. With a browser-style User-Agent, verify valid-TLS HTTP 200 for:
   - `https://app.jiejing.shop/health`
   - `https://app.jiejing.shop/health/deep`
   - `https://app.jiejing.shop/readiness/product-saas`
4. Verify the independent ops origin remains isolated:
   - `https://ops.jiejing.shop/` returns valid TLS/200;
   - unauthenticated internal overview returns 401;
   - non-whitelisted ops path returns 404;
   - `https://app.jiejing.shop/ops.html` returns 404.
5. Recreate the worker only after API health is stable.
6. Verify API/worker/frontend container health and zero unexpected restarts.
7. Wait for one scheduler interval without blocking merchant queue work.
8. Verify a fresh evaluation and fresh CLS export are present through derived internal status, with no raw timestamp/ID leakage.
9. Re-run valid-TLS health/readiness after the worker interval.

### Honest final state

If cost budgets have not been explicitly supplied, or required CLS index/alarm/notice evidence cannot be proven, deployment may still complete with the mechanism safely installed, but `production_monitoring_ready` must remain false and the formal release gate must remain blocked. Report the exact non-secret blocker; do not invent a threshold or mark production ready.

## Definition of done

- Worker evaluates eligible passive telemetry every configured interval without calling a business provider.
- Queue processing is not delayed by monitoring query/export work.
- Multiple workers produce at most one evaluation per interval.
- Real-data filtering excludes synthetic, rehearsal, verification and controlled-acceptance traffic.
- No-data truth remains `insufficient_data`.
- Reliability uses the existing durable lifecycle; cost uses explicit operator budgets and complete coverage.
- CLS receives only the flat privacy-safe aggregate contract.
- Two alarm contracts are dry-run/apply/read-back verified and exclude probes.
- Legacy booleans cannot bypass freshness evidence.
- Public readiness stays generic; detailed diagnostics stay internal-admin only.
- Full local gate remains 107/107.
- Deployment bundle remains exactly 274 files with an independently verified SHA256.
- Live health, TLS, ops authorization and app/ops isolation all pass after deployment.
