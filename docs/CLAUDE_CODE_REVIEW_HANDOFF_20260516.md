# Claude Code Review Handoff - Jiejing SaaS

Repository:

```text
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
```

This handoff is for an external code review. Please review the codebase in place. Do not redefine the product direction.

## Product Direction

Jiejing is an eBay-first AI CEO SaaS for cross-border e-commerce sellers.

The intended product is an AI e-commerce operations workbench:

- Merchant connects eBay.
- Jiejing reads store, listings, orders, fees, business policies and taxonomy data.
- Jiejing builds sanitized standard data packets.
- Jiejing Runtime / Agent Team produces market, listing, asset, customer-service, finance and confirmation-center work records.
- Human confirmation is required before high-risk actions.

Hermes is only historical/internal reference infrastructure. Public product copy and merchant-facing UX must stay on Jiejing / AI CEO / SaaS workbench. Hermes must not become the customer-facing product architecture.

Do not turn this into a generic ERP, generic chatbot, or managed-operations outsourcing product.

## Non-Negotiable Safety Boundaries

- Real eBay writes remain disabled.
- Publishing, revising listings, changing price/inventory, refunds, ads, payments, procurement and policy edits must stay confirmation-gated.
- Frontend must never receive `access_token`, `refresh_token`, client secret, Vault token, raw authorization header, or raw provider secret.
- Runtime and Agent reports must receive sanitized packets/source records only.
- SaaS database must store only `secret_ref` and redacted metadata for credentials, never raw token values.
- Missing official data must be shown as source gaps or blockers, not silently inferred.

## Current Verified Status

Approximate current state:

- Formal SaaS backend skeleton: 92%-94%
- eBay read-only integration: 98% locally verified through real Hermes bridge; Jiejing-owned credential chain is production-shaped but still needs real staging OAuth.
- Standard data packet and Runtime handoff: 96%
- Frontend backend-real display: 90%
- Jiejing-owned OAuth/Vault credential boundary: 80%-85%
- Overall commercial SaaS readiness: 64%-68%

Important distinction:

- Real eBay read-only live smoke currently passes through the legacy local Hermes credential bridge.
- Jiejing-owned credential chain now passes callback/Vault/secret_ref/connection tests with fake transports and managed-Vault-shaped tests.
- The remaining real-world blocker is a real staging domain + eBay RuName/callback URL + managed Vault/KMS credentials + one real seller OAuth authorization through the Jiejing callback path.

## Latest Continuity Notes

Read these first:

```text
docs\CODEX_CONTINUITY_RECOVERY_20260516_LIVE_READ.md
docs\CODEX_CONTINUITY_RECOVERY_20260515.md
docs\JIEJING_FORMAL_SAAS_BACKEND_MVP_20260515.md
docs\JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md
```

The 2026-05-16 continuity note supersedes the older local-dev note that said `EBAY_CREDENTIAL_PRESENT=False`.

## Main Review Targets

Please focus review on these areas first.

### 1. OAuth Callback and Vault Storage

Key files:

```text
jiejing_saas\api_server.py
jiejing_saas\ebay_oauth.py
jiejing_saas\ebay_oauth_callback.py
jiejing_saas\ebay_oauth_token_store.py
jiejing_saas\vault_secret_resolver.py
jiejing_saas\repository.py
tools\test_jiejing_ebay_oauth_callback_vault.py
```

Expected behavior:

- Backend receives eBay OAuth `code`.
- Backend exchanges code at eBay token endpoint.
- Backend extracts `refresh_token`.
- Backend writes refresh token to the configured secret resolver:
  - local development: `local_secret_resolver`
  - production-shaped managed path: `managed_hashicorp_vault`
- Database persists only `secret_ref` and `platform_connection`.
- Public callback response does not expose token values.
- Production-like mode blocks before token exchange if managed Vault is not ready.

Review questions:

- Can raw token values leak through callback response, audit logs, repository metadata, SQLite rows, or error paths?
- Is token exchange correctly blocked before touching eBay when Vault/KMS is not production-ready?
- Does the callback still depend on the older local OAuth token store anywhere it should not?
- Are state validation and callback replay/idempotency good enough for the next production step?

### 2. eBay Read-Only Live Client and Route Health

Key files:

```text
jiejing_saas\ebay_http_client.py
jiejing_saas\ebay_live_read_adapter.py
jiejing_saas\ebay_credential_preflight.py
jiejing_saas\ebay_data_packet.py
jiejing_saas\ebay_read_normalizers.py
tools\jiejing_ebay_readonly_live_smoke.py
tools\jiejing_ebay_jiejing_credential_chain_smoke.py
tools\test_jiejing_ebay_live_read_http_client.py
```

Expected behavior:

