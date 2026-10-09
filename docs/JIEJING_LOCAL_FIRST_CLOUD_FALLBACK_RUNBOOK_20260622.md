# JIEJING Two-Endpoint Continuity And Legacy Manual Self-Check

Original date: 2026-06-22. Continuity correction: 2026-10-09.

The old local-primary/cloud-fallback preference is superseded. The filename and
the `Jiejing Cloud Fallback Self Check` workflow name remain for existing callers;
they are not the current endpoint-selection policy. The earlier policy is in Git
history. Current authority is `AGENTS.md`, the current execution index
`docs/JIEJING_CURRENT_EXECUTION_STATE.md`, and `docs/continuity/11.0/WORK_SYNC.md`.

- Preserve original local 10.0 and cloud 11.0, with one responsible endpoint per task.
- The private `JIEJING-SAAS` branch `video/jiejing-11-continuity-20261006` carries
  approved source and safe progress records, not a full chat/media/secret mirror.
- Start with WORK_SYNC status, receive only on the correct clean branch, then
  read the latest execution index. Preserve dirty work and divergence; no reset,
  clean, forced overwrite, force-push or automatic merge of competing work.
- Save explicitly reviewed paths and the updated index after meaningful progress.
  A matching remote SHA means handed off; the other endpoint must actually receive.
- Source/progress synchronization is not deployment authorization.
- Tencent runtime state, databases, volumes and Vault remain separately protected.
  Do not infer their current identity or health from this June runbook.

## Plain-language answer

Local work can use the local files and tools actually available on the computer.
Existing browser login is local; verify the required browser before using it.

Cloud work can continue only from the source/progress it has actually received
and tools available there. It cannot access an offline computer's unsaved work,
local browser session or local secrets. This is not automatic machine routing.

## Available checks, when relevant and authorized

- Read and edit code in the private GitHub repo.
- Run `Jiejing Cloud Fallback Self Check`.
- Run local repository checks such as:
  - `python tools/jiejing_secret_scan.py`
  - `node --check app.js`
  - `python tools/jiejing_precloud_deployment_gate.py`
- Save source and safe records via WORK_SYNC on the existing work branch.
- Trigger `Jiejing Staging Runner Doctor` to inspect the Tencent runner.
- Trigger `Jiejing Staging Manual Deploy` in dry-run mode only.
- Trigger `Jiejing Staging Runner Maintenance` in dry-run mode only.

This list documents retained manual tools, not an instruction to dispatch them
while receiving progress. Inspect the actual target and current runbook first;
do not replace the production deployment path with a legacy staging workflow.

## Safety rules on either endpoint

- Do not repeat eBay OAuth.
- Do not trigger real eBay publish, revise, inventory, refund, ads, procurement/payment, policy edits, or sensitive customer promises.
- Do not run Stripe live payment cutover, real charges, refunds, or live webhook writes.
- Do not store Stripe live keys, eBay refresh tokens, model keys, client secrets, or SSH private keys in GitHub.
- Do not read or print local browser cookies, GitHub tokens, SSH private keys, OAuth codes, or provider keys.
- Do not use `git credential fill`.
- Do not run destructive deployment commands such as `docker compose down -v`, Docker volume deletion, database drop/truncate commands, broad recursive deletes, or secret file cleanup.
- Do not claim formal commercial launch readiness while `production_ready=false` or `can_accept_real_customers=false`.

Do not infer current launch status from this historical runbook. Current
production health, paid availability, refund execution and real eBay writes need
their own current evidence; local tests and source handoff do not establish them.

## Normal source/progress route

Use the same continuity workflow on the endpoint responsible for the task:

1. Read AGENTS and WORK_SYNC; run status/receive safely and read the latest index.
2. When reporting live launch/deployment state, verify relevant current evidence:
   - `https://app.jiejing.shop/health`
   - `https://app.jiejing.shop/health/deep`
   - `https://app.jiejing.shop/readiness/product-saas`
3. Run focused tests for the changed area.
4. For launch/deploy-adjacent changes, run:
   - `python tools/jiejing_secret_scan.py`
   - `node --check app.js`
   - `python tools/jiejing_precloud_deployment_gate.py`
5. Update the execution index, review exact paths, run WORK_SYNC save, and verify
   local/remote SHA and a clean tree. Do not push main or force-push.

## Optional legacy manual self-check / staging path

Only use these tools when the actual task calls for them. Availability from a
phone or cloud endpoint does not grant new server or business-write authority.

1. Reuse the existing project; do not recreate or remigrate it.
2. Receive the approved work branch and read its latest execution index.
3. The retained `Jiejing Cloud Fallback Self Check` is manual and repository-only.
4. Its passing result is not production deployment or paid-launch proof.
5. Source edits and handoff still follow WORK_SYNC and its exact-path protections.
6. If staging deployment is needed, run `Jiejing Staging Manual Deploy` in dry-run first.
7. Apply to staging only after an explicit operator approval window. Use this fallback approval shorthand in planning notes only:

   ```text
   apply to staging explicitly
   ```

The existing GitHub deploy workflow still requires its own exact confirmation phrase:

```text
deploy app.jiejing.shop staging
```

## Safe GitHub Actions map

- `Jiejing Cloud Fallback Self Check`
  - Runs on GitHub-hosted Linux.
  - Read-only repository self-check.
  - No deploy, no OAuth, no billing, no server writes.

- `Jiejing Staging Runner Doctor`
  - Runs on the Tencent Cloud self-hosted runner.
  - Read-only server and public health inspection.
  - No deploy, no restart, no secrets.

- `Jiejing Staging Manual Deploy`
  - Runs on the Tencent Cloud self-hosted runner.
  - Must run `dry_run` first.
  - Apply mode requires explicit typed confirmation and an approved deploy window.

- `Jiejing Staging Runner Maintenance`
  - Runs on the Tencent Cloud self-hosted runner.
  - Must run dry-run first.
  - Archives old GitHub release candidate folders only.
  - Does not touch the running app, backups, databases, Docker volumes, private env files, Vault material, eBay state, or billing secrets.

## Operator rule

If a future agent is unsure which route to use:

- Use the task's recorded responsible endpoint and its actually verified tools.
- When switching endpoints, save then receive; do not assume live synchronization.
- Any real money, real marketplace write, account OAuth, or secret-bearing step: stop at the decision center and ask for explicit approval.
