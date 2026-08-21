# Vault Production-Grade Recovery Rehearsal on E/F Volumes

## Status and decision

This design is approved in principle by the owner as the E/F-volume rehearsal path.
It produces production-grade procedural evidence with disposable credentials. It
does not create or certify the real production unseal shares and must not change
Jiejing public readiness.

The real production ceremony remains a separate event. Its three Shamir shares
must be independently controlled from the instant they are generated. The PGP
media profile retains encrypted shares on independent offline units. The
sealed-paper profile permits plaintext only on the three final paper sheets and
inside the protected ceremony process while it is running; a share may never be
written as plaintext digital data to the Windows workstation, Jiejing repository,
production host storage, logs, chat, or ordinary application state.

## Objective

Prove, before physical custody media is available, that the complete low-cost
Vault operating procedure works end to end:

1. run the same Vault Community version used by the production pilot;
2. initialize a three-share, two-share-threshold Shamir seal;
3. distribute every disposable share through a distinct PGP recipient;
4. unseal manually with exactly two independently decrypted shares;
5. install the reviewed Jiejing production policy;
6. create and renew a scoped periodic backend token;
7. store a synthetic sentinel through the KV v2 boundary;
8. stop Vault and take a consistent offline encrypted backup;
9. restore the backup into a fresh storage directory;
10. manually unseal the restored instance and resolve the sentinel;
11. retain only value-free evidence after removing disposable credentials.

HashiCorp documents `vault operator init -key-shares=3
-key-threshold=2`, PGP-encrypted unseal shares, and an independently encrypted
initial root token. HashiCorp also recommends an offline backup when the storage
backend does not provide atomic snapshots. The rehearsal follows those contracts.

## Production-grade versus production-certified

The rehearsal is **production-grade** because it uses the exact algorithms,
version, policy, token lifecycle, offline-backup sequence, restore isolation,
failure handling, and evidence schema intended for production.

The rehearsal is **not production-certified** because the simulated custody
units reside on the E and F volumes of one physical disk 0. Those volumes cannot
satisfy the three-independent-custody-unit requirement, regardless of directory
separation, ACLs, encryption, or a later copy to USB media.

No rehearsal result may set or imply any of the following:

- `JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED=true`
- a non-zero production custody-unit count;
- a production backup artifact identifier;
- a production restore-drill timestamp;
- `production_ready=true`;
- `can_accept_real_customers=true`;
- public charging, refund, public eBay publish, or broad platform writes.

## Environment and isolation

Read-only Windows storage discovery established that `E:` and `F:` are healthy
NTFS volumes, but they are partitions 2 and 3 of the same physical disk 0
(`TOSHIBA MQ04ABF100`). They are useful for proving a cross-volume restore path,
but they represent one physical failure and custody domain.

The source and restore roots are:

```text
E:\Jiejing-Vault-Recovery-Rehearsal-Source
F:\Jiejing-Vault-Recovery-Rehearsal-Restore
```

Both directories must remain on their discovered NTFS volumes and must receive
an explicit ACL that grants full control only to the current Windows account,
`SYSTEM`, and the local Administrators group. Inherited access is removed. If
either filesystem, volume-to-disk mapping, or ACL cannot be verified, the
rehearsal stops before downloading or generating any credential.

Vault listens only on `127.0.0.1`. No firewall opening, port forwarding, public
DNS, production hostname, Tencent production container, or production private
environment file is used.

The exact trees are:

```text
E:\Jiejing-Vault-Recovery-Rehearsal-Source\
  software\
  config\
  live-data\
  original-retired\
  backup-staging\
  simulated-unit-A\
  simulated-unit-C\
  simulated-root-operator\

F:\Jiejing-Vault-Recovery-Rehearsal-Restore\
  encrypted-backup\
  isolated-restore\
  simulated-unit-B\
  simulated-backup-key-unit\
  evidence\
```

Every simulated unit is marked `NON_PRODUCTION_REHEARSAL_ONLY`. Directory names
and distinct drive letters are not evidence of physical separation. Evidence
must state `discovered_physical_disk_count=1` and
`production_custody_credited=false`.

## Software provenance

The rehearsal uses Vault Community `1.21.4`, matching the pinned production
pilot image. The Windows AMD64 archive and its checksum manifest are downloaded
only from HashiCorp's official release host over HTTPS. The archive SHA-256 must
match the signed release checksum before extraction. A checksum or signature
failure aborts the run and removes the untrusted archive.

