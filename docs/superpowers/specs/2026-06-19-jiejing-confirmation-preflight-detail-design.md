# Jiejing Confirmation Preflight Detail Design

## Goal

Upgrade the publish confirmation and backend preflight surface so a merchant can understand every blocker before a real eBay write is allowed.

This is a UI and evidence-mapping pass only. It must not start eBay OAuth, publish to eBay, create live Stripe charges, or expose backend secrets.

## Product Direction

Jiejing remains an eBay-first AI CEO SaaS. The AI CEO can prepare work, explain risk, and route tasks, but real publish, price, inventory, refund, ad, policy, and sensitive customer-service actions remain confirmation-gated.

## User Experience

The backend preflight panel should read like an operating checklist, not a raw API object:

- show whether a check is blocking, review-only, or passed
- show source trail without raw secrets
- show what part of the business is affected
- show the safe repair route
- show whether a human confirmation is still required
- provide buttons that route to the right UI area

The confirmation center should add a compact "publish command" summary above publish cards:

- backend readiness state
- red/yellow/green counts
- latest confirmation id
- source packet id
- eBay write gate status
- explicit no-direct-write wording

## Data Boundary

The frontend may display:

- confirmation id
- preflight status
- sanitized source record labels
- packet id
- check label, status, summary, and safe details
- fix action label and routing action

The frontend must not display:

- eBay access token
- refresh token
- API key
- client secret
- authorization header
- raw provider response with secrets

## Visual Direction

Use the existing Jiejing white operations style:

- 8px card radius
- teal for trusted evidence
- amber for review
- red for blocking
- dense but readable cards
- no decorative dark hero or marketing layout

## Acceptance Checks

- Static test confirms new detail helper functions and CSS selectors.
- Existing publish-health and confirmation-intake tests still pass.
- `node --check app.js` passes.
- Secret scan passes.
- Public staging health and readiness are rechecked after deploy.
