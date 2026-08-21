# Jiejing CLS Probe Auto-Refresh Design

## Status

The user approved scheme B on 2026-08-21. The design is approved; this written specification awaits the final review gate before implementation.

## Context

Jiejing requires recent Tencent CLS control-plane and ingestion evidence. Both evidence timestamps expire after 24 hours. On 2026-08-21 the existing evidence was slightly older than 24 hours, which made monitoring incomplete even though the application, database, queue, worker, CLS alarms and passive provider monitor remained healthy.

The existing probe command failed when run with the host system Python because the host does not contain the Tencent Cloud Python SDK. The deployed `deploy-jiejing-saas` image does contain the SDK. Running the same allowlisted probe from that image succeeded: the probe was uploaded, found by `SearchLog`, excluded by both alarm queries, and recorded without exposing secrets or resource identifiers.

## Goal

Refresh the existing privacy-safe CLS evidence every 12 hours without a human Tencent Cloud login, while preserving the 24-hour freshness gate and all current paid-launch, eBay, payment and real-write safeguards.

## Non-goals

- Do not call eBay OAuth, token refresh, read, draft-save or publish endpoints.
- Do not call model, search, media, payment, charge or refund providers.
- Do not send a notification or create an operational alarm.
- Do not increase the 24-hour freshness threshold.
- Do not install an SDK on the server host.
- Do not expose environment values, cloud resource identifiers, tokens, merchant content or probe timestamps in workflow logs.
- Do not mark paid launch ready or enable public charging or real-platform writes.

## Selected architecture

### Scheduled maintenance workflow

Add a dedicated GitHub Actions workflow with:

- `schedule: "17 */12 * * *"`, avoiding the top of the hour;
- `workflow_dispatch` for a controlled manual refresh;
- `permissions: contents: read`;
- the existing `[self-hosted, jiejing-staging]` runner;
- one non-cancelling concurrency group;
- a ten-minute timeout;
- checkout with full history followed by one dedicated maintenance script.

The workflow performs no deployment and does not accept user-supplied paths, commands, resource IDs or environment values.

### Trusted live-release boundary

The maintenance script resolves fixed paths below `/opt/jiejing-staging` and fails closed unless:

1. the application, deploy root, private environment and live Compose file resolve inside the expected staging root and are not symbolic links;
2. the private environment is a regular root-controlled file and is not group/world readable or writable;
3. the current checkout SHA exactly matches the latest applied release manifest SHA;
4. the running API container belongs to the expected Compose project and service;
5. the image, working directory and Compose file labels match the live deployment;
6. the deployed image contains the existing probe tool and Tencent SDK;
7. the trusted runtime-environment overlap guard passes for API and worker.

Any mismatch exits non-zero before a probe, environment write or container recreation.

### Probe execution

Run one ephemeral container from the exact image used by the running API service. Mount the server-private directory only for the duration of the command and execute the deployed probe tool against `tencent-managed.env`:

```text
--verify-provider-cls-probe --apply
```

The existing tool remains the single owner of the probe event and timestamp update. Success requires all of the following:

- the exact 12-field allowlist;
- `probe=true`;
- successful upload;
- successful `SearchLog` read-back;
- both alarm queries explicitly exclude the probe;
- no notification sent;
- no resource identifier or secret exposed;
- exactly the three existing evidence keys updated.

The maintenance wrapper never parses or prints the private environment.

### Runtime reload

After a verified probe, recreate only `jiejing-saas` and `jiejing-worker` from the exact live Compose project and file. Do not restart Vault, frontend or Cloudflare. Recreate the API first, wait for its container health check and public `/health` plus `/health/deep`, then recreate the worker and wait for its ready evidence.

Finally verify:

- `/health` is HTTP 200 with database startup ready;
- `/health/deep` is HTTP 200 with database, queue and worker ready;
- `/readiness/product-saas` reports its `monitoring_alerting` item as `cloud_monitoring_ready` and remains otherwise truthful;
- real and requested platform writes are false;
- public charging is not enabled;
- `secret_exposed=false`.

