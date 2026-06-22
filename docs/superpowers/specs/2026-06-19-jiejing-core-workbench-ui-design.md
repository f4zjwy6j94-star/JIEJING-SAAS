# Jiejing Core Workbench UI Upgrade Design

Date: 2026-06-19

## Goal

Upgrade the logged-in Jiejing SaaS workbench from a feature stack into an operator-grade AI CEO cockpit. The first screen should help a merchant understand current store readiness, the next action, publish risk, and confirmation workload without reading every lower panel.

## Product Boundary

Jiejing remains an eBay-first AI CEO SaaS. The UI must not imply public paid launch readiness while Stripe remains test/mock, eBay token refresh success proof is zero, and the old eBay account cannot be reused. The interface may summarize sanitized backend evidence, but secrets, OAuth tokens, model keys, and refresh tokens remain behind the backend/Vault boundary.

## Information Architecture

1. Keep the existing left navigation and workflow modules.
2. Add a new first-screen cockpit inside the logged-in workbench.
3. Keep existing truth, eBay snapshot, setup, evidence, operating path, data coverage, AI output, publish preflight, and confirmation panels after the cockpit.
4. Show owner/security/platform details only in Settings/control-room panels, not as merchant-facing selling points.

## Cockpit Contents

- AI CEO header: current next action, current environment truth, and safe quick actions.
- Operating pulse: eBay packet, account health, pending confirmations, AI reports, billing/launch status.
- Workstream lanes: connect data, generate reports, prepare listing, preflight publish, merchant confirmation, post-publish audit.
- Risk queue: publish red/yellow/green status, high-risk confirmations, account-health incident mode, billing/provider launch gate.
- Evidence rail: latest sanitized packet id, report count, confirmation count, backend proof flags.

## Interaction Rules

- Refresh only reloads current backend state.
- Generate report can call the existing workflow action only when the existing button allows it.
- Publish preflight actions create/read confirmation evidence only; they must not write to eBay.
- Opening confirmation center is the only path toward high-risk decisions.
- No OAuth, payment, refund, ad spend, inventory change, price change, or real publish is triggered by the cockpit itself.

## Visual Direction

Use the existing Jiejing design system: white and near-white surfaces, restrained teal, amber for caution, red only for blockers, 8px radius, dense but calm operations UI. Avoid marketing-style hero composition inside the app.

## Verification

Run static UI contract tests, JS syntax checks, secret scan, staging bundle, online health/readiness, and browser smoke. Browser smoke must verify page identity, nonblank content, console health, and one cockpit interaction such as opening the confirmation center.
