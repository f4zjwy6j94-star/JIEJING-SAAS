# JIEJING GitHub Self-Hosted Runner Deploy Runbook

Date: 2026-06-22

This runbook explains how JIEJING can move from "local computer pushes to Tencent Cloud" to "GitHub/Codex Cloud checks code, then Tencent Cloud pulls and deploys it". It is designed to keep a rollback path and avoid data loss.

## Plain-language model

- GitHub private repo is the source of truth for code.
- Codex Cloud can read the GitHub repo, edit code, run checks, and open diffs without your Windows computer staying on.
- Local Windows Codex remains the primary operating mode; Codex Cloud is a fallback route when the local computer cannot be used.
- Tencent Cloud keeps the real running app, runtime env files, Vault/KMS boundary, database files, and Docker volumes.
- A GitHub self-hosted runner on Tencent Cloud is the bridge from GitHub to the server.
- The runner must only deploy after a manual workflow dispatch and a typed confirmation sentence.

## What this does not do

- It does not run eBay OAuth.
- It does not publish, revise, refund, advertise, or pay on any real platform.
- It does not write Stripe live keys, eBay refresh tokens, model keys, or SSH private keys into GitHub.
- It does not delete Docker volumes or database files.
- It does not make JIEJING formally paid-public-launch ready.

## Current installation state

As of 2026-06-22, the Tencent Cloud self-hosted runner path has been installed and validated for dry-run only.

- Runner directory: `/opt/actions-runner-jiejing`
- Runner service: `actions.runner.f4zjwy6j94-star-JIEJING-SAAS.jiejing-staging-VM-0-15-ubuntu.service`
- Runner label: `jiejing-staging`
- Staging deploy roots:
  - `/opt/jiejing-staging/app`
  - `/opt/jiejing-staging/github-action-releases`
  - `/opt/jiejing-staging/github-action-backups`
- Latest validated dry-run: GitHub run `27935130643`, SHA `09fbba4791a98fc660afc81b556e3492f08ba878`
- Dry-run proof:
  - `JIEJING_STAGING_DEPLOY_DRY_RUN=1`
  - `PATCH_APPLIED=0`
  - No running app files, databases, Docker volumes, or Vault/env files were changed.
- Public health after install:
  - `https://app.jiejing.shop/health`: HTTP 200
  - `https://app.jiejing.shop/health/deep`: HTTP 200
  - `https://app.jiejing.shop/readiness/product-saas`: HTTP 200
  - `beta_ready=true`, `production_ready=false`, `can_accept_real_customers=false`
- Disk note: `/` was about 88 percent used after runner install and dry-run release creation. Treat 90 percent as a cleanup warning and 95 percent as a hard blocker.
- Runner maintenance note: use `Jiejing Staging Runner Maintenance` in dry-run mode before archive/apply. It does not touch the running app, backups, private env files, databases, Docker volumes, Vault material, eBay OAuth state, or billing/provider secrets.

## Files added for this path

- `AGENTS.md`
  - Repository-level project instructions for local Codex, Codex Cloud, and GitHub-driven agents.
  - Preserves the JIEJING eBay-first product boundary, no-repeat-OAuth rule, no-secret rule, and no-destructive-deploy rule.
  - Included in public staging bundles and the whitelisted staging patch path so cloud work keeps the same operating rules.

- `.github/workflows/jiejing-staging-manual-deploy.yml`
  - Manual workflow only.
  - Runs secret scan, frontend syntax check, deploy guardrail test, and precloud gate.
  - Uses the self-hosted runner only for `dry_run` or `apply`.
  - Prepares Node on the self-hosted runner before the server-side frontend syntax check, so the server does not need a global Node install.
  - Defaults to `dry_run`.

- `.github/workflows/jiejing-staging-manual-rollback.yml`
  - Manual rollback workflow only.
  - Defaults to dry-run.
  - Restores only from backups under `/opt/jiejing-staging/github-action-backups`.

- `deploy/github-actions/jiejing-staging-deploy.sh`
  - Copies the GitHub Actions workspace into a release candidate directory.
  - Refuses to run unless the confirmation phrase is exactly `deploy app.jiejing.shop staging`.
  - Dry-run creates the release candidate but does not touch the running app.
  - Apply mode backs up `/opt/jiejing-staging/app` first, then calls the existing whitelisted `deploy/apply-staging-patch.sh`.

