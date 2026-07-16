# Jiejing CLS Probe Evidence Freshness Implementation Plan

## Objective

Implement the approved 24-hour CLS evidence freshness design without changing merchant behavior, paid-launch truth, real-platform write policy, or the current dirty-worktree baseline. Finish with a new staging bundle, live privacy-safe probes, sequential service reload and refreshed evidence.

## Safety invariants

- Never reset, clean, checkout, stash or broadly format the worktree.
- Never run eBay OAuth, eBay writes, charges, refunds, ads, procurement, price, inventory or policy mutations.
- Never print private environment values, resource identifiers, credentials or log bodies.
- Keep `production_monitoring_ready=false` while provider latency/cost alert evidence is absent.
- Keep the formal production gate at its evidence-derived value; do not infer progress from code changes.

## Phase 0 — Documentation discovery and allowed patterns

### Sources

- Approved behavior: `docs/superpowers/specs/2026-07-16-cls-probe-evidence-freshness-design.md:1`
- Existing CLS contract: `jiejing_saas/monitoring.py:256`
- Existing production freshness pattern: `jiejing_saas/backup_plan.py:178`
- ISO-aware timestamp parsing: `jiejing_saas/backup_plan.py:270`
- Finite numeric fallback: `jiejing_saas/backup_plan.py:257`
- Current configurator status/blockers: `tools/jiejing_configure_tencent_runtime_env.py:306`
- Monitoring regression entry: `tools/test_jiejing_monitoring_runbook_gate.py:52`
- Tencent integration matrix pattern: `tools/test_jiejing_tencent_cloud_integrations.py:146`
- Bundle/deploy whitelist: `deploy/apply-staging-patch.sh:19`

### Allowed APIs and patterns

- `datetime.fromisoformat(value.replace("Z", "+00:00"))` for ISO parsing.
- Reject timestamps whose `tzinfo` is missing; normalize aware values with `astimezone(timezone.utc)`.
- `math.isfinite()` plus `value > 0` for the CLS maximum-age configuration.
- One shared `datetime.now(timezone.utc)` value per status build, injected into a pure helper.
- Determine freshness using the unrounded age; round only the exposed age field.
- Use explicit `if/elif` priority for missing, invalid, future and stale blockers.

### Anti-pattern guards

- Do not make Tencent Cloud calls from health/readiness/monitoring status builders.
- Do not copy the backup helper's maximum bound; the approved CLS contract accepts any positive finite value.
- Do not use fixed calendar timestamps in tests.
- Do not include the design or plan documents in the 274-file runtime whitelist.
- Do not assume `/opt/jiejing-staging/private/tencent-managed.env` is consumed by containers; verify and update the actual env source by key presence only.

## Phase 1 — Core monitoring contract, test first

### RED: observable behavior

Update `tools/test_jiejing_monitoring_runbook_gate.py` one behavior at a time:

1. Add `JIEJING_CLS_PROBE_MAX_AGE_HOURS` to the environment cleanup set.
2. Replace fixed timestamps with values relative to one current UTC time.
3. Add a stale control-plane case and assert `tencent_cls_live_probe_stale` plus `target_ready=false`.
4. Add a stale ingestion case and assert `tencent_cls_ingestion_live_probe_stale`.
5. Add invalid and more-than-five-minute-future cases for both timestamps.
6. Test exact-threshold freshness through the public `build_monitoring_status(..., now_utc=...)` testability hook rather than wall-clock drift.
7. Test custom positive threshold and invalid/non-finite/non-positive fallback to 24.
8. Preserve provider latency/cost blockers and the serialized secret-marker scan.

Run after each tracer bullet:

```powershell
python tools\test_jiejing_monitoring_runbook_gate.py
```

### GREEN: production code

In `jiejing_saas/monitoring.py`:

1. Add `math`, `datetime`, `timezone` imports and constants for 24 hours and five-minute future skew.
2. Add an optional keyword-only `now_utc` parameter to `build_monitoring_status`; production callers omit it and tests can supply a fixed aware UTC value.
3. Add a pure `_timestamp_evidence_status(value, max_age_hours, now_utc)` helper.
4. Add a positive-finite environment float parser with a 24-hour fallback.
5. Evaluate both CLS timestamps against one UTC `now`.
6. Emit one blocker per timestamp in the approved priority order.
7. Change `control_plane_ready` and `target_ready` to require fresh evidence when live probes are required.
8. Expose the approved non-secret validity/future/freshness/age/max-age fields while keeping existing fields.

### Verification

- Monitoring test passes.
- `git diff --check` has no errors.
- No provider alert flags or launch switches are changed.

## Phase 2 — Configurator and environment contract, test first

### RED

Extend `tools/test_jiejing_configure_tencent_runtime_env.py`:

