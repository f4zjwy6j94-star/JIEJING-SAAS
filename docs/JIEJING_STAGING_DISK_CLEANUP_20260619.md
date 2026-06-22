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

1. Check `df -hPT / /tmp`.
2. If root usage is above `80%`, clean old `/tmp/jiejing-public-staging-*` artifacts using the same allowlist guard.
3. Keep current app files and rollback backups intact.
4. If root usage stays above `80%` after `/tmp` cleanup, inspect logs and Docker cache next.
5. Do not prune Docker volumes or app backups unless there is a separate verified backup/restore plan.

Recommended future hardening:

- Add a deploy-script cleanup step that keeps only the newest 2 to 4 `/tmp/jiejing-public-staging-*` artifacts.
- Add disk usage monitoring alert at `80%` warning and `90%` critical.
- Plan storage expansion before production traffic if deploy frequency remains high.