- `deploy/github-actions/jiejing-staging-rollback.sh`
  - Refuses to run unless the confirmation phrase is exactly `rollback app.jiejing.shop staging`.
  - Dry-run validates the selected backup.
  - Apply mode backs up current app again before restore.

- `.github/workflows/jiejing-staging-runner-doctor.yml`
  - Manual workflow only.
  - Runs on the Tencent Cloud self-hosted runner after it is installed.
  - Does not deploy or restart anything.
  - Reports whether Docker, sudo, app path, deploy path, local health, and disk space are ready.

- `deploy/github-actions/jiejing-runner-doctor.sh`
  - Read-only server-side runner check.
  - Prints `JIEJING_RUNNER_DOCTOR_STATUS=ready` when the host is ready for deploy dry-run.
  - Prints `PUBLIC_HEALTH=ready` when the formal staging domain answers `/health`.
  - Probes `http://127.0.0.1:18080/health` for local health. This is the
    Compose-published frontend path and traverses the local Nginx-to-API route;
    API port `8788` remains container-only and must not be published merely for
    the Doctor check.
  - `local_health_unreachable` is a warning when localhost health is not reachable from the runner host; compare it with public health before treating staging as broken.
  - Common blockers include `docker_cli_missing`, `sudo_noninteractive_unavailable`, `app_dir_missing`, and `disk_usage_at_or_above_95_percent`.
  - Disk usage at or above 90 percent reports `disk_usage_at_or_above_90_percent` as a warning so we can clean up before it becomes a hard failure.

- `.github/workflows/jiejing-staging-runner-maintenance.yml`
  - Manual workflow only.
  - Runs on the Tencent Cloud self-hosted runner.
  - Defaults to dry-run.
  - Requires the exact confirmation phrase `cleanup app.jiejing.shop runner`.
  - Archives old release candidates only after the newest unpacked candidates are kept.

- `deploy/github-actions/jiejing-runner-maintenance.sh`
  - Maintains only `/opt/jiejing-staging/github-action-releases`.
  - Archives to `/opt/jiejing-staging/github-action-release-archives`.
  - It does not touch the running app, backups, private env files, databases, Docker volumes, Vault material, eBay OAuth state, or billing/provider secrets.
  - Dry-run prints `ARCHIVE_APPLIED=0`.
  - Apply mode first writes and verifies a `.tar.gz` archive, then removes the unpacked release candidate.

- `docs/JIEJING_LOCAL_FIRST_CLOUD_FALLBACK_RUNBOOK_20260622.md`
  - Defines local Windows Codex as the normal route and Codex Cloud as the backup route.
  - Explains what phone-only Codex Cloud fallback may do and must not do.
  - Keeps eBay OAuth, Stripe live cutover, deploy apply, and secret-bearing operations behind explicit operator approval.

- `.github/workflows/jiejing-cloud-fallback-self-check.yml`
  - Manual workflow only.
  - Runs on GitHub-hosted Linux with read-only repository permission.
  - Checks secret scan, frontend syntax, local-first fallback guardrails, deploy guardrails, doctor guardrails, and maintenance guardrails.
  - Does not deploy, run eBay OAuth, touch billing, or write server state.

## One-time Tencent Cloud setup

Do this only after you are ready to let GitHub Actions deploy to staging.

1. Keep the repository private.

2. In GitHub, open:
   `f4zjwy6j94-star/JIEJING-SAAS > Settings > Actions > Runners > New self-hosted runner`

3. Choose Linux x64.

4. On the Tencent Cloud server, install the runner under a dedicated directory, for example:

   ```bash
   sudo mkdir -p /opt/actions-runner-jiejing
   sudo chown -R ubuntu:ubuntu /opt/actions-runner-jiejing
   cd /opt/actions-runner-jiejing
   ```

5. Run the download/config commands shown by GitHub. The registration token is time-limited. Do not paste it into project files, chat, commits, or docs.

6. Use these labels when configuring the runner:

   ```text
   jiejing-staging
   ```

7. Install the runner as a service only after it is connected and visible in GitHub:

   ```bash
   sudo ./svc.sh install
   sudo ./svc.sh start
   sudo ./svc.sh status
   ```

8. Make sure the runner user can run the existing staging deploy commands:

   ```bash
   docker compose version
   sudo -n true
   test -d /opt/jiejing-staging/app
   test -f /opt/jiejing-staging/app/app.js
   ```

