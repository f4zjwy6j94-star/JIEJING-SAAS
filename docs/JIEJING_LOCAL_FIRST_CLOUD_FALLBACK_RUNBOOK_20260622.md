# JIEJING Local-First Codex And Cloud Fallback Runbook

Date: 2026-06-22

This runbook fixes the operating model for JIEJING development:

- Local Windows Codex remains the primary operating mode.
- Codex Cloud is a fallback route for times when the local computer cannot be used.
- The GitHub private repo `JIEJING-SAAS` is the code handoff point between the two modes.
- Tencent Cloud keeps the running staging app, runtime env files, database state, Docker volumes, Vault/KMS boundary, and server-side deploy bridge.

## Plain-language answer

When the local computer is on, use the current local Codex workflow. That is still the best path for UI screenshots, browser smoke checks, local files, existing SSH access, and fast product iteration from the shared workspace.

When the local computer is not available, use Codex Cloud from the phone as a backup path. It can work from GitHub, run repository checks, create commits, push code, and trigger safe GitHub Actions checks. It should not pretend to have access to local-only files, browser login state, or local secrets.

## What Codex Cloud fallback can do

- Read and edit code in the private GitHub repo.
- Run `Jiejing Cloud Fallback Self Check`.
- Run local repository checks such as:
  - `python tools/jiejing_secret_scan.py`
  - `node --check app.js`
  - `python tools/jiejing_precloud_deployment_gate.py`
- Open commits or pull requests when needed.
- Trigger `Jiejing Staging Runner Doctor` to inspect the Tencent runner.
- Trigger `Jiejing Staging Manual Deploy` in dry-run mode only.
- Trigger `Jiejing Staging Runner Maintenance` in dry-run mode only.

## What Codex Cloud fallback must not do

- Do not repeat eBay OAuth.
- Do not trigger real eBay publish, revise, inventory, refund, ads, procurement/payment, policy edits, or sensitive customer promises.
- Do not run Stripe live payment cutover, real charges, refunds, or live webhook writes.
- Do not store Stripe live keys, eBay refresh tokens, model keys, client secrets, or SSH private keys in GitHub.
- Do not read or print local browser cookies, GitHub tokens, SSH private keys, OAuth codes, or provider keys.
- Do not use `git credential fill`.
- Do not run destructive deployment commands such as `docker compose down -v`, Docker volume deletion, database drop/truncate commands, broad recursive deletes, or secret file cleanup.
- Do not claim formal commercial launch readiness while `production_ready=false` or `can_accept_real_customers=false`.

Current state remains beta/public-staging oriented, not paid commercial launch.

## Normal daily route

Use this route whenever the local computer is available:

1. Work in the local Windows Codex workspace.
2. Verify current staging health before reporting launch or deployment state:
   - `https://app.jiejing.shop/health`
   - `https://app.jiejing.shop/health/deep`
   - `https://app.jiejing.shop/readiness/product-saas`
3. Run focused tests for the changed area.
4. For launch/deploy-adjacent changes, run:
   - `python tools/jiejing_secret_scan.py`
   - `node --check app.js`
   - `python tools/jiejing_precloud_deployment_gate.py`
5. Commit and push to GitHub after checks pass.

## Phone-only fallback route

Use this route only when the local computer cannot be used:

1. Open Codex Cloud on the phone.
2. Select the GitHub repo `JIEJING-SAAS`.
3. Ask it to run `Jiejing Cloud Fallback Self Check`.
4. If the self-check passes, let it make code changes in a branch or commit.
5. Ask it to run repository checks before pushing.
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

- Local computer available: use local Windows Codex as primary.
- Local computer unavailable: use Codex Cloud fallback against GitHub.
- Any real money, real marketplace write, account OAuth, or secret-bearing step: stop at the decision center and ask for explicit approval.
