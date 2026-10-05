# Production Vault recovery evidence renewal

## Status and scope

The owner has now confirmed being at the computer with any two existing A/B/C
shares and asked to continue the bounded short maintenance and recovery task.
The implementation passed 18 focused tests locally and on NEW. A no-secret
remote dry-run and memory-protection probe passed. A separate owner-only hidden
input window is open; actual recovery success remains unverified until its
backend receipt and live health have been checked. See the current execution
index for the exact helper hashes and evidence locations.

This is not a website migration, a new Vault initialization, a rekey, a storage
engine migration, a deployment, an eBay action, or permission to retire OLD.
Preserve the existing A/B/C paper custody arrangement and all source data.

## Verified baseline

- Production app release: `20260923T161500Z-e9a158088fab`.
- API and Worker both report only `vault_restore_drill_overdue` for backup
  readiness. PostgreSQL restore evidence, COS probe and backup-alert flags were
  valid in the preceding read-only diagnostic. Do not rerun those tasks.
- NEW Vault is healthy, unpaused, file-backed, version `1.21.4`, image digest
  `sha256:4e33b126a59c0c333b76fb4e894722462659a6bec7c48c9ee8cea56fccfd2569`.
- The current encrypted storage inventory contains 46 regular files totalling
  27,282 bytes, no special entries. This is metadata, not a consistent snapshot.
- NEW has approximately 33.3 GB free disk and 2.26 GB available memory at the
  observed time. A new cloud purchase is not required for this isolated test.
- Existing operator scripts and sentinel-evidence files were located. Secret
  file contents were not read. Local LF-normalized unseal/restore-controller
  hashes match the existing server copies. The legacy backup shell script does
  not match and is not approved for unreviewed reuse.
- Read-only receipts live in the task workspace's
  `output/backup-readiness-20260924/result-attempt3.json` and
  `output/backup-readiness-20260924/recovery-preflight.json`.

## Options and decision

1. **Recommended: a new offline file-backend backup and isolated restore.**
   Obtain a current consistent artifact, bring production back first, then
   verify the independent restored copy. It needs owner participation and a
   short maintenance window, but does not change the architecture.
2. Repeat the August process-freeze archive. It avoids a production re-unseal,
   but a frozen process is not proof of a gracefully completed set of file
   writes. Do not upgrade that older approach to a clean offline backup claim.
3. Migrate to Integrated Storage for online snapshots. That is a distinct
   architecture change, excluded from this evidence-renewal task.

HashiCorp recommends offline backups for storage without atomic snapshots:
[Vault storage guidance](https://developer.hashicorp.com/vault/docs/concepts/storage#backing-up-vaults-persisted-data).
The configured [file backend](https://developer.hashicorp.com/vault/docs/configuration/storage/filesystem)
must not be sent Raft snapshot commands. These references guide the choice;
they do not certify this installation or grant maintenance authority.

## Execution boundaries

1. Finish a version-bound, dry-run-only preparation. Resolve current container
   IDs, image, volume, configuration and private-file references; never depend
   on mutable image names, historic release paths or the production DNS alias
   alone. Check isolation and rollback before any interruption.
2. Owner availability and two distinct existing paper shares are mandatory
   before stopping production. Input is through an owner-operated, unrecorded
   TTY with hidden input, no getpass fallback, locked memory and core dumps
   disabled. No browser form, chat, shell arguments, environment variables,
   clipboard automation or agent-observed terminal may carry share values.
3. Before production interruption, establish that the material can recover the
   current seal configuration in an isolated precheck. An incomplete/live-copy
   precheck, if used, is not credited as a consistent backup or formal recovery
   drill. If that check cannot be established safely, stop before maintenance.
4. Capture only after a confirmed clean Vault shutdown; no automatic forced
   kill, initialization, rekey, private-permission repair or unseal-key storage.
   Bound the operation with an independent restart path. Restart cannot bypass
   Shamir unsealing: the owner must remain available. Do not promise unattended
   recovery after a restart.
5. Store the new encrypted storage artifact and configuration binding under a
   new backend-only run directory; never overwrite the original volume, old
   backups or prior evidence. Verify artifact hashes and safe archive members.
   Restore uses a new empty volume, exact local image, internal-only network,
   no published ports, no production volume mount and no cloud downloads.
6. Resume and unseal production first, verify health and the existing backend
   token's status without exposing it. Do not proceed with an unhealthy live
   service. Isolated-controller routing must be independently checked before
   sending shares, even though the old scripts use the same hostname alias.
7. Independently unseal the restored copy with two distinct shares and verify
   the existing synthetic sentinel digest and scoped-token contract. Keep all
   values inside the protected backend boundary. No merchant secret exports,
   model calls, OAuth, platform sync, payment or refund are part of the test.
8. Persist only run ID, artifact/configuration bindings, validated states and
   actual UTC timestamps. Stop the isolated instance after verification;
   retain artifacts/volume, do not delete them under this authorisation.
9. Registration is a separate final step, permitted only after real successful
   evidence is bound to this run. Preserve the 30-day policy. Never refresh a
   date from a mock, an old successful receipt, or an operator's assertion alone.
   Re-read readiness afterwards; do not infer public-launch readiness or enable
   real platform writes from this one evidence track.

## Failure and regression acceptance

- A wrong release/container/volume/network, occupied restore destination,
  symlink or invalid artifact must fail before modifying production.
- Wrong/missing shares, non-TTY input, memory-lock failure or unknown target
  must fail without echo, traceback values, root-token generation or live seal.
- A backup or interrupted operator session must not strand production silently;
  prove the restart/recovery path with disposable local fixtures first.
- One share remains sealed, two distinct shares unseal; repeated shares or a
  sentinel mismatch cannot produce successful evidence.
- A stale, partial or foreign-run receipt must not update readiness timestamps.
- Local fixture tests are never production proof. A generic green healthcheck
  does not prove backup consistency, custody, independent recovery or retirement.

## Current stop point

The bounded R2 drill is now complete and independently read back. Its cold
archive hash is `41cd2086849455fab1c6a96af8b03372c85138639dd79f57dfdbabb738e851fb`;
the successful drill receipt hash is
`8887a56db4144430f7e7623a2d6df4fe60616fe54440d367c7be9ffc94063e13`.
An owner-only off-host encrypted-storage copy was hash-verified. Only the
artifact identifier and actual drill timestamp were registered; the 30-day
policy and existing custody/payment/platform controls were preserved.

The first registration wrapper rejected an old-runtime equality assertion after
its reload. This failed wrapper receipt is retained. An independent readback
verified the two-field source change and both runtime environments against the
actual Compose plus image model without repeating the reload; it then recorded
completion. The original old-runtime differences were not retained, so their
exact cause is not retroactively asserted. Public and dual-runtime backup
readiness are now true. These results do not authorize retiring OLD or writing
to eBay. See the current execution index for exact evidence paths. Do not rerun
the completed drill, legacy backup shell or paper initialization controller.
