# JIEJING GitHub Self-Hosted Runner Deploy Runbook

Date: 2026-06-22

This runbook explains how JIEJING can move from "local computer pushes to Tencent Cloud" to "GitHub/Codex Cloud checks code, then Tencent Cloud pulls and deploys it". It is designed to keep a rollback path and avoid data loss.

## Plain-language model

- GitHub private repo is the source of truth for code.
- Codex Cloud can read the GitHub repo, edit code, run checks, and open diffs without your Windows computer staying on.
- Tencent Cloud keeps the real running app, runtime env files, Vault/KMS boundary, database files, and Docker volumes.
- A GitHub self-hosted runner on Tencent Cloud is the bridge from GitHub to the server.
- The runner must only deploy after a manual workflow dispatch and a typed confirmation sentence.

## What this does not do

- It does not run eBay OAuth.
- It does not publish, revise, refund, advertise, or pay on any real platform.
- It does not write Stripe live keys, eBay refresh tokens, model keys, or SSH private keys into GitHub.
- It does not delete Docker volumes or database files.
- It does not make JIEJING formally paid-public-launch ready.

## Files added for this path

- `AGENTS.md`
  - Repository-level project instructions for local Codex, Codex Cloud, and GitHub-driven agents.
  - Preserves the JIEJING eBay-first product boundary, no-repeat-OAuth rule, no-secret rule, and no-destructive-deploy rule.
  - Included in public staging bundles and the whitelisted staging patch path so cloud work keeps the same operating rules.

- `.github/workflows/jiejing-staging-manual-deploy.yml`
  - Manual workflow only.
  - Runs secret scan, frontend syntax check, deploy guardrail test, and precloud gate.
  - Uses the self-hosted runner only for `dry_run` or `apply`.
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
  - Common blockers include `docker_cli_missing`, `sudo_noninteractive_unavailable`, `app_dir_missing`, and `disk_usage_at_or_above_95_percent`.
  - Disk usage at or above 90 percent reports `disk_usage_at_or_above_90_percent` as a warning so we can clean up before it becomes a hard failure.

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

9. After the runner appears online, open GitHub Actions > `Jiejing Staging Runner Doctor` and run it once.

   A healthy result should include:

   ```text
   JIEJING_RUNNER_DOCTOR_STATUS=ready
   JIEJING_RUNNER_DOCTOR_BLOCKERS=none
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

## Why this preserves a retreat path

- Code remains in GitHub history.
- The server keeps backups under `/opt/jiejing-staging/github-action-backups`.
- Dry-run is the default path.
- Apply mode requires an exact typed confirmation phrase.
- Existing database and Docker volumes are not deleted.
- The workflow is manual only and restricted to the `main` branch.

## Current remaining external blockers

- The Tencent Cloud self-hosted runner is not installed yet.
- Formal paid launch still needs production managed Postgres/Redis, Vault/KMS, monitoring, backups, domain/billing cutover, Stripe live provider, and new eBay account validation.
- Current state remains beta/public-staging oriented, not paid commercial launch.
