# Jiejing Runtime Backroad Progress 2026-05-15

This document records the current state of the Jiejing-owned Agent Runtime after synchronizing safe provider knowledge from the local Hermes environment.

## What Improved

- `jiejing-llm` now prefers DeepSeek when a backend Hermes/Runtime credential is available. If no model key is configured, it falls back to deterministic local output instead of blocking the SaaS demo.
- Runtime provider status now exposes DeepSeek, Tavily, FAL, and eBay readiness through backend-only status endpoints without exposing secrets.
- Runtime now exposes `/progress-scorecard`, which calculates five project tracks from live repository evidence instead of relying on hand-written percentages.
- Runtime now has `JiejingToolOrchestrator`, a single tool execution layer for role tools. It records timeout, retry, status, no-secret, and no-real-write boundaries for market, sourcing, listing, asset, and finance tools.
- Tool outputs now drive Agent report sections instead of only sitting in appendices: sourcing updates supplier/cost/package sections, eBay metadata updates category/policy/publish blockers, media manifests update asset sections, and logistics estimates update finance/logistics sections.
- eBay read-only adapters can discover backend credentials and sanitized business-policy snapshots from the Hermes environment, but they never return tokens to reports or frontend payloads.
- eBay token discovery now prefers the Hermes root credential file over older role-profile token copies. Expired profile tokens no longer hide a fresh root token.
- Product listing metadata can still use the latest sanitized business-policy snapshot for fulfillment, payment, and return policies when live Account API reads are unavailable.
- SaaS mock frontend now fetches `/provider-status`, `/agent-job-specs`, and `/progress-scorecard`; its Runtime-triggered workflow sends `tool_mode: safe_live_read`.
- Owned Agent execution records now mark external tool boundary usage when market data, listing metadata, or media generation probes are attached.
- Owned Agent execution records now also mark sourcing availability and logistics estimate tool usage.

## Current Smoke-Test Result

- DeepSeek configured: yes.
- Tavily configured: yes.
- FAL configured: yes.
- eBay short-lived access token: ready after running the Hermes business-policy adapter with direct network mode.
- Runtime now reports `access_token_status: ready` and `refresh_required: false` when the Hermes root token is fresh.
- OAuth refresh readiness is reported separately. Runtime can detect the refresh token and app keyset in backend-only Hermes files without exposing them.
- Runtime now has an optional backend-only auto-refresh bridge: set `JIEJING_EBAY_AUTO_REFRESH=1` to let Runtime call the Hermes read-only business-policy adapter when a token is expired.
- eBay business-policy snapshot: readable.
- Public search probe: ready.
- eBay Browse read-only probe: ready in the latest SaaS-to-Runtime smoke test.
- Listing metadata policy packet: ready from sanitized snapshot.
- Real eBay publish/write: still blocked and confirmation-gated.

Latest smoke-test detail:

- eBay provider source: `wsl_hermes_root_credential_file`.
- eBay Browse summary: `Stainless Steel Travel Tumbler` returned 10 item summaries with sample price band `USD 11.99-89.89`.
- Full-stack smoke script: `python tools\jiejing_full_stack_smoke.py`.
- Latest full-stack smoke report:
  - `output/jiejing-agent-runtime-samples/full-stack-smoke/jiejing_full_stack_smoke_latest.md`
  - `output/jiejing-agent-runtime-samples/full-stack-smoke/jiejing_full_stack_smoke_latest.json`
- Latest local progress scorecard:
  - SaaS demo frontend loop: `96%`
  - Jiejing Runtime foundation: `98%`
  - Owned 7-Agent role system: `94%`
  - Owned Agent low-risk takeover capability: `80%`
  - Owned Agent production-level Hermes replacement ceiling: about `35%`
  - SaaS mock Runtime integration: `96%`
  - Local demo average: `93%`
  - Production-ready claim: `false`
- The latest full-stack smoke run includes five tool-boundary handoffs: market data packet, sourcing availability, eBay listing metadata, media generation manifest, and logistics estimate.
- The latest SaaS snapshot shows 19 tool-driven report sections across market, sourcing, listing, asset, and finance tasks.
- Important wording correction: `80%` does not mean Jiejing can fully replace Hermes in production. It means the owned Runtime can locally take over low-risk structured tasks with evidence and tool boundaries. Hermes remains the main execution substrate until search, eBay read-only, sourcing, logistics, media generation, memory, retry, queue, and production backend are stable.

## Hermes Replacement Readiness Correction

Added a strict production replacement evaluator:

- API: `GET /replacement-readiness`
- Module: `jiejing_runtime/replacement_readiness.py`
- Regression: `python tools\test_jiejing_replacement_readiness.py`
- Full-stack smoke now includes a required same-topic comparison gate using `RuntimeComparisonScorer`. It is marked `sample_only: true`, so it does not count as production replacement evidence yet.

Current honest state:

- Local low-risk Agent takeover: about `82%`
- Production-level Hermes replacement readiness: about `37%`
- Can replace Hermes in production: `false`
- Same-topic comparison smoke gate: `pass`, sample-only, not counted for production replacement.

Main blockers:

- Real 1688/source reads and Orange Connex/SpeedPAK quotes are not stable production adapters yet.
- Real image/video generation still needs queueing, cost control, retry, and commercial QA.
- Jiejing Agents have not yet passed repeated same-topic Hermes comparison gates.
- Formal SaaS backend, tenant permissions, Vault, cloud queue, audit, and operations are not production-ready.
- Real eBay writes still require confirmation center and ExecutionService.
- Listing fact update now reaches `ready_for_confirmation_review` in the smoke test after demo policy IDs and package facts are supplied. It still does not publish to eBay.
- Remaining workflow block: source availability and logistics facts are still pending, so the workflow correctly stops before publish.
- Secret exposure check: false.

## What This Means

The backroad Runtime is now a real owned execution boundary, not only a static demo:

1. SaaS can create a standard product workflow.
2. Runtime can split it into 11 controlled tasks.
3. Owned Agent job specs are loaded.
4. Read-only tools can attach evidence where available.
5. Missing connectors are labeled as pending instead of pretending success.
6. Listing policy data can be read from a sanitized snapshot.
7. High-risk execution remains blocked.

## Remaining Gaps

- The Hermes policy adapter default proxy was stale in this environment. Running with direct network mode succeeded; production must make proxy/network selection explicit instead of hardcoding one WSL gateway address.
- 1688/source connector is still not a real live adapter.
- Orange Connex/SpeedPAK pricing is still not a real live quote adapter.
- FAL media provider is configured, but media generation remains opt-in and is not auto-triggered by safe read mode.
- Frontend modules still need deeper conversion from static demo data to Runtime result data.
- The Runtime still has far less tool ecosystem, memory, and worker orchestration than Hermes.

## Verification Commands

```powershell
python tools\test_jiejing_live_tool_contracts.py
$env:JIEJING_MODEL_PROVIDER='responses'; python tools\test_jiejing_runtime_workflow.py
python tools\test_jiejing_runtime_mvp.py
python tools\test_jiejing_owned_agent_team.py
python tools\test_jiejing_runtime_knowledge.py
python tools\jiejing_runtime_self_check.py
node --check app.js
python tools\jiejing_full_stack_smoke.py
python tools\test_jiejing_tool_orchestrator.py
```