1. Apply CLS configuration with an explicit 24-hour threshold.
2. Confirm ordinary control-plane recording does not fabricate ingestion evidence.
3. Confirm recent verified timestamps clear CLS freshness blockers.
4. Rewrite the temporary private env with stale, invalid and future timestamps and check precise redacted blockers.
5. Confirm invalid/non-finite/non-positive stored thresholds fall back to 24.
6. Preserve all existing secret-output sentinel checks.

### GREEN

In `tools/jiejing_configure_tencent_runtime_env.py`:

1. Add the max-age key to `KNOWN_KEYS`.
2. Add `--cls-probe-max-age-hours`; validate CLI input as positive and finite before writing.
3. When a CLS enable/probe action occurs, persist the explicit normalized threshold, defaulting to 24.
4. Add standalone stdlib timestamp/freshness helpers that mirror the runtime rules without importing the SaaS runtime.
5. Add a derived, redacted CLS evidence status object and matching blocker priority.
6. Keep raw secret/resource output behavior unchanged.

Update `deploy/jiejing-saas.tencent-managed.env.example` with:

```dotenv
JIEJING_CLS_PROBE_MAX_AGE_HOURS=24
```

Update `jiejing_saas/production_release_gate.py:355` so the monitoring evidence environment-key list includes the live-probe requirement, both timestamps, ingestion pass flag and max age.

### Verification

```powershell
python tools\test_jiejing_configure_tencent_runtime_env.py
python tools\test_jiejing_production_release_gate.py
```

## Phase 3 — Tencent integration regression

Update `tools/test_jiejing_tencent_cloud_integrations.py`:

1. Add the max-age key to environment cleanup.
2. Replace fixed May timestamps with recent values relative to the test UTC time.
3. Snapshot stale, invalid, future, exact-threshold, custom-threshold and fallback behavior.
4. Assert the CLS target is ready only for fresh evidence.
5. Preserve backup/restore freshness assertions and secret scans.

Verification:

```powershell
python tools\test_jiejing_tencent_cloud_integrations.py
python tools\test_jiejing_monitoring_runbook_gate.py
python tools\test_jiejing_configure_tencent_runtime_env.py
python tools\test_jiejing_production_release_gate.py
python tools\test_jiejing_staging_patch_apply_contract.py
```

## Phase 4 — Full local release verification

1. Run `git diff --check` and inspect only task-related diffs.
2. Run the complete precloud gate:

```powershell
python tools\jiejing_precloud_deployment_gate.py
```

3. Require all 107 checks to pass and retain paid launch/writes/secret flags as false.
4. Generate a new bundle with `tools/jiejing_prepare_public_staging_bundle.py`.
5. Require exactly 274 files and independently recalculate the zip SHA256.

Anti-pattern: the 107 gate does not directly replace the Tencent integration or configurator tests, so targeted tests must run first.

## Phase 5 — Safe staging deploy and live evidence refresh

1. Deploy through `tools/jiejing_staging_deploy.py` and retain the reported rollback point.
2. Verify deployed task-file SHA256 values match local files.
3. Read only key-presence booleans from the two private env files; never print values.
4. Run the existing live CLS control-plane/index/alarm query checks.
5. Upload one privacy-safe synthetic event and confirm it through `SearchLog`; output only counts/booleans.
6. Record both current timestamps and max age in every private env file actually consumed by API and worker. Do not rely on the configurator default path alone.
7. Recreate API first, verify `https://app.jiejing.shop/health` with valid TLS, then recreate worker.

### Live verification

- `/health`, `/health/deep`, `/readiness/product-saas`: HTTP 200, TLS verify result 0.
- `ops.jiejing.shop/`: HTTP 200 with valid TLS.
- Unauthenticated operations overview: HTTP 401.
- Main-site `/ops.html`: HTTP 404.
- Cloudflare DoH for `ops.jiejing.shop`: status 0 and expected A record.
- API, worker and frontend: running, restart count 0.
- Runtime CLS status: control plane fresh, ingestion fresh, CLS blockers empty.
- Production monitoring remains false while latency/cost alert blockers remain.

## Phase 6 — Evidence closure and completion audit

Update:

- `docs/JIEJING_PRODUCTION_EVIDENCE_20260716.md`
- `output/jiejing-production-evidence-20260716-summary.json`

Record the new bundle, SHA256, rollback point, 24-hour threshold, timestamp validity/freshness booleans, synthetic match count and unchanged launch truth. Do not write raw timestamps, cloud IDs or credentials into evidence.

Final checks:

```powershell
python -m json.tool output\jiejing-production-evidence-20260716-summary.json
python tools\test_jiejing_production_evidence_ledger.py
python tools\test_jiejing_fixed_launch_progress.py
python tools\test_jiejing_version_bound_release_evidence.py
git diff --check
```

The objective is complete only when the deployed runtime proves fresh CLS evidence, all required tests pass, live surfaces remain healthy and isolated, and no forbidden write/charge/launch action occurred.
