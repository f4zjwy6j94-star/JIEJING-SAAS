# Jiejing Staging Restore Drill - 2026-05-19

Scope: staging PostgreSQL backup and restore drill for the eBay-first Jiejing SaaS workbench.

This drill did not repeat eBay OAuth, did not rerun official eBay sync, and did not enable real platform writes.

## Result

- Status: `passed`
- Drill ID: `20260519-144746`
- Source: managed PostgreSQL used by staging
- Restore target: ephemeral `postgres:18-alpine` container
- Checked packet: `packet_5c69bcc5bf0e79ae`
- Counts matched: `true`
- Packet present in source: `1`
- Packet present after restore: `1`
- Raw rows printed: `false`
- Database URL printed: `false`
- Secrets printed: `false`
- Real platform writes enabled: `false`

## Verified Table Counts

| Table | Source | Restored |
| --- | ---: | ---: |
| `audit_logs` | 315 | 315 |
| `companies` | 5 | 5 |
| `confirmations` | 36 | 36 |
| `platform_connections` | 6 | 6 |
| `platform_data_packets` | 6 | 6 |
| `reports` | 44 | 44 |
| `secret_refs` | 6 | 6 |
| `stores` | 3 | 3 |
| `tasks` | 16 | 16 |
| `users` | 6 | 6 |

## Evidence

- Remote evidence directory: `/opt/jiejing-staging/app/output/restore-drills/20260519-144746`
- Remote logical backup: `/opt/jiejing-staging/app/output/restore-drills/20260519-144746/staging-postgres.dump`
- Local redacted summary: `output/jiejing-restore-drill-20260519/restore-drill-summary.json`
- Dump size: `690219` bytes
- Dump SHA-256: `4f67d41171335d84b535fb6854944d98c893b22a051c359b92d32bf675646257`

Only the redacted summary was copied locally. The raw PostgreSQL dump remains on the staging host with mode `600`.

## Backup Gate Status After Recording

After recording `JIEJING_RESTORE_DRILL_LAST_AT` in the staging private env and recreating backend/worker containers:

- `backup_ready_for_paid_launch`: `true`
- `blockers`: `[]`
- `restore_drill_recorded`: `true`
- `last_restore_drill_at`: `2026-05-19T14:49:26+0800`
- `object_storage_ready`: `true`
- `alerts_configured`: `true`
- `secret_exposed`: `false`

This clears the backup/restore drill item. It does not clear unrelated launch blockers such as model value proof or billing.