The evidence records only the version, archive SHA-256, checksum-verification
boolean, and source host. It never records a download credential because none is
required.

## Credential distribution

The rehearsal creates four disposable PGP identities:

- A, B, and C each receive one encrypted Shamir share;
- the root-operator identity receives the encrypted initial root token.

Only public keys are supplied to `vault operator init`. Vault output is captured
in memory by the rehearsal controller and split immediately into the target
simulated units. The controller must never print the JSON response, unseal share,
root token, backend token, backup key, or sentinel value.

The production ceremony supports two explicit profiles. **PGP media custody**
replaces the simulated identities with public keys whose private keys are created
and retained on three genuinely independent offline digital units. It uses the
same `-pgp-keys` mechanism so plaintext production shares never pass through the
Windows workstation or remain on the production host.

**Sealed-paper custody** is the no-device profile. It must use a direct trusted
local console with every recording, automation, remote-assistance, clipboard,
camera, and print-spool path disabled. A protected human-only controller keeps
the initialization response in process memory, reveals one share at a time for
a double transcription check, proves one-share-sealed and two-share-unsealed by
protected interactive input, completes setup, revokes root, clears scrollback,
and exits without an initialization file or any other plaintext digital residue.
The three paper shares are sealed immediately and moved to three independent
physical custody units, with no unit or custodian holding two shares.

The rehearsal remains deliberately PGP-only: it proves the Vault lifecycle,
threshold, backup, restore, policy and cleanup contracts, but does not prove the
paper ceremony or grant production custody credit. Production custody credit is
issued only after the selected real-media profile is witnessed, an independent
restore is manually unsealed, the sentinel is resolved value-free, and the
existing distribution evidence is recorded. A browser-controlled terminal,
Codex session, cloud transcript, screenshot, phone photo or synced print queue
can never satisfy the sealed-paper profile.

The WSL GnuPG clock was observed up to roughly three minutes ahead of the
Windows Vault process. Disposable rehearsal keys are therefore generated with a
fixed five-minute creation-time offset into the past and a one-day expiry. This
keeps Vault's future-key check strict while bounding the compatibility offset;
the production ceremony must use synchronized operator clocks rather than rely
on this rehearsal-only offset.

## Vault lifecycle

### Initialization

The controller starts Vault with file storage under `live-data` and a loopback
listener. It asserts the server is uninitialized, then initializes exactly three
shares with threshold two and PGP encryption.

The controller proves the threshold contract twice:

1. after submitting only share A, Vault remains sealed;
2. after submitting share B, Vault becomes unsealed.

The third share is not used during the first unseal.

### Policy and periodic token

The decrypted disposable root token is used only to:

1. enable KV v2 at `secret/`;
2. install `deploy/vault-policy.production.hcl` under a rehearsal policy name;
3. create a scoped periodic backend token;
4. verify `renewable=true` and a positive period;
5. revoke the initialization root token.

The scoped token must successfully renew itself and must not acquire root,
sudo, system-configuration, or unrelated secret-path capabilities.

### Sentinel

The controller writes a random disposable sentinel to the rehearsal keyspace
using the scoped backend token. Evidence retains only:

- the sentinel reference SHA-256;
- the sentinel payload SHA-256;
- write success;
- later resolve success;
- equality of the two in-memory digests.

The reference and payload are never emitted into evidence or logs.

## Offline backup and restore

Vault is stopped before copying file-backend storage. The controller verifies
that no Vault process has the storage directory open, then creates a consistent
archive in `backup-staging`.

The archive is encrypted with a fresh 256-bit rehearsal-only key. The key is
stored only in the F-drive `simulated-backup-key-unit`, separate by directory
from the encrypted backup and the three simulated unseal units. This is logical
separation for rehearsal, not a second physical custody boundary. Plaintext
backup staging is removed after the encrypted artifact is durably written and
its SHA-256 recorded.

To prove a real restore rather than a restart:

1. rename the original storage to `original-retired`;
2. create an empty `isolated-restore` directory;
3. decrypt the backup into that fresh directory;
4. start a new Vault process against the restored path;
5. prove share A alone leaves it sealed;
6. unseal with share B;
7. authenticate with the pre-backup scoped periodic token;
8. renew the token;
9. resolve the sentinel and compare only in-memory digests.

