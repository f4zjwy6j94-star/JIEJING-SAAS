# Jiejing eBay Marketplace Account Deletion Design

Date: 2026-07-13
Status: approved for implementation

## Goal

Restore truthful eBay production-key compliance without using the frozen seller account or weakening Jiejing's backend-only secret boundary.

The public contract is:

- `GET /webhooks/ebay/marketplace-account-deletion?challenge_code=...`
- `POST /webhooks/ebay/marketplace-account-deletion`

The endpoint verifies the official eBay signature, durably persists a sanitized receipt, and acknowledges the request quickly. Destructive processing happens asynchronously only after signature verification and tenant identity resolution.

## Trust Boundaries

- The verification token is injected through the backend environment or Vault. It is never stored in the SaaS database, returned to the frontend, logged, or included in audit records.
- eBay notification bodies are untrusted input. Body size, content type, topic, schema, identifiers, and signature metadata are validated.
- A notification is not authority to delete an arbitrary tenant. The immutable eBay user identifier must resolve to an existing eBay platform connection.
- OAuth requests include `commerce.identity.readonly`. After code exchange, the backend calls the eBay Identity API with the transient access token and stores only irreversible user and username hashes; raw identity and profile fields are discarded.
- Unknown identities remain quarantined for operator review. Jiejing never performs tenant-wide deletion as a fallback.

## Challenge Verification

For a bounded `challenge_code`, return:

`SHA256(challenge_code + verification_token + canonical_endpoint_url)`

The response is JSON with one `challengeResponse` field. Missing configuration, malformed input, or a non-canonical endpoint fails closed without disclosing which secret component was missing.

## Notification Intake

1. Reject oversized or malformed JSON.
2. Require the marketplace account deletion topic and required identifiers.
3. Decode the signature header, fetch/cache the eBay public key, and verify the compact JSON payload using the official SDK-compatible algorithm.
4. Derive an idempotency key from the immutable notification identifier.
5. Persist only a sanitized envelope and signature metadata. Do not persist authorization headers, cookies, raw secrets, or an unbounded raw request.
6. Return HTTP 202 for the first accepted notification and for an exact duplicate. Signature failures return 412; temporary verification-provider failures return 503 so eBay retries.
7. Queue one background compliance job per matched connection.

## Asynchronous Processing

1. Resolve the immutable eBay user identifier to the matching platform connection.
2. Revoke the seller credential reference through the existing Vault boundary.
3. Delete or irreversibly anonymize eBay-derived merchant and customer data for that connection.
4. Preserve only a sanitized compliance receipt: notification hash, processing timestamps, affected record counts, result status, and legal-retention reason when applicable.
5. Retry transient failures up to five attempts. Local and Redis workers preserve attempt accounting; permanent failures enter dead letter with an operator-safe audit message.
6. Reauthorization does not weaken deletion: every eBay connection and credential reference attached to the matched store is revoked, not only the newest connection row.

## Data Scope

Deletion or irreversible anonymization covers records tied to the matched eBay store/connection, including platform packets, tasks and outputs, reports, confirmations, execution receipts, merchant memory, AI CEO records containing eBay-derived data, media jobs and source assets, and connection metadata.

Company billing, unrelated stores, unrelated platform connections, and account login records are not deleted by an eBay marketplace-account notification.

Where law requires retention, direct eBay identity and customer personal data are removed and the retained record is reduced to the minimum non-identifying compliance or accounting fields.

## Failure and Abuse Handling

- Shared database rate limits protect both challenge and notification routes.
- Body and field lengths are bounded before hashing or persistence.
- Duplicate delivery is idempotent.
- Signature failure never mutates merchant data.
- Unknown identity never mutates merchant data.
- Queue recovery, retry limits, dead-letter state, operational metrics, and audit records expose failures without exposing payload secrets.
- Application access tokens and public verification keys are cached in backend memory with bounded lifetimes and bounded key-cache size to reduce provider load under duplicate or abusive deliveries.
- Real eBay listing, inventory, offer, advertising, refund, payment, and policy writes remain disabled.

## Deployment Sequence

1. Land tests and implementation.
2. Inject a new verification token through the staging secret boundary.
3. Deploy and verify health, readiness, challenge response, duplicate intake, and no-secret logs.
4. In eBay Developer Portal, remove the inaccurate exemption and register the endpoint and token.
5. Send eBay's test notification and verify the durable receipt.
6. Rotate the potentially exposed production client secret with an atomic backend secret update.
7. Run OAuth only for the new seller account, then prove refresh and read-only synchronization. Do not perform a real platform write.

## Acceptance Criteria

- Challenge vectors match the eBay algorithm exactly.
- Missing secret configuration fails closed.
- Oversized, malformed, wrong-topic, and incomplete requests are rejected.
- First delivery and exact duplicate produce one durable event and one job.
- Invalid signatures and unknown users cause zero merchant-data mutations.
- A verified, mapped notification revokes the connection secret reference and purges/anonymizes only the matched eBay store's data.
- Tests pass on SQLite and the PostgreSQL migration path.
- Secret scan, readiness, health, and public smoke pass after deployment.
- `production_ready` remains false until all independent launch blockers are genuinely resolved.