If `sudo -n true` fails, do not weaken the whole server. Add only the minimum no-password sudo rules needed by the existing staging deploy script, then test again.

9. Provision the runtime-environment guard through a separate root-controlled
   change, outside the app checkout, release directory, and GitHub Actions
   workspace. The deploy and Doctor scripts never install or update this file:

   ```text
   /usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py
   ```

   It must resolve to that absolute regular file without any symlink. The file
   and every parent directory through `/` must be owned by uid 0 and must not
   be group/world writable. Review and pin the exact guard version before this
   manual root-controlled provisioning step. Bootstrap, deploy, patch and
   Doctor never install or update the trusted copy. A candidate bundle may
   update the source proposed for a later, separately approved trusted-guard
   rollout, but it cannot change the guard used in its own execution. A missing
   or untrusted fixed guard is a hard blocker; never fall back to
   `$GITHUB_WORKSPACE/tools/`, a release candidate, or `$APP_DIR/tools/`.

   Server-side deploy `dry_run` executes only this trusted guard. It reads the
   candidate Compose and committed public env examples as data, without sudo
   and without reading the server-private env files. Runner Doctor and deploy
   apply use the same trusted guard to inspect the real private env files via
   the existing restricted sudo boundary.

   Conflict resolution is a separate value-free preparation step. The checked-in
   staging resolution manifest contains value-free key names, source roles and
   the single reviewed retire action enum only, and
   `resolution-plan` validates that evidence without mutating Compose or any
   private env file. For a reviewed candidate, `--compose-runtime-path` supplies
   only the future installed path identity used to resolve `env_file`, while
   `--donor-compose` is the strictly read-only current Compose and may supply a
   value only for an explicit `donor_role=compose` decision. The donor is never
   treated as the desired owner. The two media decisions explicitly use
   `resolution_action=retire_equal_compose_donor_keep_authoritative`; they pass
   only when the candidate omits the key, the secret owner is unique, the donor
   has exactly one declaration in each required runtime service, and all current
   declarations compare equal. Missing owners, conflicts, candidate declarations
   and abnormal donor service topology fail closed. Plan reports expose action,
   key, roles, count and comparison only. The plan is not wired to
   `migrate --apply`.

   A later private-env resolution uses the separate `resolution-apply`
   subcommand only after explicit operator approval. It accepts the same
   candidate, runtime identity, donor, manifest, overrides, three private env
   files and required-service inputs as `resolution-plan`; there is no apply
   flag. No confirmation is a non-mutating dry-run, and the only accepted apply
   phrase is `APPLY_JIEJING_RUNTIME_ENV_RESOLUTION`. The command rebuilds the
   zero-blocker plan under the exclusive transaction lock and binds every input
   snapshot plus internal plan identity before changing only managed, secret or
   postgres private env files. Candidate/donor Compose and the manifest are
   always read-only; the media retire action remains evidence-only. Existing
   CAS/no-clobber, backup and transaction-wide rollback controls protect every
   changed private file, preserve concurrent external bytes, and require a
   zero-blocker post-apply guard of the desired candidate topology. After that
   validator and every backup/commit integrity check, a final readonly-snapshot
   check binds candidate/donor Compose, manifest and every override until the
   success return; only committed private sources are excluded. Late readonly
   drift is preserved and rolls back all private commits, while retire-only
   execution remains zero-write.

   Compose donor values use a strict reversible single-quoted `env_file`
   encoding and target-parser semantic round trip, keeping hash, surrounding
   spaces, quotes and backslashes literal. A dollar marker requires a verified
   single-quoted source; plain or double-quoted Compose/private dollar values
   may interpolate and fail closed. Compose donor apply is mapping-only,
   including evidence-only retire: every Compose environment list donor fails
   before backup, regardless of content, RHS-like quote characters or whole-item
   quoting. Newline, NUL, Unicode `Cc` controls, `Zl` line separators, `Zp` paragraph separators
   and unsupported escape forms fail closed before backup
   or commit, while ordinary printable Unicode remains supported. Every fully rendered private candidate
   is processed by the complete env parser before
   backup/commit; it must have zero blockers, and every addition must occur
   exactly once with the bound runtime value. Existing private env payloads are
   scanned as complete text before `splitlines`: only physical LF and CRLF are line endings,
   lone CR fails closed, and mixed LF/CRLF stays valid with untouched bytes
   preserved. Candidate Compose, donor Compose and manifest structure do not
   pass through this env-file parser. Private-to-private moves retain and
   revalidate the exact original RHS rather than stripping it. Apply
   reports omit key names, values, paths, digests and
   line contents. This subcommand does not copy a candidate, run Docker Compose,
   deploy or restart anything.

   Example syntax for a separately approved maintenance window:

   ```bash
   sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" resolution-apply \
     --compose "$CANDIDATE_COMPOSE" \
     --compose-runtime-path "$CURRENT_COMPOSE" \
     --donor-compose "$CURRENT_COMPOSE" \
     --managed-env /opt/jiejing-staging/private/tencent-managed.env \
     --secret-env /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env \
     --postgres-env /opt/jiejing-staging/private/postgres-localqueue.env \
     --decision-manifest deploy/jiejing-staging-runtime-env-resolution-manifest.example.json \
     --confirm APPLY_JIEJING_RUNTIME_ENV_RESOLUTION \
     --json
   ```

   If cost-saver mode is enabled, its only accepted override is the fixed,
   root-owned, non-writable resource override at
   `/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml`. It may
   contain only `services`, the `jiejing-saas` / `jiejing-worker` service names,
   and literal bounded `deploy.resources.limits` / `reservations` values for
   `cpus`, `memory`, and `pids` (`pids` is limits-only). Any old environment-
   switching cost-saver file, unknown key or service, inline collection, YAML
   include, anchor, alias, merge, variable interpolation, or unsafe scalar
   makes the guard fail closed. Replace a rejected legacy file only through a
   separate reviewed root-controlled operation; these scripts never rewrite it.

