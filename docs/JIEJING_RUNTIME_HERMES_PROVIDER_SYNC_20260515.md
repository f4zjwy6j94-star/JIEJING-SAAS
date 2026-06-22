# Jiejing Runtime Hermes Provider Sync 2026-05-15

This record documents the safe synchronization from the current Hermes local environment into the Jiejing-owned Runtime and Agent knowledge layer.

## What Was Synchronized

- DeepSeek model provider: available to Jiejing Runtime as the live model client when the backend environment enables it.
- Tavily public search: available to the market data packet and market report flow as public-web evidence, not as official platform sales data.
- FAL media provider: available to the asset workflow for image and video generation only when the backend explicitly requests `provider=fal` or a configured media endpoint.
- eBay provider map: Browse, Taxonomy, Account policy read, Trading, Finances, and gated write execution are recorded as Agent knowledge and provider status.
- Hermes skills and SOPs: already included through the sanitized knowledge pack, now strengthened with explicit provider inventory items.

## What Was Not Synchronized

- Raw provider credentials.
- Seller OAuth strings.
- Cookies.
- Buyer private data.
- Frontend-visible secrets.
- Any permission to publish, refund, buy, pay, edit policy, or change ads without confirmation.

## Runtime Behavior

- Provider status is visible through the local Runtime API `/provider-status`.
- The owned Agent knowledge pack contains `Hermes provider inventory for Jiejing Agents` and `eBay provider inventory for Jiejing Agents`.
- FAL credentials are detected, but media calls do not run automatically just because a key exists.
- eBay credentials and policy snapshots are detected as backend-only status. Real writes remain blocked until ExecutionService and confirmation center are production-ready.

## Verification

- `python tools/ingest_jiejing_knowledge.py`
- `python tools/test_jiejing_live_tool_contracts.py`
- `python tools/test_jiejing_runtime_knowledge.py`
- `python tools/test_jiejing_runtime_mvp.py`
- `python tools/jiejing_runtime_self_check.py`

All listed checks passed after this sync.
