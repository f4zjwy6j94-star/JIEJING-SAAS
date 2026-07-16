# Jiejing Passive Provider Monitoring Design

## Status

Approved on 2026-07-17. The selected approach is a worker-native passive monitoring scheduler. It does not initiate model, public-search, media-generation, payment or eBay requests.

## Context

Jiejing already records provider-neutral model usage, provider costs and sanitized reliability telemetry. It also has threshold classification, durable alert lifecycle state, an internal operations console and a Tencent CLS target. The missing production evidence is not another dashboard or another one-time probe. The missing link is a continuously running evaluator that consumes existing real-business telemetry, publishes a privacy-safe aggregate heartbeat and proves that latency and cost alarms remain configured.

The production environment currently has no eligible real-merchant provider samples. No-data state must remain `insufficient_data`; it must never be reported as healthy. The fixed 107-check gate and the formal production release gate remain separate. This work must not alter paid-launch, public-charging, real-platform-write or eBay authorization truth.

## Goals

1. Evaluate real-business provider telemetry automatically every five minutes inside the existing worker.
2. Reuse the current provider-neutral reliability thresholds and durable alert lifecycle instead of creating a parallel system.
3. Add a cost-coverage and 24-hour cost-budget evaluation without inventing a business budget.
4. Publish one allowlisted aggregate CLS event per completed evaluation.
5. Require fresh scheduler, CLS-export and cloud-alarm evidence before provider observability can be production-ready.
6. Keep failures isolated from merchant task processing and keep all provider calls passive.

## Non-goals

- Do not issue synthetic requests to model, search, media or payment providers.
- Do not perform eBay OAuth, refresh, reads or writes.
- Do not charge, refund, purchase, advertise, change price, change inventory or edit marketplace policies.
- Do not expose monitoring, provider names, cost internals or cloud diagnostics to merchants.
- Do not store prompts, replies, search queries, product data, merchant identifiers, order identifiers, raw errors, credentials or cloud resource identifiers.
- Do not treat an internal aggregate probe as proof of real provider performance.
- Do not change the fixed productization progress ranges or infer paid-launch readiness from this feature alone.

## Selected architecture

### Worker-native scheduler

The existing worker owns a `ProviderMonitoringScheduler`. The worker checks the scheduler on its normal loop, while the scheduler runs at most once every 300 seconds. The interval is configurable and bounded between 60 and 3600 seconds. An optional initial jitter prevents multiple workers from competing immediately after a deployment.

The scheduler is not allowed to call an external business provider. Its only remote operation is an optional upload of one aggregate event to the already configured CLS topic.

### Durable singleton lease and state

Add a dedicated scheduler-state table keyed by a constant scheduler name. It stores only operational fields:

- lease owner hash and lease expiry;
- last evaluation start and completion times;
- last CLS export success time;
- last safe error class;
- last result status and contract version;
- a redacted aggregate snapshot with no merchant or provider content.

Lease acquisition must be atomic in both SQLite tests and Postgres staging. A lease expires automatically so a terminated worker cannot block future evaluations. Duplicate workers that lose the lease skip the evaluation without treating it as an error.

### Dedicated aggregate query

Add a focused repository query instead of invoking the full operations-console overview. It reads:

- a rolling 30-minute reliability window for model, public search, media generation and payment;
- a rolling 24-hour platform-paid model and provider-cost window;
- cost coverage, unmetered current tasks and unknown-cost record counts.

The query keeps the existing data-quality rules: synthetic accounts, rehearsals, acceptance payments and non-commercial records do not qualify as real-business telemetry.

## Evaluation rules

### Reliability

Reuse `build_reliability_alert_summary()` and the existing threshold contracts. Preserve the current rules:

- fewer than five eligible requests produces `insufficient_data`;
- attention or critical status requires the configured latency, failure or timeout threshold;
- two consecutive breaches are required to open an alert;
- two consecutive healthy evaluations are required to recover;
- acknowledgements and lifecycle events remain internal-owner operations.

The scheduler calls the existing durable reconciliation contract with a system actor. It does not bypass the existing deduplication or recovery behavior.

### Cost

Add a provider-neutral cost evaluator with separate data-quality and budget signals:

- unknown provider-cost records, unknown platform-model cost records or current unmetered work produce `cost_coverage_incomplete`;
- a configured 24-hour warning threshold produces attention when reached;
- a configured higher critical threshold produces critical status when reached;
- the critical threshold must be greater than the warning threshold;
- missing, invalid, non-finite or non-positive budget thresholds produce `provider_cost_budget_not_configured` and keep production readiness blocked.

No default monetary budget is invented. The mechanism can be implemented and deployed while formal readiness remains blocked until an operator sets explicit minor-unit thresholds.

Evaluation priority is fixed. Invalid or missing budget configuration is a readiness blocker first. With valid budgets, incomplete cost coverage produces attention before numeric spend thresholds are evaluated. With complete coverage, the critical threshold takes precedence over the warning threshold; otherwise the cost state is healthy. Exactly equal to a threshold counts as reached.

### No-data truth

No eligible requests produces `insufficient_data`, not `healthy`. An insufficient-data heartbeat proves only that the scheduler, aggregate query and CLS path are alive. It does not prove real provider latency or reliability.

## CLS aggregate contract

Each completed evaluation emits at most one flat, allowlisted event:

- event contract and event type;
- environment;
- evaluation status;
- reliability overall status;
- cost overall status;
- aggregate request, failure and timeout counts;
- maximum observed p75 duration bucket;
- 24-hour cost total in minor units;
- cost coverage complete boolean;
- budget configured boolean;
- evaluation window sizes;
- `probe=false` for scheduler output;
- `secret_exposed=false`.