10. After the runner appears online, open GitHub Actions > `Jiejing Staging Runner Doctor` and run it once.

   Doctor validates the reviewed candidate Compose from the exact Actions
   checkout as data with the root-pinned trusted guard. It binds relative
   `env_file` resolution to the future installed location through
   `--compose-runtime-path`; it never executes the candidate guard. The
   checkout HEAD must equal the 40-character workflow target SHA and the
   candidate Compose must be a tracked, unchanged, regular non-symlink file
   inside that checkout.

   During a separately approved private-env-to-Compose transition, the old
   live Compose may fail the legacy ownership check after the private files
   have already been transactionally aligned to the candidate. Doctor accepts
   this state only when the candidate check has zero blockers and it can prove
   the current live release SHA from the latest applied release whose Compose
   and application payload match the live files. That SHA must differ from and
   be a Git ancestor of the exact candidate SHA. It then reports
   `RUNTIME_ENV_GUARD_STATUS=ready_transition` and the value-free warning
   `runtime_env_live_compose_transition_detected`. Missing, ambiguous or
   non-ancestor release evidence fails closed; never suppress an unknown live
   ownership failure.

   A healthy result should include:

   ```text
   JIEJING_RUNNER_DOCTOR_STATUS=ready
   JIEJING_RUNNER_DOCTOR_BLOCKERS=none
   LOCAL_HEALTH=ready
   PUBLIC_HEALTH=ready
   SECRET_EXPOSED=false
   ```

   If it reports blockers, fix those before running staging deploy dry-run. For example:

   - `docker_cli_missing`: Docker is not visible to the runner user.
   - `sudo_noninteractive_unavailable`: the runner cannot run the existing deploy script without an interactive password prompt.
   - `deploy_root_not_writable_by_runner`: `/opt/jiejing-staging` ownership or permissions need adjustment.
   - `disk_usage_at_or_above_95_percent`: stop and clean/expand disk before deploying.

## Safe deploy flow

1. Push code to `main`.

2. Wait for normal `Jiejing CI` to pass.

3. Open GitHub Actions > `Jiejing Staging Manual Deploy`.

4. If this is the first deploy attempt after installing the runner, run `Jiejing Staging Runner Doctor` first.

5. First deploy run:

   ```text
   deploy_mode: dry_run
   confirm_staging_deploy: deploy app.jiejing.shop staging
   ```

6. Check output. Dry-run should show:

   ```text
   JIEJING_STAGING_DEPLOY_DRY_RUN=1
   PATCH_APPLIED=0
   RELEASE_DIR=...
   BACKUP_DIR_WOULD_BE=...
   ```

