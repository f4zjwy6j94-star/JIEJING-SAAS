# Jiejing CLS Probe Evidence Freshness Design

## Status

Approved approach A on 2026-07-16. This specification covers monitoring evidence truth only.

## Goal

Prevent a successful Tencent CLS control-plane or ingestion probe from remaining valid forever. Production-like monitoring must require recent, parseable and non-future evidence before the CLS target can be considered ready.

## Non-goals

- Do not add a continuous CLS exporter or new provider latency/cost alarms.
- Do not call Tencent Cloud from `/health`, `/health/deep`, `/readiness/product-saas` or `/monitoring/status`.
- Do not record raw prompts, replies, merchant content, supplier names, credentials or cloud resource identifiers.
- Do not enable real eBay writes, charges, refunds, ads, procurement, price, inventory or policy changes.
- Do not change the fixed productization progress ranges or treat beta readiness as paid-launch readiness.

## Configuration

- Add `JIEJING_CLS_PROBE_MAX_AGE_HOURS` with a default of `24` hours.
- Accept a positive finite numeric value; invalid, non-finite or non-positive values fall back to `24`.
- Both `JIEJING_CLS_LIVE_PROBE_LAST_AT` and `JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT` use the same threshold.
- Permit at most five minutes of clock skew into the future.
- Accept timezone-aware ISO 8601 timestamps, including a trailing `Z`. Reject timezone-naive timestamps.
- Evidence exactly at the configured maximum age is fresh; evidence older than the maximum is stale.

## Architecture

Add a small internal timestamp-evidence helper in `jiejing_saas/monitoring.py`. It receives a timestamp string, the configured maximum age and the current UTC time, and returns only derived status fields:

- timestamp present
- timestamp valid
- timestamp in the future
- timestamp fresh
- age in hours when calculable
- configured maximum age in hours

The helper performs no network or database I/O. `_cls_monitoring_target_status()` evaluates control-plane and ingestion evidence independently and composes their results into the existing CLS monitoring target.

The private environment configurator mirrors the same rules in its redacted status output so an operator sees the same blocker before restarting containers. The configurator continues to record timestamps only after an explicit operational probe command.

## Readiness rules

When `JIEJING_CLS_LIVE_PROBE_REQUIRED=true`, CLS target readiness requires all of the following:

1. CLS is enabled and its region, logset, topic and alert-policy evidence are configured.
2. The control-plane probe timestamp is present, valid, not more than five minutes in the future and no older than the configured maximum age.
3. The ingestion probe passed flag is true.
4. The ingestion probe timestamp is present, valid, not more than five minutes in the future and no older than the configured maximum age.

When the live-probe requirement is false, the existing non-live configuration behavior remains unchanged. Production deployments keep the requirement enabled.

## Blockers

Keep existing missing-evidence blockers and add precise blockers for each failure class:

- `tencent_cls_live_probe_timestamp_invalid`
- `tencent_cls_live_probe_timestamp_in_future`
- `tencent_cls_live_probe_stale`
- `tencent_cls_ingestion_live_probe_timestamp_invalid`
- `tencent_cls_ingestion_live_probe_timestamp_in_future`
- `tencent_cls_ingestion_live_probe_stale`

Only one blocker is emitted per timestamp, in the priority order missing, invalid, future, stale. No blocker includes the timestamp value or a cloud resource identifier.

## Status contract

Expose the following non-secret evidence fields under `cloud_monitoring`:

- `live_probe_timestamp_valid`
- `live_probe_timestamp_in_future`
- `live_probe_fresh`
- `live_probe_age_hours`
- `ingestion_live_probe_timestamp_valid`
- `ingestion_live_probe_timestamp_in_future`
- `ingestion_live_probe_fresh`
- `ingestion_live_probe_age_hours`
- `live_probe_max_age_hours`

Existing fields remain compatible. `target_ready` becomes false whenever required evidence is missing, invalid, future-dated or stale.

## Operational data flow

1. An operator performs the existing read-only CLS control-plane checks.
2. The operator uploads one privacy-safe synthetic event and confirms it with `SearchLog`.
3. Only after both checks succeed, the private configurator records the control-plane and ingestion timestamps.
4. Containers reload the private environment sequentially: API first, verify valid TLS health, then worker.
5. Monitoring status derives freshness locally on every request without contacting Tencent Cloud.

## Failure behavior

- Timestamp parse failures block CLS readiness without crashing health or readiness endpoints.
- Future timestamps beyond the clock-skew allowance block readiness.
- Stale timestamps block readiness and direct the operator to rerun the privacy-safe probes.
- An invalid maximum-age setting falls back to 24 hours instead of weakening the gate.
- Provider latency/cost alert blockers remain unchanged; fresh CLS evidence alone must not make production monitoring ready.

## Tests

Use timestamps relative to the test's current UTC time so tests do not expire by calendar date. Cover:

- recent control-plane and ingestion evidence passes the CLS target boundary;
- stale control-plane evidence blocks readiness;
- stale ingestion evidence blocks readiness;
- invalid control-plane and ingestion timestamps block readiness;
- timestamps more than five minutes in the future block readiness;
- exactly-at-threshold evidence remains fresh;
- a custom maximum age is honored;
- invalid, non-finite or non-positive maximum-age configuration falls back to 24 hours;
- provider latency/cost blockers remain present;
- serialized monitoring status contains no secret markers.

Run the targeted monitoring, Tencent integration, configurator and production-release tests, then the complete 107-check precloud gate before deployment.

## Deployment and evidence

- Produce a new 274-file public staging bundle and verify its SHA256.
- Deploy through the existing SSH staging workflow and retain its rollback point.
- Refresh both CLS probe timestamps only after the live control-plane and synthetic ingestion checks pass again.
- Recreate API and worker sequentially, then verify `/health`, `/health/deep`, `/readiness/product-saas`, operations-console isolation, DNS and zero container restarts.
- Update the July 16 production evidence document and JSON summary without changing formal `3/8` production-gate truth unless independent evidence changes.

## Acceptance criteria

- A once-successful but older-than-threshold CLS probe cannot keep `target_ready=true`.
- Current privacy-safe probe evidence makes the CLS target ready after deployment.
- `production_monitoring_ready` remains false until provider latency and cost alarms are independently configured and verified.
- No real platform write, charge or public paid-launch switch is triggered.
