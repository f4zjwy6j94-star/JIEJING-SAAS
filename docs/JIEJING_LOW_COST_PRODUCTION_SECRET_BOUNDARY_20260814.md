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
- USB is optional. A custody unit may instead be a sealed paper share, a
  write-once optical disc, or an independent offline device such as an encrypted
  external SSD/HDD, provided it is physically separate, remains offline, and
  contains only one share. A different partition or drive letter on the same
  physical disk is not an independent custody unit. A cloud drive, email,
  ordinary password manager, synced folder, screenshot, or phone photo does not
  count as an offline custody unit.
- The share payload is tiny. If buying removable media, even 8 GB is technically
  ample; choose a reputable 16 GB encrypted USB drive for availability and
  reliability, not capacity. Larger capacity does not improve the custody
  boundary.
- Lowest-cost acceptable combinations include: one encrypted USB plus one sealed
  paper share plus one independent offline device, or three sealed paper shares
  held in tamper-evident envelopes by three separate custodians/physical safes.
  Prepare paper without a network-connected printer or camera, verify it
  privately, and keep each copy in a different location.
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

## Sealed-paper production ceremony

Use this profile when the owner selects three sealed paper shares and has no
independent digital media. It is a human-only ceremony, not an automation step.

1. Prepare three opaque tamper-evident envelopes labelled only `A`, `B`, and `C`,
   three separate custody locations/custodians, and a pen. Do not put a company,
   Vault, domain, account, or threshold label on the outside.
2. Use a direct trusted local console with no screen recording. Shell recording,
   remote assistance, browser automation, screen sharing, clipboard history, and
   cloud-shell transcript must all be disabled. The ceremony must not pass through
   Codex, chat, a phone, a screenshot, a camera, a synced printer, or a network
   print queue.
3. Initialize exactly three Vault shares with threshold two. Keep the response
   only in the foreground process memory and reveal one share at a time to the
   owner. Never write the initialization JSON, shares, or root token to a file.
4. Hand-copy share A, B, and C onto their matching paper sheets. For each sheet,
   perform a double transcription check by reading every character twice before
   sealing it. Do not create a second working copy or photograph the sheet.
5. Verify the threshold through protected interactive input: one share must leave
   Vault sealed and a second distinct share must unseal it. Never place a share in
   a command argument, shell history, evidence output, or operator note.
6. Complete policy and periodic-token setup in the same protected session, revoke
   the initialization root token, close the process, clear the terminal scrollback,
   disable any temporary clipboard, and verify that no plaintext digital residue
   or initialization file remains.
7. Move envelopes A, B, and C immediately to three independent physical custody
   units. No custodian or location may hold two envelopes. Record only the
   value-free geometry and witnessed pass/fail facts after an isolated restore.

If a direct non-recording console cannot be established, stop. Do not weaken the
ceremony by using a browser-controlled terminal or by storing a temporary copy on
the workstation; use the PGP media custody profile after independent offline media
becomes available instead.

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
