# Vault Production-Grade Recovery Rehearsal Implementation Plan

> Status: approved design execution. This plan implements the non-production
> E/F rehearsal defined in
> `docs/superpowers/specs/2026-08-21-vault-production-grade-recovery-rehearsal-design.md`.
> It must never credit production custody or change public launch readiness.

## Phase 0: documented interfaces and boundaries

### Sources to copy from

- HashiCorp `operator init` documentation:
  `https://developer.hashicorp.com/vault/docs/commands/operator/init`
  - `-key-shares=3`, `-key-threshold=2`, `-pgp-keys`,
    `-root-token-pgp-key`, and JSON output are supported.
- HashiCorp binary verification guide:
  `https://developer.hashicorp.com/well-architected-framework/verify-hashicorp-binary`
  - verify the detached signature over `SHA256SUMS`, then compare the selected
    archive SHA-256 before extraction.
- HashiCorp file storage documentation:
  `https://developer.hashicorp.com/vault/docs/configuration/storage/filesystem`
  - use an absolute file-storage path and secure the filesystem itself.
- HashiCorp periodic token documentation:
  `https://developer.hashicorp.com/vault/docs/commands/token/create`
  - `vault token create -period=<duration>` produces a renewable periodic
    service token when created by an authorized root operator.
- Existing repository crypto/evidence seam:
  `tools/jiejing_vault_recovery_drill.py`
  - reuse the existing AES-256-GCM archive format and value-free evidence
    convention; do not invent a second encryption format.
- Production policy:
  `deploy/vault-policy.production.hcl`
  - install this exact policy body under a rehearsal-only policy name.

### Allowed APIs

- Windows PowerShell storage discovery: `Get-Volume`, `Get-Partition`,
  `Get-Disk`.
- Windows ACL application and verification: `icacls` with literal paths.
- Windows Vault Community 1.21.4 CLI and loopback HTTP API.
- WSL GnuPG only for generating disposable rehearsal identities, exporting
  public keys, verifying HashiCorp's checksum signature, and decrypting the
  PGP-encrypted disposable outputs.
- Python standard library plus repository-installed `cryptography` for
  subprocess control, loopback HTTP, canonical JSON, SHA-256, ZIP extraction,
  tar snapshot creation, and AES-256-GCM.

### Anti-pattern guards

- No Docker dependency, development server, one-share seal, plaintext init
  output, command-line secret, shell transcript, public listener, production
  host, production env edit, production Vault call, eBay call, or payment call.
- No fallback from failed signature/checksum/ACL/disk checks.
- No production readiness/custody evidence credit from E/F because both map to
  physical disk 0.

## Phase 1: public contract and fail-closed controller

### What to implement

1. Add `tools/jiejing_vault_production_grade_rehearsal.py` with a narrow CLI:
   `--source-root`, `--restore-root`, `--policy-file`, `--execute`.
2. Default mode is validation only; credential generation requires explicit
   `--execute`.
3. Emit only one value-free result JSON and a short PASS/BLOCKED line.
4. Keep secret-bearing subprocess input in memory or stdin; never place tokens,
   shares, backup keys, or sentinel values in argv, evidence, exceptions, or
   logs.

### Tracer test

Add `tools/test_jiejing_vault_production_grade_rehearsal.py` and first prove
that a valid synthetic backend produces the exact value-free evidence contract
while E/F same-disk discovery remains non-production.

### Verification

- The first test must fail before the controller exists.
- Green requires `production_readiness_credited=false`,
  `production_custody_credited=false`, `real_platform_writes_enabled=false`,
  `public_charging_allowed=false`, and `secret_exposed=false`.
- Secret canaries must be absent from serialized results and raised error text.

## Phase 2: host preflight and software provenance

### What to implement

1. Discover E/F as NTFS and prove each exact drive-to-disk mapping.
2. Create the approved source/restore trees with inherited ACL removal and an
   allowlist of current user, SYSTEM, and Administrators.
3. Download only the Windows AMD64 1.21.4 archive, signed checksum manifest,
   signature, and HashiCorp public key over HTTPS.
4. Verify the checksum signature in an isolated WSL GnuPG home and compare the
   selected archive SHA-256 before ZIP extraction.
5. Run `vault version` and require exact 1.21.4.

### Verification

- Wrong filesystem, wrong physical-disk fact, unsafe ACL, non-loopback
  listener, bad signature, bad checksum, unexpected ZIP member, or wrong Vault
  version stops before credential generation.
- Evidence records only version, archive digest, official source host, disk
  numbers, ACL booleans, and same-disk fact.

## Phase 3: Shamir/PGP/token lifecycle

### What to implement

1. Generate four disposable PGP identities in the approved simulated units.
2. Start Vault with file storage on E and a random loopback-only port.
3. Initialize three PGP-encrypted shares with threshold two and an encrypted
   root token.
4. Prove share A alone leaves Vault sealed and A+B unseals it.
5. Enable KV v2, install the exact production policy, create a scoped periodic
   token, require `renewable=true` and `period>0`, renew it, and revoke root.
6. Write and read a random rehearsal sentinel; keep only reference/payload
   digests.

### Verification

- Share count/threshold/PGP booleans are exact.
- Root/default/sudo/unrelated capabilities are denied to the backend token.
- No decrypted share/token/sentinel is written to retained plaintext files.

## Phase 4: stopped backup and fresh F-volume restore

### What to implement

1. Stop Vault and prove the process exited before snapshot creation.
2. Tar the E file-storage tree into E backup staging.
3. Encrypt it with the existing AES-256-GCM archive seam, storing the encrypted
   artifact on F and the protected rehearsal key in the separate F key unit.
4. Remove plaintext staging, retire the original E data path, decrypt into a
   fresh empty F restore directory, and start a second Vault process against it.
5. Repeat one-share-sealed/two-share-unsealed proof, renew the original scoped
   token, and resolve the sentinel with matching in-memory digests.

### Verification

- Restore path and source path must be different volumes and directories.
- Backup creation while the Vault PID is alive must be rejected.
- Any archive tamper, non-empty restore, reuse of source storage, threshold
  bypass, token renewal failure, or digest mismatch is blocked.

## Phase 5: cleanup, evidence, and product safety

### What to implement

1. Stop all rehearsal Vault processes in `finally`.
2. Remove GPG secret homes, decrypted shares, tokens, key material, sentinel,
   plaintext archive, live source data, retired source data, and restored data.
3. Retain only verified software/public provenance, encrypted backup if
   requested, unit marker files, and `F:\...\evidence\rehearsal-result.json`.
4. Recursively scan retained files and repository changes for secret canaries
   and forbidden populated fields.

### Verification

- Focused rehearsal contract, existing Vault recovery drill, secret scan,
  Python compilation, and `git diff --check` pass.
- Full precloud gate passes.
- Browser-like public `/health`, `/health/deep`, and
  `/readiness/product-saas` values are unchanged before/after.
- No eBay, sync, write, charge, refund, ad, procurement, or policy-write
  endpoint is called.

## Phase 6: owner handoff and next work

Record the value-free evidence and the remaining real-custody blocker in the
latest no-loss handoff. Do not set production custody/restore evidence in the
runtime env. After this rehearsal is closed, inspect the authenticated
`ops.jiejing.shop` owner surface read-only, fix low-risk observability/UX issues,
and then execute the separately confirmation-gated payment launch plan.
