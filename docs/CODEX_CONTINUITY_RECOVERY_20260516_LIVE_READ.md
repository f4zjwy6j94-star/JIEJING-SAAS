# Jiejing SaaS Continuity Update 2026-05-16

This note supersedes the older local-dev snapshot that said `EBAY_CREDENTIAL_PRESENT=False`.

## Verified Direction

- Keep Jiejing as the eBay-first AI CEO SaaS product.
- Keep Hermes internal as a local legacy credential bridge and reference worker only.
- Runtime and frontend must only receive sanitized packets, source records, work records, reports, and confirmation items.
- Real eBay writes remain disabled and confirmation-gated.

## Verified Live Read Smoke

Repeatable command:

```powershell
python tools\jiejing_ebay_readonly_live_smoke.py --local-hermes-bridge
```

The command enables these process-local read switches:

```powershell
JIEJING_ENABLE_HERMES_EBAY_BRIDGE=true
JIEJING_EBAY_AUTO_REFRESH=true
JIEJING_EBAY_READ_ONLY_LIVE=true
JIEJING_EBAY_TOKEN_REFRESH_LIVE=true
```

Latest verified result:

- eBay preflight: `ready_for_official_read`
- Token mode: `backend_legacy_credential_bridge`
- Live read status: `completed_live_read`
- Official eBay GET requests: `12`
- Data packet source mode: `official_api`
- AI CEO workflow: `completed_with_blocks`
- Runtime reports saved: `11`
- Pending confirmation items: `9`
- Real platform writes enabled: `False`
- Secret exposed: `False`

Current packet coverage after fixing the official route roots:

- Present: `store_profile`, `account_business_policies`, `inventory_and_offers`, `orders_and_fulfillment`, `finances`, `taxonomy_listing_metadata`
- Missing/source-gap: none in the latest smoke

Output summaries:

```text
output/jiejing-saas-backend/local-ebay-readonly-live-smoke/live_smoke_latest.json
output/jiejing-saas-backend/local-ebay-readonly-live-smoke/live_readonly_sync_summary.json
output/jiejing-saas-backend/local-ebay-readonly-live-smoke/ai_ceo_workflow_from_official_packet_summary.json
```

Frontend browser verification command:

```powershell
node tools\jiejing_frontend_route_health_browser_smoke.js
```

Latest verified browser result:

- `routeStripCount`: `2`
- `packetPresentCards`: `6`
- `routeOkCards`: `6`
- `requestCount`: `12`
- `routeResultCount`: `6`
- `missingResources`: `[]`
- Frontend shows `Official read`, `Store profile`, and `Finances` from real backend state.

## Verified Jiejing-Owned Credential Chain

Repeatable command:

```powershell
python tools\jiejing_ebay_jiejing_credential_chain_smoke.py
```

This smoke explicitly disables the legacy Hermes eBay credential bridge and uses a fake backend transport, so it does not call real eBay or expose real seller credentials. It proves the Jiejing-owned credential boundary can replace the local bridge for read-only sync once production OAuth/Vault is configured.

Latest verified result:

- Overall status: `pass`
- Cases passed: `4 / 4`
- Hermes bridge enabled: `False`
- Secret leak check: `pass`
- Real platform writes enabled: `False`

Credential sources covered:

- `backend_env_access_token`
- `backend_jiejing_local_oauth_store`
- `backend_jiejing_secret_ref_resolver` with local secret resolver
- `backend_jiejing_secret_ref_resolver` with managed Vault-shaped resolver

Each case completed:

- eBay preflight: `ready_for_official_read`
- Live read status: `completed_live_read`
- Official route requests: `12`
- Present resources: `store_profile`, `account_business_policies`, `inventory_and_offers`, `orders_and_fulfillment`, `finances`, `taxonomy_listing_metadata`
- Missing/source-gap resources: none
- Runtime packet status: `packet_cached_sanitized`

Output summary:

```text
output/jiejing-saas-backend/jiejing-owned-credential-chain-smoke/latest.json
```

The productization gate now includes this as `jiejing_owned_credential_chain_smoke` under Stage 3, so non-Hermes credential regressions are visible in:

```powershell
python tools\jiejing_productization_stage_gate.py
```

## Verified OAuth Callback Vault Storage

Repeatable command:

```powershell
python tools\test_jiejing_ebay_oauth_callback_vault.py
```

Latest verified result:

- OAuth callback exchanges authorization code through the backend token endpoint client.
- The callback writes only the seller refresh token to the configured secret resolver.
- Local development path uses `local_secret_resolver`.
- Managed production-shaped path uses `managed_hashicorp_vault`.
- The SaaS database stores only `secret_ref` and `platform_connection` metadata.
- Public callback response returns no access token, refresh token, client secret, Vault token, `Bearer` header, or `Basic` header.
- Production-like mode blocks before token exchange if only the local secret resolver is enabled.

Implemented backend boundary:

- `jiejing_saas/ebay_oauth_callback.py`
- `VaultSecretResolver.store_secret(...)`
- `VaultSecretResolver._write_hashicorp_vault_secret(...)`
- `SaaSRepository.update_secret_reference_status(...)`

The productization gate now also includes this as `ebay_oauth_callback_vault_storage` under Stage 3.

## Next Work

Do not rebuild the credential bridge from scratch. The next product work is:

- Keep per-resource route visibility in the smoke output so endpoint or scope regressions are visible.
- Keep standardizing official read results into `platform_data_packet`.
- Continue making the AI CEO workbench read real backend packets, reports, source records, and confirmations.
- On a real staging domain, configure eBay RuName/callback URL and managed Vault credentials, then run one real seller OAuth authorization through this Jiejing-owned callback path.
