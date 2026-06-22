# Jiejing publish preflight resolution design

## Goal

Make the publish health report behave like an operating control surface, not just a red/yellow/green display. After a publish confirmation packet returns backend `publish_readiness`, each preflight check must show:

- evidence trust from backend `source_records`
- the repair entry from backend `fix_action`
- the decision-center route from backend `confirmation_gate`
- an explicit no-direct-write boundary

## Product Boundary

This UI does not trigger eBay OAuth, payment, price changes, inventory changes, refunds, ads, policy edits, or a real eBay write. It only renders sanitized backend evidence and routes the merchant back to existing safe actions:

- `focus-publish-intake`
- `open-connect`
- `open-confirm`

Any real publish remains blocked until the decision center confirms the action.

## UI Shape

The backend preflight panel now has a resolution board above the detailed cards:

- red repair queue
- amber review queue
- green confirmation queue

Each backend check card gets a three-part resolution row:

- `证据可信度`: source record count and whether secret-like fields are withheld
- `修复入口`: the exact UI target for fixing the issue
- `确认中心路由`: the decision-center gate and direct-write status

The visual treatment follows the Jiejing design system: white surfaces, restrained teal, amber for review, red for blockers, 8px radius, and dense evidence-led copy.

## Verification

Static guard: `tools/test_jiejing_publish_preflight_resolution_ui.py`.

The guard checks that the frontend keeps the evidence trust, fix routing, confirmation route, and no-direct-write markers, and that backend evidence still exposes only sanitized source and fix metadata.
