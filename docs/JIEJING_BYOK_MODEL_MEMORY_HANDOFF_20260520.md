# Jiejing BYOK Model And Merchant Memory Handoff - 2026-05-20

## Direction

Jiejing remains an eBay-first AI CEO merchant SaaS. Hermes is only historical/internal reference. Runtime and Agents operate on sanitized standard packets and must not touch eBay tokens, model API keys, refresh tokens, or cloud credentials.

## What Changed

1. Merchant BYOK model provider catalog is added.
   - Backend endpoint: `GET /model/providers/catalog`
   - File: `jiejing_saas/model_provider_catalog.py`
   - Providers include OpenAI, DeepSeek, OpenRouter, Qwen/DashScope, Moonshot, Anthropic, Google Gemini, and Tencent Hunyuan.
   - Only providers with compatible adapters can run live reports now. Native providers marked `native_pending` are catalog-only until their adapters are added.

2. Merchant model API key storage is added.
   - Backend endpoint: `POST /stores/{store_id}/model/api-key`
   - Backend stores only `secret_ref` in the SaaS database.
   - Raw API key goes through `VaultSecretResolver` into local dev resolver, Vault, or Tencent SSM/KMS depending on environment.
   - Public responses never return raw model keys.
   - Merchant pays the model provider directly from the merchant provider account.

3. Live model value rehearsal can use merchant BYOK.
   - Backend endpoint: `POST /stores/{store_id}/model/value-rehearsal`
   - It resolves the selected model `secret_ref` backend-only, builds a temporary model client in process memory, and runs only `market.report` and `listing.package`.
   - Runtime receives only the sanitized platform packet handoff.
   - No eBay write, publish, refund, ad budget, procurement payment, or policy edit can run.

4. Merchant Memory V1 is added.
   - Table: `merchant_memory`
   - Backend endpoint: `GET /merchant-memory`
   - Backend endpoint: `POST /stores/{store_id}/merchant-memory/refresh`
   - `save_runtime_outputs` automatically writes memories for reports and confirmation-center items.
   - Existing report/confirmation records can be backfilled into memory with the refresh endpoint.

5. Workbench UI is wired.
   - The merchant workbench now shows a model account panel with provider official API-key links.
   - Merchant can paste a model API key once, save it to the secret boundary, then clear the input.
   - Merchant can trigger live Market Report + Listing Package once a model key and packet are available.
   - Merchant Memory panel shows saved report/confirmation memories.

## Tests

Run from `software-demo`:

```powershell
python -m compileall jiejing_saas jiejing_runtime
node --check app.js
python tools\test_jiejing_merchant_byok_model_and_memory.py
python tools\test_jiejing_model_value_rehearsal.py
python tools\test_jiejing_saas_backend_mvp.py
```

Current result: all passed locally.

## Remaining Product Truth

This implements the BYOK path and live-report trigger, but a real paid value proof still requires a merchant-provided valid model API key and an actual run against the current sanitized eBay packet. Do not claim paid SaaS launch readiness until model outputs are reviewed, stable domain/TLS/callback/CORS are finalized, backup restore drill is proven, and billing/legal gates are completed.
