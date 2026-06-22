# Jiejing Real eBay BYOK Value Proof - 2026-05-21

## Scope

Active staging route:

```text
https://individually-buffalo-prescribed-blocking.trycloudflare.com
```

This run used the real merchant eBay read-only OAuth path and the merchant BYOK model secret boundary. No real eBay publish, revise, refund, ad, payment, procurement, buyer-message send, or policy edit was enabled.

```text
real_platform_writes_enabled=false
secret_exposed=false
```

## eBay OAuth Result

The merchant store is now connected at the backend platform-connection layer:

```text
store_id=store_bdce2f90f8259912
company_id=company_e74e9d3dfb2a7332
oauth_status=callback_exchange_completed
connection_status=read_only_authorized
secret_purpose=ebay_refresh_token
secret_status=managed_vault_stored
```

If the browser shows `blocked_invalid_state`, it means an old callback URL was refreshed or reused. It is not proof that the store is disconnected.

## Official eBay Packet

An official read-only sync was run and completed:

```text
task_id=task_cc8740ba2fcd18d9
job_id=job_f999e3d7471834
live_read_performed=true
```

Latest packet:

```text
packet_id=packet_0b5dd20476f71eab
source_mode=official_api
status=packet_cached_with_source_gaps
ready_for_runtime=true
safe_for_reports=true
safe_for_real_platform_write=false
```

Present resource keys:

```text
store_profile
account_business_policies
inventory_and_offers
orders_and_fulfillment
finances
taxonomy_listing_metadata
```

Known gaps:

```text
marketing_readonly -> HTTP 403
inventory_and_offers -> partial, one offer path returned HTTP 400
field_gap_count=9
source_gap_count=1
```

Important quality note: this packet is strong enough for store-level evidence and confirmation boundaries, but it does not contain enough concrete listing/product facts to produce a high-quality single-product listing package without merchant-supplied supplier/product/material/image/cost data.

## BYOK Model Result

The merchant DeepSeek secret was already stored as a `secret_ref`. The non-sensitive metadata had an incorrect `base_url` pointing to the DeepSeek documentation page:

```text
before=https://api-docs.deepseek.com/zh-cn
after=https://api.deepseek.com/v1
```

Only metadata was corrected. The raw model key was not read into the frontend and was not printed.

Live model-backed value proof completed:

```text
task_id=task_ae15a82adb1c072d
packet_id=packet_0b5dd20476f71eab
live_model_report_types=market.report, listing.package
runtime_gets_sanitized_packet_only=true
runtime_gets_raw_ebay_token=false
frontend_gets_model_api_key=false
real_platform_writes_enabled=false
```

Reports created:

```text
report_6bb3f13a3559596c -> market.report -> live_http_model applied
report_1691dff86139401d -> listing.package -> live_http_model applied
```

Confirmation center items created:

```text
Confirm real eBay publish -> pending -> hold
Confirm store policy use or edit -> pending -> hold
```

Merchant memory records were written for both reports and both confirmation boundaries.

## Deployed Fixes

Deployed to staging after local and remote checks:

1. eBay OAuth now navigates in the same tab instead of opening a disconnected new tab, so `sessionStorage` is preserved when returning to the workbench.
2. BYOK model base URL normalization is enforced in both frontend and backend. Obvious docs/key URLs are corrected to the provider default API base.
3. DeepSeek docs URL can no longer silently become the runtime API endpoint.

Verification:

```text
node --check app.js
python -m compileall jiejing_saas jiejing_runtime tools
python tools/test_jiejing_merchant_byok_model_and_memory.py
python tools/test_jiejing_frontend_staging_config.py
python tools/test_jiejing_saas_p0_security_guardrails.py
python tools/test_jiejing_model_value_rehearsal.py
cloud /health -> 200
cloud /auth/demo-session -> 403
cloud readiness blocker_count=0
```

## Current Product Truth

The previous blocker `model_value_proof` is now cleared for controlled staging and private-beta evidence.

This still does not mean paid public SaaS launch is ready. Remaining important risks:

1. Current browser session may still be on a login page; the user needs to log in again and refresh the workbench state.
2. Store-level official packet lacks concrete product/listing/supplier facts; single-product Listing Package quality needs merchant product input or better inventory/listing read coverage.
3. External paid billing provider is still not configured.
4. Token refresh adapter is still pending.
5. Session hardening should move toward HttpOnly secure cookies or equivalent before paid launch.
6. UI still needs a product-quality pass: account/store naming, callback recovery copy, source gaps, and store-level vs product-level report separation.

## Next Step

Use the current merchant account, not another test account:

1. Log in to the workbench.
2. Confirm the connected store shows `read_only_authorized`.
3. Confirm `packet_0b5dd20476f71eab` appears as the latest official packet.
4. Review the live model Market Report and Listing Package.
5. Do not publish; handle the two confirmation-center items as hold/review only.
