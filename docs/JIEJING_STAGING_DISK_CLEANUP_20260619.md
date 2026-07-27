# Jiejing staging disk cleanup - 2026-06-19

## Scope

This record covers the safe disk cleanup performed on the staging host.

- Host: `43.129.205.244`
- App path preserved: `/opt/jiejing-staging/app`
- Data paths preserved: database, Vault/env boundaries, app output, rollback backups
- Cleanup target only: `/tmp/jiejing-public-staging-*`

No application data, database files, secrets, Vault material, environment files, current app files, or rollback backups were deleted.

## Pre-clean state

- Root filesystem: `40G`, used `38G`, available `337M`, usage `100%`
- `/tmp` contained `274` Jiejing public staging upload/extract artifacts
- Candidate temporary artifact size: about `24G`

The large disk usage came from repeat deploy bundles uploaded to `/tmp` and their extracted directories.

## Action

Removed old temporary deployment artifacts matching this strict allowlist:

- `/tmp/jiejing-public-staging-*.zip`
- `/tmp/jiejing-public-staging-*` directories

Safety controls:

- Resolved each path with `readlink -f`
- Refused any path not under `/tmp/jiejing-public-staging-*`
- Refused `/`, `/tmp`, and empty/dangerous path shapes
- Kept the newest 4 temporary artifacts for short-term deploy debugging

## Result

- Deleted artifacts: `270`
- Candidate bytes removed: `25079597824`
- Root filesystem after cleanup: `40G`, used `14G`, available `24G`, usage `37%`
- `/tmp` after cleanup: `945M`
- `/opt/jiejing-staging`: `823M`

Remaining temporary artifacts:

- `/tmp/jiejing-public-staging-20260619-081947`
- `/tmp/jiejing-public-staging-20260619-081947.zip`
- `/tmp/jiejing-public-staging-20260619-122127`
- `/tmp/jiejing-public-staging-20260619-122127.zip`

## Post-clean verification

Verified after cleanup:

- `https://app.jiejing.shop/health`: `status=ok`, `secret_exposed=false`
- `https://app.jiejing.shop/health/deep`: operational health `ready`
- Postgres live probe: `ready`
- Queue provider: `postgres_durable`
- Worker heartbeat: `ready`
- `https://app.jiejing.shop/readiness/product-saas`: `beta_ready=true`
- `production_ready=false`
- `can_accept_real_customers=false`
- `warning_count=2`
- Latest official eBay packet: `packet_f5cbba8068e6542d`
- eBay token refresh success proof: `0`

The cleanup did not make the product paid-launch ready. Billing live provider and new eBay account smoke remain external launch gates.

## Next maintenance rule

Before frequent staging bundle deploys:

1. The stable deploy tool checks `df -Pk` for the app path and `/tmp` before uploading a bundle.
2. At `80%` usage it records a warning and continues only when at least `2 GiB` remains.
3. At `92%` usage, below `2 GiB` free, or when the report cannot be parsed, deployment is blocked before upload.
4. After a successful deployment, clean old `/tmp/jiejing-public-staging-*` artifacts using the same allowlist guard and keep the newest four.
5. Keep current app files and rollback backups intact.
6. If root usage stays above `80%` after `/tmp` cleanup, inspect logs and Docker cache next.
7. Do not prune Docker volumes or app backups unless there is a separate verified backup/restore plan.

Recommended future hardening:

- Keep disk monitoring aligned with the deploy guard: `80%` warning and `92%` deployment block.
- Plan storage expansion before production traffic if deploy frequency remains high.

## Automated deploy-artifact retention - 2026-07-15

A follow-up read-only audit found that repeated `--no-cache` image builds and
unbounded deployment rollback artifacts had become the main growth path:

- Docker build cache: `15.48G`, of which `14.69G` was unused and reclaimable
- GitHub Actions backups: `2.2G`
- GitHub Actions release candidates: `2.2G`
- staging patch backups: `870M`

The stable staging deploy tool now applies bounded retention only after the new
deployment passes its local container health check:

- keep the newest `8` `output/staging-patch-backups/[timestamp]` directories
- keep the newest `5` `github-action-backups/pre-github-*` directories
- keep the newest `5` `github-action-releases/github-*` directories
- remove only unused Docker builder cache older than `1` hour; current staging
  builds already use `--no-cache`, so retaining older build cache has no runtime
  or build-speed value
- retain the existing newest `4` `/tmp/jiejing-public-staging-*` artifacts

The cleanup resolves and validates every deletion candidate beneath one of the
three exact deployment roots. It refuses non-canonical app roots and reports
before/after filesystem evidence in the deploy result.

Explicit exclusions remain unchanged: no Docker volume prune, no Docker system
prune, no database, Vault, private env, uploaded media, business output, current
container image, or `/opt/jiejing-staging/backups` recovery archive deletion.
