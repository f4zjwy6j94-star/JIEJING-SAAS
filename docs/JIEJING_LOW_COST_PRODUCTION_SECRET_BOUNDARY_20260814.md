# Jiejing Low-Cost Production Secret Boundary

This is the budget launch profile for the eBay-first AI CEO SaaS. KMS is optional;
the production boundary may use the pinned, file-backed HashiCorp Vault service in
`deploy/docker-compose.production-pilot.yml` without exposing Vault on a host port.
Managed KMS remains the later high-availability upgrade, not a paid launch blocker.

## Non-negotiable boundary

- Initialize Vault once with three key shares and a two-share threshold.
- Use three independent custody units for the 3-share/2-threshold layout. No single custody unit or custodian may hold two shares. A practical low-cost
  layout is one share on encrypted USB A, one on encrypted USB B, and one
  separately sealed offline copy held by another custodian or stored in a
  different physical safe. Two USB drives alone are not sufficient if either
  one also contains the third share.
- Perform manual unseal after a planned Vault or host restart.
- Keep the shares offline across three independent operator-controlled custody units;
  no unit may contain enough shares to meet the unseal threshold.
- Apply the reviewed `deploy/vault-policy.production.hcl`: data access is limited
  to `secret/data/jiejing-production/*`, KV v2 permanent revocation is limited to
  `secret/metadata/jiejing-production/*`, and the token may only look up/renew itself.
  Create a periodic backend token with this policy and write it once to the mode-`0600`
  server-private `jiejing-vault-token` file. API, worker and renewer mount that
  same file read-only, so renewal and application use cannot drift to different tokens.
- Never store the unseal key, root token, backend token, provider key, or eBay token
  in Git, the image, Compose YAML, logs, chat, ordinary database rows, or backups.
- Keep Vault `mlock` enabled with the container `IPC_LOCK` capability so decrypted
  secret pages are not written to host swap.
- Revoke the initialization root token after policy and backend-token setup.

## Initialization sequence

1. Provision the dedicated production host and private env file with mode `0600`.
2. Start only `jiejing-vault` and run `vault operator init` inside that container.
3. Move the three returned shares and initial root token directly to offline encrypted
   operator storage. Use three independent custody units and keep the maximum at one
   share per unit for this 3-share/2-threshold layout. Do not leave the initialization
   JSON on the server.
4. Use two shares for manual unseal, enable KV v2 at `secret/`, create the scoped
   `jiejing-production` policy from `deploy/vault-policy.production.hcl`, issue the
   periodic backend token, verify it is renewable with a positive period, then revoke root.
5. Write only the scoped backend token to `../../private/jiejing-vault-token`, set
   owner-only permissions, and start Vault, renewer, API and worker in that order.
6. Verify `/health/deep` and a backend-only secret resolver probe without printing a
   secret value.

After the encrypted backup, isolated restore, manual unseal and sentinel resolve have
all actually succeeded, record only the value-free custody geometry and evidence:

```powershell
python tools/jiejing_configure_tencent_runtime_env.py `
  --env-file <server-private-env-file> `
  --apply `
  --record-vault-recovery-evidence `
  --vault-backup-artifact-id-env JIEJING_OPERATOR_VAULT_BACKUP_ARTIFACT_ID `
  --vault-unseal-key-shares 3 `
  --vault-unseal-key-threshold 2 `
  --vault-offline-share-custody-verified `
  --vault-offline-custody-unit-count 3 `
  --vault-offline-max-shares-per-custody-unit 1
```

The artifact identifier must enter through the named process environment variable.
Never put any share, root token or backend token in this command, evidence output or
runtime database.

## Backup and recovery

- Stop or quiesce Vault briefly and take a consistent encrypted off-host backup of
  the dedicated `jiejing_production_vault_data` volume.
- Store backup encryption material separately from both the backup and unseal shares.
- Run a quarterly isolated restore drill and verify only value-free secret metadata
  and resolver success; never copy raw secret values into evidence artifacts.
- A backup is not valid until the isolated restore can be manually unsealed and the
  application resolves a sentinel reference without exposing its value.

This profile trades managed auto-unseal and multi-node availability for lower cost.
It is acceptable for the controlled launch only with monitoring, documented restart
procedures, offline shares, and the encrypted off-host backup/restore drill above.