The scheduled workflow does not use a merchant or operations-console session. An operator may separately verify the authenticated monitoring detail after deployment, but the unattended job relies only on the public value-free health and readiness contracts.

## Failure behavior

- Missing SDK, path drift, SHA drift, label drift, unsafe permissions or runtime-guard failure: exit before the probe.
- Probe upload or search failure: do not update evidence and do not restart containers.
- Environment update succeeds but API recreation fails: exit non-zero and leave the worker untouched.
- API becomes unhealthy after recreation: exit non-zero and leave the worker untouched.
- Worker recreation or health verification fails: exit non-zero; do not repeat the probe or any business operation.
- A failed scheduled run must remain visible as a failed GitHub Actions run. No automatic retry loop is added.

The next scheduled run or a manually dispatched run may try again. The existing 24-hour gate continues to turn stale evidence into an explicit monitoring blocker.

## Security and privacy

- Use only fixed absolute server paths and exact Compose labels discovered from the live API container.
- Do not interpolate workflow inputs into shell commands.
- Do not use `set -x`, print environment variables or copy the private environment into the GitHub workspace.
- Keep the ephemeral container's lifetime limited to the probe command and remove it automatically.
- Keep the probe event incapable of matching operational alerts.
- Emit only value-free markers such as `PROBE_STATUS`, `API_HEALTH`, `WORKER_HEALTH`, `BLOCKERS`, and `SECRET_EXPOSED=false`.
- Keep all eBay, payment, provider-business and real-write flags unchanged.

## Tests

Use test-driven vertical slices through the public maintenance-script and workflow contracts:

1. RED then GREEN: the workflow has the exact schedule, runner, permissions, timeout, concurrency and script entrypoint.
2. RED then GREEN: unsafe or missing paths, symbolic links, weak private-file permissions and non-exact release SHA block before Docker execution.
3. RED then GREEN: wrong Compose project/service/image/working-directory labels or missing SDK/tool block before the probe.
4. RED then GREEN: a verified probe causes exactly one API recreation followed by one worker recreation.
5. RED then GREEN: blocked or malformed probe output causes zero recreations.
6. RED then GREEN: API health failure prevents worker recreation.
7. RED then GREEN: public readiness verification rejects a non-ready monitoring item, real writes, public charging or secret exposure.
8. Mutation checks: attempts to add eBay, payment, provider-business calls, `set -x`, environment dumps, arbitrary workflow inputs or a broader freshness threshold fail the contract.

Run the focused workflow/guard tests, shell syntax check, secret scan, deployment guardrails and the complete precloud gate before deployment.

## Deployment sequence

1. Commit this specification only.
2. Implement the workflow, maintenance script and focused contracts using vertical RED-GREEN cycles.
3. Run focused checks and the complete precloud gate.
4. Obtain an independent read-only review of the frozen tree.
5. Commit and push the exact approved files.
6. Run pre-Doctor, dry-run, apply and post-Doctor for the exact SHA.
7. Manually dispatch the new maintenance workflow once.
8. Verify the workflow markers, public health, authenticated monitoring, readiness truth, container health and zero secret exposure.
9. Observe the first scheduled run before treating the automation as established operational evidence.

## Acceptance criteria

- Fresh CLS evidence is maintained with a 12-hour cadence without a human login.
- The 24-hour fail-closed freshness threshold remains unchanged.
- The job uses the deployed image's existing SDK and installs no host software.
- A failure cannot refresh timestamps or restart services unless the probe was verified.
- API and worker reload in order; Vault, frontend and Cloudflare remain untouched.
- No eBay, payment, model, search, media or other business-provider operation is called.
- Public charging, charge/refund, eBay publish and real-platform-write flags remain false.
- Logs and status output contain no private values, raw identifiers or secrets.
