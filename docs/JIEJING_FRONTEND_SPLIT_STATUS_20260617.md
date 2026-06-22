# Jiejing Frontend Split Status - 2026-06-17

## Completed In This Pass

- Added `assets/jiejing-settings-panels.js`.
- Moved the clean settings-page implementations for:
  - production queue / deep operational health
  - formal billing provider / Stripe Checkout / Customer Portal status
- `app.html` now loads the settings module before `app.js`.
- `index.html` prefetches the settings module before app entry.
- `app.js` wrappers now delegate to `window.JiejingSettingsPanels` and keep the old inline implementation only as a fallback.
- Added `tools/test_jiejing_frontend_settings_module_split.py`.

## Why This Split First

The settings page is now where eBay, BYOK, packet, billing, queue, backup, permissions, launch gate and account health converge. Pulling these panels out first gives the biggest maintainability gain while keeping AI CEO, Listing, media and confirmation behavior stable for the next test run.

## Remaining Split Order

1. AI CEO: chat shell, routing badges, streaming/fallback states, memory policy hints.
2. Listing: market report, listing package, eBay synced items, IP/VeRO preflight.
3. Media workshop: asset manifest, image/video/script task cards, publishability status.
4. Confirmation center: high-risk action cards, execution result handback, cleanup actions.
5. Shared view helpers: status labels, source badges, timestamp labels, escape helpers.

## Guardrail

Do not move high-risk execution logic to frontend modules. Frontend modules can render state and call SaaS backend endpoints only. eBay tokens, model keys, billing secrets and provider API keys remain in backend secret boundaries.