- Official read-only GET routes cover:
  - `store_profile`
  - `account_business_policies`
  - `inventory_and_offers`
  - `orders_and_fulfillment`
  - `finances`
  - `taxonomy_listing_metadata`
- Finances uses the `apiz` eBay API root.
- Store profile uses `/sell/account/v1/privilege`.
- Raw eBay responses and tokens are not stored in packets.

Review questions:

- Are the route contracts correct and future-proof enough?
- Is response normalization robust enough when eBay returns partial/error-shaped responses?
- Are finance/order fields sufficiently PII-safe?
- Are API permission failures surfaced as route gaps instead of account-disconnect false alarms?

### 3. Standard Data Packet and Runtime Handoff

Key files:

```text
jiejing_saas\platform_data_packet_handoff.py
jiejing_saas\ebay_data_packet.py
jiejing_saas\task_secret_grants.py
jiejing_runtime\
```

Expected behavior:

- Runtime receives sanitized packet sections only.
- Source gaps are explicit.
- Reports and confirmation center can reference packet sections without needing raw platform credentials.

Review questions:

- Can Runtime or provider jobs ever get raw secrets by accident?
- Are packet lineage/source labels sufficiently auditable?
- Is the packet schema stable enough for frontend and Agents?

### 4. Frontend SaaS Workbench

Key files:

```text
app.js
styles.css
index.html
tools\jiejing_frontend_route_health_browser_smoke.js
```

Expected behavior:

- Frontend reads backend readiness, queue, reports, confirmations, execution results, eBay credential preflight, live route health and latest packet coverage.
- Frontend does not expose Hermes publicly.
- Frontend does not pretend demo data is real backend data.

Review questions:

- Which panels still use static/demo constants where backend state should be used?
- Is the eBay sync status understandable for a merchant?
- Are confirmation-center and source-record boundaries clear enough?

### 5. Productization Gate and Tests

Key files:

```text
tools\jiejing_productization_stage_gate.py
tools\test_jiejing_saas_backend_mvp.py
tools\test_jiejing_ebay_oauth_callback_vault.py
tools\test_jiejing_vault_secret_resolver.py
tools\test_jiejing_ebay_credential_preflight.py
tools\test_jiejing_ebay_live_read_http_client.py
tools\jiejing_ebay_jiejing_credential_chain_smoke.py
```

Expected current passing commands:

```powershell
node --check app.js
python tools\test_jiejing_ebay_oauth_callback_vault.py
python tools\test_jiejing_saas_backend_mvp.py
python tools\test_jiejing_vault_secret_resolver.py
python tools\test_jiejing_ebay_credential_preflight.py
python tools\test_jiejing_ebay_live_read_http_client.py
python tools\jiejing_ebay_jiejing_credential_chain_smoke.py
python tools\jiejing_productization_stage_gate.py
```

Real local live-read smoke, only if local credentials/bridge are intentionally available:

```powershell
python tools\jiejing_ebay_readonly_live_smoke.py --local-hermes-bridge
```

Do not run any command that performs real eBay writes.

## Recent Implemented Changes To Review

The newest important change is OAuth callback credential productionization:

- Added `jiejing_saas\ebay_oauth_callback.py`.
- Added `VaultSecretResolver.store_secret(...)`.
- Added managed Vault-shaped write path through `_write_hashicorp_vault_secret(...)`.
- Added `SaaSRepository.update_secret_reference_status(...)`.
- Updated `api_server.py` callback handler to call `process_ebay_oauth_callback(...)`.
- Updated `ebay_oauth.py` so callback readiness requires secret resolver availability instead of the deprecated local token store.
- Added `tools\test_jiejing_ebay_oauth_callback_vault.py`.
- Added productization gate check `ebay_oauth_callback_vault_storage`.

Known fixed issue:

- OAuth code exchange was previously blocked by `JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED`, which incorrectly tied callback exchange to the deprecated local token store. It is now separated: exchange is backend-only, storage goes through Vault resolver.

## Known Remaining Gaps

These are not bugs in the local code path, but real production blockers:

- No real staging domain has been wired to eBay RuName/callback URL yet.
- Managed Tencent KMS/Aliyun KMS production client is still not implemented; current managed live write path is HashiCorp-Vault-shaped.
- Cloud Postgres/Redis/KMS deployment is not live.
- eBay write adapter remains disabled and contract-only.
- 1688, logistics, media generation and public search need more production-grade provider adapters and cost controls.
- Some frontend modules still need deeper binding to Runtime/provider outputs.

## What To Return From Review

Please return findings in this format:

1. Blocking security or credential-leak risks.
2. OAuth/Vault correctness issues.
3. eBay read-only route/data-packet correctness issues.
4. Frontend/backend-real-data gaps.
5. Production deployment risks.
6. Suggested minimal fixes, with file paths and line references.

Avoid broad rewrites unless a real bug requires them.