7. Only if dry-run succeeds, run apply:

   ```text
   deploy_mode: apply
   confirm_staging_deploy: deploy app.jiejing.shop staging
   ```

8. After apply, verify:

   ```bash
   curl -fsS https://app.jiejing.shop/health
   curl -fsS https://app.jiejing.shop/health/deep
   curl -fsS https://app.jiejing.shop/readiness/product-saas
   ```

9. In a separate evidence-recording maintenance step, and only after the live
   public-charging and real-write switches are independently confirmed off,
   the support/refund pages are verified, and the merchant-surface copy scan
   passes, record the four reviewed facts:

   ```bash
   cd /opt/jiejing-staging/app
   sudo -n python3 tools/jiejing_configure_tencent_runtime_env.py \
     --env-file /opt/jiejing-staging/private/tencent-managed.env \
     --apply \
     --production-release-charge-flag-reviewed \
     --production-release-real-write-flag-reviewed \
     --production-support-refund-policy-reviewed \
     --production-merchant-surface-copy-scan-passed
   ```

   This records review evidence only: it does not enable public charging,
   payment/refund execution, or eBay writes, and it does not grant final owner approval.
   Rerun the trusted runtime ownership guard, Runner Doctor, deploy
   dry-run, and separately approved deploy apply before treating the new env as
   loaded. Never combine this step with a final owner-approval or live switch.

## Rollback flow

1. Find the backup name printed by the deploy workflow:

   ```text
   BACKUP_DIR=/opt/jiejing-staging/github-action-backups/pre-github-...
   ```

2. Open GitHub Actions > `Jiejing Staging Manual Rollback`.

3. First run dry-run:

   ```text
   backup_name: pre-github-...
   dry_run: true
   confirm_staging_rollback: rollback app.jiejing.shop staging
   ```

4. Only if dry-run validates the backup, run apply:

   ```text
   backup_name: pre-github-...
   dry_run: false
   confirm_staging_rollback: rollback app.jiejing.shop staging
   ```

5. Verify health endpoints again.

## Runner maintenance flow

Use this when dry-runs or deploy attempts have created many release candidate folders and disk usage is approaching the 90 percent warning threshold.

1. Open GitHub Actions > `Jiejing Staging Runner Maintenance`.

2. First run dry-run:

   ```text
   dry_run: true
   keep_latest: 5
   archive_after_days: 7
   confirm_runner_maintenance: cleanup app.jiejing.shop runner
   ```

3. Check output. Dry-run should show:

   ```text
   JIEJING_RUNNER_MAINTENANCE_DRY_RUN=1
   ARCHIVE_CANDIDATE_COUNT=...
   ARCHIVE_APPLIED=0
   SECRET_EXPOSED=false
   ```

4. Only if the candidates are old release directories under `/opt/jiejing-staging/github-action-releases/github-*`, run apply:

   ```text
   dry_run: false
   keep_latest: 5
   archive_after_days: 7
   confirm_runner_maintenance: cleanup app.jiejing.shop runner
   ```

5. Apply mode should show:

   ```text
   ARCHIVED_RELEASE=...
   ARCHIVE_FILE=/opt/jiejing-staging/github-action-release-archives/....tar.gz
   ARCHIVE_APPLIED=1
   SECRET_EXPOSED=false
   ```

6. Run `Jiejing Staging Runner Doctor` again. If disk remains above 90 percent, inspect archive sizes and decide whether to download/delete old archives manually. Do not delete backups or private state.

## Why this preserves a retreat path

- Code remains in GitHub history.
- The server keeps backups under `/opt/jiejing-staging/github-action-backups`.
- Dry-run is the default path.
- Apply mode requires an exact typed confirmation phrase.
- Existing database and Docker volumes are not deleted.
- The workflow is manual only and restricted to the `main` branch.

## Current remaining external blockers

- Apply-mode staging deploy has been proven through GitHub Actions, but every
  new change must still follow Doctor -> dry-run -> explicit apply.
- Formal paid launch still needs the owner's authenticated single-account
  merchant workflow acceptance, a clean new eBay account authorization and
  controlled proof, production WeChat payment/refund cutover evidence, and
  explicit final owner approval. The future three-merchant scale-validation
  target does not block the single-owner private pilot.
- Current state remains beta/public-staging oriented, not paid commercial launch.
