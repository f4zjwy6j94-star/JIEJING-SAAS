# JIEJING Agent Instructions

These instructions apply to the whole repository. They exist so local Codex, Codex Cloud, and GitHub-driven agents keep the same JIEJING safety and product boundaries.

## Continuity And Instruction Conflicts

- At a restart, handoff, or context compaction, read `docs/JIEJING_CURRENT_EXECUTION_STATE.md` before task actions. It is the single current execution index; dated handoffs are historical evidence, not automatic next-step instructions.
- Verify the actual repository, `git status --short --branch`, and relevant changes before continuing. Refresh online state only when needed for the claim or action. Do not rerun completed OAuth, payment/refund proof, research, or product imports just to recover context.
- Keep that index current at meaningful milestones: completed actions and their IDs, remaining work, failed approaches, test evidence, and whether work is uncommitted, committed, deployed, or exercised through the SaaS. Link evidence instead of copying whole logs. Do not store secrets or credentials.
- The user's latest explicit decisions take precedence over advisory skill content. Do not let design libraries, remembered summaries, or historical documents silently change product scope, pricing, navigation, or deployment authority.
- On a genuine conflict, inspect the smallest relevant source and explain the discrepancy; do not reset the project or invent a new plan. Updates to an existing authorised task do not require repeated generic approval, but high-risk external actions retain their action-time confirmation boundary.
- Code review, local test success, production health, paid availability, and real eBay execution are distinct evidence. Never turn one into a claim about all of them.
- Resolve material ambiguity before implementation: briefly restate the intended outcome, preserve agreed constraints, and ask focused questions with a recommendation when the answer changes scope or product direction. Investigate code-answerable questions independently; do not repeatedly reopen settled decisions.

## Approved UI And Product Constraints

- Public entry has three choices: 免费体验、有店铺、多店铺. No beginner sourcing service, fourth pricing plan, or unsupported platform claims. Use current billing definitions for amounts and entitlements.
- Merchants without supply receive research suggestions and find their own source; merchants with supply provide product information. 捷境 helps generate/edit Listing and media inside the SaaS, without inventing facts or sending normal listing work to manual eBay forms.
- Preserve the existing product structure and capabilities. The user retired the custom Jiejing visual skill on 2026-09-06: its palette and styling prescriptions are not mandatory. Verify the functional merchant journey before a broader visual upgrade, then agree on a visible design direction before production UI changes. UI changes must not silently change backend business logic or remove capabilities such as bulk-listing.
- AI CEO conversation is the primary workspace; product progress is secondary and compact. Check existing-project and empty states, desktop and tablet widths.
- Do not restore a standalone 工作记录/运行记录 navigation item. Retain the actual conversations, reports, Listing versions, media jobs, and support history in their corresponding business pages.
- Keep owner-facing project completion and engineering readiness commentary out of public pages and merchant Settings. Internal operations surfaces hold those details.

## Product Boundary

- JIEJING is an eBay-first AI CEO SaaS for cross-border commerce operations.
- Do not reframe it as a generic ERP, generic agent marketplace, or ordinary chatbot.
- The AI CEO can chat normally, but eBay operating tasks must enter workflows with evidence, audit trails, and confirmation gates.
- Keep owner-only launch gates, WAF/security diagnostics, billing cutover, and project-readiness panels in internal operations surfaces. Merchant Settings holds actionable account, plan, store, model, and permission controls. Core merchant workflows should stay simple.

## Current-State Rules

- Before reporting current launch or deployment status, verify current evidence instead of relying on old notes.
- Prefer these public staging probes when live status matters:
  - `https://app.jiejing.shop/health`
  - `https://app.jiejing.shop/health/deep`
  - `https://app.jiejing.shop/readiness/product-saas`
- If an edge/WAF blocks script-like probes, retry with a normal browser User-Agent before declaring the app down.
- Never claim paid public launch readiness without current `production_ready`, `can_accept_real_customers`, and `public_charging_allowed` evidence. Refund execution and eBay writing must be verified separately, not inferred from payment availability.