Any restore that reads from `original-retired`, reuses `live-data`, or succeeds
without the threshold proof is invalid.

## Evidence contract

The only durable result is `evidence/rehearsal-result.json`. It contains:

- contract version and UTC timestamps;
- `mode=non_production_production_grade_rehearsal`;
- Vault version and verified binary SHA-256;
- loopback-only listener proof;
- E/F filesystem, ACL, disk-number, and same-physical-disk verification;
- `discovered_physical_disk_count=1`;
- share count, threshold, simulated custody-unit count, and maximum shares per
  simulated unit;
- PGP-encryption and encrypted-root-token booleans;
- single-share-remains-sealed and two-share-unseal booleans;
- exact production-policy file SHA-256;
- periodic-token renewable/positive-period/renew-self booleans;
- offline-stop, encrypted-backup, fresh-restore, manual-unseal, and sentinel
  digest-match booleans;
- `production_readiness_credited=false`;
- `real_platform_writes_enabled=false`;
- `public_charging_allowed=false`;
- `secret_exposed=false`.

Before success, a recursive sentinel scan must prove that the evidence,
transcript, repository, and non-secret retained files contain none of the
disposable secret canaries or sensitive field names with values.

## Failure and cleanup

The controller fails closed on any checksum, ACL, listener, initialization,
threshold, policy, token, backup, restore, sentinel, or secret-scan mismatch.
It never falls back to development mode, a one-share threshold, plaintext init
output, a public listener, the production server, or the live Jiejing Vault.

On success or failure it stops the local Vault process. On success it removes:

- decrypted PGP private-key working copies;
- disposable Shamir shares;
- disposable root and backend tokens;
- the backup encryption key;
- the sentinel value;
- plaintext backup staging;
- `live-data`, `original-retired`, and `isolated-restore`.

It retains only verified software, public keys, the encrypted disposable backup
if explicitly requested, and value-free evidence. Because secure deletion on an
SSD cannot be guaranteed, all generated credentials are disposable and are
never promoted to production.

## Tests and acceptance criteria

The rehearsal is complete only when all of the following pass:

1. E and F are NTFS, their root ACLs match the allowlist, and evidence truthfully
   records that both volumes map to physical disk 0.
2. Vault version and official checksum match.
3. The listener is loopback-only.
4. Initialization reports exactly three encrypted shares and threshold two.
5. One decrypted share keeps Vault sealed; two unseal it.
6. The production policy digest matches the repository file.
7. The scoped token is periodic, renewable, and successfully renewed.
8. Root-token revocation succeeds before backup.
9. The file-backend backup is taken only while Vault is stopped.
10. The encrypted backup crosses from E to F and restores into a fresh directory.
11. The restored Vault repeats the one-share/two-share seal proof.
12. The restored scoped token resolves the sentinel with matching digests.
13. No raw credential or sentinel appears in evidence, logs, repository files,
    shell history, process arguments, or retained plaintext artifacts.
14. Public Jiejing health and readiness are unchanged before and after.
15. No eBay OAuth, eBay sync, eBay write, payment, refund, media purchase, ad,
    procurement, or policy-write endpoint is called.

## Production follow-through

After the rehearsal passes and three real custody units are available, the
production ceremony repeats the validated sequence with these changes:

- for PGP media custody, each PGP private key is created and kept on a different
  offline unit, only the three public keys are presented to initialization, and
  encrypted shares A, B, and C are transferred directly to their matching units;
- for sealed-paper custody, the direct trusted local console reveals one share at
  a time for double-checked hand transcription, then proves the threshold and
  leaves no plaintext digital residue before the envelopes are distributed;
- for PGP media custody, the root token is separately encrypted; for sealed-paper
  custody it remains only in the protected ceremony process; in both profiles it
  is used briefly and revoked before the session ends;
- the encrypted backup is moved off-host and its key is held separately;
- an independent restore is manually unsealed and resolves a production
  sentinel without exposing its value;
- only then may the value-free production evidence fields be recorded and the
  production pilot/release gate rerun.

Public charging, refunds, broad eBay writes, and public listing remain separate
owner-confirmed gates even after Vault recovery readiness is satisfied.
