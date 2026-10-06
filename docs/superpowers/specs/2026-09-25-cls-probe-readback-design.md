# CLS probe readback correction

Scope approved by the user's 2026-09-25 fixed-MVP-closeout request. The single progress and acceptance index remains `docs/JIEJING_CURRENT_EXECUTION_STATE.md` (R1). This document defines the narrow correction, not a parallel launch status.

## Evidence and decision

The existing verifier waits only twice for two seconds, and accepts any non-empty `SearchLog.Results`. Local injected reproductions demonstrated both a fourth-read false negative and acceptance of an old unrelated row. These do not prove every historic production failure had that cause.

Tencent documents API/SDK ingestion-to-search latency up to one minute, and `LogInfo.FileName`, `Time` (milliseconds), and `LogJson` as returned search metadata:

- https://cloud.tencent.com/document/product/614/86845
- https://cloud.tencent.com/document/api/614/56471 (LogInfo)

Alternatives: adding only retries leaves false verification; a thirteenth event field expands all aggregate and alarm contracts. Selected: preserve all 12 aggregate fields and put a random per-run marker in the existing protobuf log-group filename metadata. This marker contains no account, host, topic, credential, or product data. Passive scheduled aggregates remain unchanged.

## Contract

- Upload at most one probe; never re-upload during retries. No notification or business-provider request.
- Production adapter accepts only `jiejing-provider-probe-` plus 32 lowercase hex characters, only when `probe is True`. No arbitrary filename or merchant data.
- Read back up to 20 rows from the existing probe-only indexed query. Validate exact filename marker, same topic, current upload-time window, and all 12 serialized aggregate values from bounded `LogJson`. Do not print returned rows or markers. Unknown/malformed/old/other-run rows cannot verify.
- Default up to 13 read attempts, waits of at most 5 seconds, with a 75-second monotonic retry deadline. Every actual SDK request is already bounded to 10 seconds. Stop on deadline/exhaustion/error; missing proof stays blocked. One in-flight request can finish after the retry deadline, but no additional attempt starts then.
- Only successful identity readback refreshes environment evidence. Upload/query/parse failure cannot change existing evidence timestamps. Existing shell consumers retain the 12-field and allowlist checks.
- No billing, eBay, tenant, entitlement, design, index, alarm, credential, or infrastructure changes.

## Implementation and verification

1. RED: add a regression that unrelated non-empty results must not verify; minimal exact-identity fix and update success fixtures with real response shape.
2. RED: delayed visibility beyond the old window; bounded retry fix. Cover last attempt, exhaustion, deadline, upload failure, query failure, stale/wrong/malformed records, row ordering, and no raw-output leak using injected API/time boundaries only.
3. Exercise the real protobuf upload adapter with a fake network client, including metadata propagation and rejection; test the CLI's evidence-write boundary with temporary synthetic env files. Run related monitoring/refresh/deployment contracts.
4. Review the fixed MVP acceptance list, freeze the final scope, then run one clean same-source full gate and existing deployment workflow. This document itself is not a production-verification claim.

## Local evidence (2026-09-25)

- Both reported defects were observed failing before their respective implementation change; current regressions pass through the last permitted retry and reject exhaustion, deadline, unrelated and malformed readback.
- Real repository protobuf serialization/deserialization verifies the filename metadata and unchanged twelve-field aggregate, with only the network client replaced. CLI tests use temporary synthetic inputs and confirm upload/query failures leave evidence byte-for-byte unchanged and stdout sanitized.
- `test_jiejing_configure_tencent_runtime_env.py`, `test_jiejing_worker_cli_contract.py`, both CLS/production evidence refresh guardrail suites, staging patch contract, production deployment channel, secret scan, JavaScript syntax and whitespace checks passed locally.
- The local Python lacked protobuf; the exact existing production lockfile package protobuf 5.29.6 was installed into an ignored test-only directory using both committed hashes and `--require-hashes --no-deps`. Production requirements and dependency versions are unchanged. Full-gate subprocesses must inherit that test dependency path.
- The runtime configurator regression is now part of the full precloud gate exactly once; final same-source gate and production identity verification remain required.
