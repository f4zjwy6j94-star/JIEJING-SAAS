# JIEJING Agent Instructions

These instructions apply to the whole repository. They exist so local Codex, Codex Cloud, and GitHub-driven agents keep the same JIEJING safety and product boundaries.

## Product Boundary

- JIEJING is an eBay-first AI CEO SaaS for cross-border commerce operations.
- Do not reframe it as a generic ERP, generic agent marketplace, or ordinary chatbot.
- The AI CEO can chat normally, but eBay operating tasks must enter workflows with evidence, audit trails, and confirmation gates.
- Keep complex operational status, launch gates, WAF/security diagnostics, billing cutover, and owner-only readiness panels in settings or internal owner surfaces. Core merchant workflows should stay simple.

## Current-State Rules

- Before reporting current launch or deployment status, verify current evidence instead of relying on old notes.
- Prefer these public staging probes when live status matters:
  - `https://app.jiejing.shop/health`
  - `https://app.jiejing.shop/health/deep`
  - `https://app.jiejing.shop/readiness/product-saas`
- If an edge/WAF blocks script-like probes, retry with a normal browser User-Agent before declaring the app down.
- Never claim formal paid public launch readiness unless readiness evidence says `production_ready=true` and `can_accept_real_customers=true`.

## Local-First And Cloud Fallback

- Local Windows Codex is the primary operating mode.
- Codex Cloud is a fallback route for times when the local computer cannot be used.
- Use `Jiejing Cloud Fallback Self Check` before trusting a phone-only cloud session for JIEJING work.
- Do not treat Codex Cloud as having local-only files, browser login state, or local secrets.
- Cloud fallback may edit GitHub code and run safe checks, but real deploy apply, eBay OAuth, Stripe live cutover, and secret-bearing operations still require explicit operator approval.

## Hard Safety Rules

- Do not run or repeat eBay OAuth unless the user explicitly says to start with a new eBay account.
- Do not trigger real eBay publish, revise, inventory, refund, procurement/payment, ads, policy edits, or sensitive customer promises without the confirmation center / decision center boundary.
- The old eBay account is frozen. Do not use it for real validation.
- Do not run Stripe live payment cutover, real charges, refunds, or live webhook writes unless explicitly approved for that step.
- Do not read, print, commit, or write secrets: model keys, BYOK keys, API keys, client secrets, Stripe secrets, eBay refresh/access tokens, OAuth codes, SSH private keys, cookies, or GitHub tokens.
- Never use `git credential fill` or any equivalent command that could print credentials.
- Keep BYOK, eBay tokens, and provider secrets inside backend Vault/env boundaries.

## Data And Deployment Safety

- Do not delete databases, Docker volumes, Vault material, `.env` files, backups, or production/staging runtime state.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` unless the user explicitly asks and the target scope is clear.
- For staging deployment automation, use the manual GitHub Actions path only:
  - Run `Jiejing Staging Runner Doctor` after installing the self-hosted runner.
  - Run `Jiejing Staging Manual Deploy` in `dry_run` first.
  - Only run `apply` after dry-run succeeds and the user approves the deploy step.
  - Use `Jiejing Staging Manual Rollback` dry-run before rollback apply.
- Do not use `docker compose down -v`, `docker volume rm`, broad `rm -rf`, or database drop/truncate commands in deployment paths.

## Verification Commands

Run focused checks for the files changed. For cloud/deployment/readiness work, run at minimum:

```bash
python tools/jiejing_secret_scan.py
node --check app.js
python tools/jiejing_precloud_deployment_gate.py
```

For GitHub runner/deployment automation changes, also run:

```bash
python tools/test_jiejing_github_actions_deploy_guardrails.py
python tools/test_jiejing_github_runner_doctor_guardrails.py
python tools/test_jiejing_staging_patch_apply_contract.py
python tools/test_jiejing_local_first_cloud_fallback_guardrails.py
```

For UI changes, run the relevant contract tests and browser smoke checks. Use the JIEJING design system and keep merchant-facing pages simple.

## Professional Prompt Auto-Trigger

- Use `docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md` as the internal professional-prompt library for JIEJING work.
- Trigger the relevant prompts autonomously; do not wait for the operator to name them every time.
- For product or prioritization work, apply Product Owner Review and Reality Checker.
- For AI CEO behavior, apply AI CEO Routing Review, Beginner UX Walkthrough, and Reality Checker.
- For workflow UI, onboarding, homepage, settings, or pricing UI, apply Beginner UX Walkthrough, UI Design Polish, and the JIEJING design system.
- For Listing and bulk-listing work, apply Listing Expert Review, Beginner UX Walkthrough, Security Threat Model, and Reality Checker.
- For billing, subscription, quota, Stripe, or payment-provider work, apply Billing And Pricing Review, Security Threat Model, and Reliability And Launch Readiness Review.
- For account isolation, chat history, reports, stores, orders, or tenant data, apply Tenant Isolation Audit and Security Threat Model.
- For customer messages, returns, refunds, disputes, policy language, or order handling, apply Customer Support And Order Reply Review and require confirmation-center review when risk is present.
- For deployment, readiness, domain, WAF, queue, worker, database, backups, monitoring, or launch claims, apply Reliability And Launch Readiness Review and Reality Checker.
- These prompts are advisory review tools only. They do not grant permission to bypass confirmation gates, secret boundaries, tenant isolation, live-payment controls, or readiness evidence.

## Git And Handoff

- Keep commits scoped and explain whether a change is code-only, staging-only, or production-adjacent.
- If pushing to GitHub, do not include local `output/`, env files, databases, logs, build caches, private keys, screenshots, or third-party cloned references.
- Keep `ready_for_paid_commercial_launch=false` unless the external payment, new eBay account, managed infra, Vault/KMS, monitoring, backups, and live proof gates are actually complete.