## Local-First And Cloud Fallback

- Local Windows Codex is the primary operating mode.
- Codex Cloud is a fallback route for times when the local computer cannot be used.
- Use `Jiejing Cloud Fallback Self Check` before trusting a phone-only cloud session for JIEJING work.
- Do not treat Codex Cloud as having local-only files, browser login state, or local secrets.
- Cloud fallback may edit GitHub code and run safe checks, but real deploy apply, eBay OAuth, Stripe live cutover, and secret-bearing operations still require explicit operator approval.

## Hard Safety Rules

- Do not run or repeat eBay OAuth unless the user explicitly says to start with a new eBay account.
- Do not trigger real eBay publish, revise, inventory, refund, procurement/payment, ads, policy edits, or sensitive customer promises without the confirmation center / decision center boundary.
- Historical eBay account restrictions are not current proof. Inspect the specific account's current status when relevant; do not repeat OAuth or use a restricted account for real validation.
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

For UI changes, run the relevant contract tests and browser smoke checks. Follow the user's selected visual direction, keep merchant-facing pages simple, and verify rendered layouts rather than treating a named skill as evidence of design quality.

## Proactive Principal Audit

- Do not wait for the operator to ask for an audit after meaningful product, UI, billing, security, deployment, or workflow changes.
- After each important change, review JIEJING from these owner lenses: SaaS product fit, beginner merchant UX, billing clarity, tenant isolation, security/trust, eBay operating correctness, reliability/readiness, and merchant-facing copy quality.
- Treat this audit as part of the work, not as an optional follow-up. If a finding is low-risk and directly fixable, fix it in the same pass; if it needs external accounts, live billing, new eBay credentials, or paid infrastructure, report it as a blocker without inventing readiness.
- Keep the audit conservative: no eBay OAuth, no live Stripe cutover, no real platform write, no secret read/print, and no destructive deploy action unless explicitly approved.

## Professional Prompt Auto-Trigger

- Use `docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md` as the internal professional-prompt library for JIEJING work.
- Trigger the relevant prompts autonomously; do not wait for the operator to name them every time.
- For product or prioritization work, apply Product Owner Review and Reality Checker.
- For AI CEO behavior, apply AI CEO Routing Review, Beginner UX Walkthrough, and Reality Checker.
- For workflow UI, onboarding, homepage, settings, or pricing UI, apply Beginner UX Walkthrough and UI Design Polish against the current user-approved brief; do not reinstate the retired custom visual skill.
- For Listing and bulk-listing work, apply Listing Expert Review, Beginner UX Walkthrough, Security Threat Model, and Reality Checker.
- For billing, subscription, quota, Stripe, or payment-provider work, apply Billing And Pricing Review, Security Threat Model, and Reliability And Launch Readiness Review.
- For account isolation, chat history, reports, stores, orders, or tenant data, apply Tenant Isolation Audit and Security Threat Model.
- For customer messages, returns, refunds, disputes, policy language, or order handling, apply Customer Support And Order Reply Review and require confirmation-center review when risk is present.
- For deployment, readiness, domain, WAF, queue, worker, database, backups, monitoring, or launch claims, apply Reliability And Launch Readiness Review and Reality Checker.
- These prompts are advisory review tools only. They do not grant permission to bypass confirmation gates, secret boundaries, tenant isolation, live-payment controls, or readiness evidence.

## Git And Handoff

- Keep commits scoped and explain whether a change is code-only, staging-only, or production-adjacent.
- If pushing to GitHub, do not include local `output/`, env files, databases, logs, build caches, private keys, screenshots, or third-party cloned references.
- Report launch flags as calculated from current evidence; do not hardcode a desired true or false value into the report. eBay account eligibility, public charging, and refund execution remain separate checks. Do not introduce paid KMS as a requirement: the approved Vault recovery arrangement is a separate evidence track.