The event contains no IDs tied to merchants, users, stores, orders, tasks, providers or cloud resources. Detailed per-scope analytics remain inside the internal database and owner-only console.

Full-text indexing remains disabled. Add only the minimum key-value index fields required by the two alarm queries. The latency alarm matches real scheduler events with attention or critical reliability status. The cost alarm matches real scheduler events with attention or critical cost status. Both alarm queries explicitly exclude `probe=true`.

## Cloud configuration and verification

Add an operator tool with dry-run as the default and an explicit apply mode. It:

1. verifies the configured topic and minimum key-value index without printing identifiers;
2. creates or updates one latency alarm and one cost alarm;
3. binds the existing internal notice route without printing the notice identifier;
4. reads both alarms back and validates their enabled state and query contract;
5. records verification timestamps only after successful read-back;
6. never sends a test notification.

A privacy-safe `probe=true` aggregate can be uploaded and found with SearchLog to prove ingestion. Because alarm queries exclude probes, this validation cannot open an operational alert or notify anyone.

## Configuration

Add backend-only configuration keys:

- `JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED`
- `JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS` (default 300; range 60 to 3600)
- `JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES` (default 30)
- `JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS` (default 24)
- `JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES` (default 15)
- `JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR`
- `JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR`
- `JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT`
- `JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT`
- `JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS` (default 7)

Existing `JIEJING_PROVIDER_METRICS_ENABLED`, `JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED` and `JIEJING_PROVIDER_COST_ALERTS_CONFIGURED` keys remain readable during migration, but their boolean values alone can no longer prove readiness when the scheduler is required.

## Monitoring readiness

Provider observability is ready only when all of the following are true:

1. provider metrics and the passive scheduler are enabled;
2. the last evaluation completed within the configured freshness window;
3. the last aggregate CLS export succeeded within the freshness window;
4. explicit cost warning and critical thresholds are valid;
5. latency and cost alarm read-back evidence is valid, not future-dated and no older than the alarm-verification maximum age;
6. the existing CLS target and safe-access-log requirements are ready.

Missing samples do not block monitoring-infrastructure readiness, but the status must expose `insufficient_data` and a zero evaluated-scope count. Missing configuration or stale evidence does block readiness with precise, non-secret blocker keys.

## Failure handling

- Aggregate query failure: record only the exception class, release or expire the lease and retry on the next interval.
- CLS upload failure: retain the completed local evaluation, do not advance last-export success and keep readiness blocked when evidence becomes stale.
- Alarm verification failure: do not record a verification timestamp and do not mark the corresponding alarm configured.
- Invalid cost budget: do not weaken the gate and do not emit a false healthy cost status.
- Worker shutdown: no special cleanup is required beyond best-effort lease release because the lease expires.
- Scheduler failure must never fail, retry or delay a merchant queue job.

## Security and privacy

- Use an explicit event-field allowlist; reject unknown fields before serialization.
- Never serialize request bodies, headers, URLs, raw log text, prompts, replies or provider responses.
- Credentials remain in the current private environment boundary and are read only by the backend SDK.
- Output, tests, deployment logs and evidence documents expose only booleans, counts and blocker names.
- The operations console remains owner/admin only, and the merchant application does not receive scheduler state or alert details.

## Testing

### Unit and repository tests

- interval bounds and injected-clock behavior;
- atomic lease acquisition, contention, expiry and recovery;
- no-data remains insufficient;
- healthy, attention, critical, recovery and duplicate reconciliation;
- incomplete cost coverage and missing budget blockers;
- valid warning/critical budget thresholds and threshold ordering;
- safe event allowlist and forbidden-data scans;
- SQLite and Postgres-compatible timestamp/JSON queries.

### Worker and API tests

- worker periodically invokes the scheduler without delaying queue work;
- two workers produce one evaluation per interval;
- query or CLS failures do not crash the worker;
- owner-only status exposes derived state and merchant endpoints do not;
- manual booleans cannot bypass stale or missing live evidence.

### Cloud and deployment tests

- operator tool defaults to dry-run;
- apply mode is idempotent and does not print resource identifiers;
- alarm read-back validates both query contracts;
- probe event is searchable and excluded from alarm queries;
- no test notification is sent;
- targeted tests and the complete 107-check gate pass before packaging.

## Deployment sequence

1. Run targeted monitoring, operations-metering, reliability-lifecycle, worker and production-release tests.
2. Run the complete 107-check precloud gate.
3. Create and independently hash a 274-file staging bundle.
4. Deploy with a rollback point.
5. Apply private scheduler configuration without printing values.
6. Configure and read back the two CLS alarms.
7. Run one alarm-excluded aggregate ingestion probe.
8. Recreate API, verify valid-TLS health, then recreate worker.
9. Verify scheduler evaluation and CLS-export freshness, container restart counts, operations-console isolation and public readiness truth.
10. Update evidence without raw timestamps, identifiers or credentials.

## Acceptance criteria

- The worker evaluates passive provider telemetry continuously without calling a business provider.
- Multiple workers cannot duplicate an interval evaluation.
- No-data state remains insufficient and cannot be presented as healthy provider performance.
- One privacy-safe aggregate event reaches CLS per completed interval.
- Latency and cost alarm configuration is proved by read-back, not by manual booleans.
- Stale evaluation, stale export, stale alarm evidence or invalid cost budgets block provider observability.
- Merchant workflows, eBay state, charging state and real-platform-write state remain unchanged.
- Full local gates, staging deploy, valid TLS, internal-console isolation and zero-restart verification pass.
