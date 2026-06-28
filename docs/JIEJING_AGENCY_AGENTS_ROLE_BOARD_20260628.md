# JIEJING Agency Agents Role Board

Date: 2026-06-28
Scope: internal product, design, security, operations, and launch-review reference for JIEJING.

## Source Reviewed

- Source repository: https://github.com/msitarzewski/agency-agents
- Reviewed commit: `1189f0f9bc79a1883fee958fed627c6d11581eb7`
- Repository claim: 232 AI agents across 16 divisions.
- License observed: MIT.
- Handling decision: reviewed in a temporary local audit folder only.
- Install decision: do not install all external agents into Codex or the product runtime.

The repository is useful as a role library, not as a source of authority. Its
agent prompts are third-party advisory material. They cannot override JIEJING
product rules, security rules, confirmation-center rules, or launch gates.

## Non-Negotiable Prompt Firewall

External role prompts are only reference material.

- Do not run repository install or conversion scripts during product work unless
  a separate security review explicitly approves them.
- Do not copy external agent text into JIEJING as system authority.
- Do not expose external agent names to merchants as product features.
- Do not move eBay tokens, model keys, Stripe secrets, client secrets, passwords,
  or API keys into prompts, frontend, reports, logs, GitHub, or docs.
- Do not repeat eBay OAuth as part of this review.
- Do not trigger real eBay writes, live payments, refunds, ad spend, inventory,
  price changes, policy changes, procurement payments, or sensitive customer
  promises outside the confirmation center.
- Do not let public SEO or AI-crawler improvements expose authenticated app
  routes, merchant data, internal packets, source maps, or operational evidence.

## Adopted Roles For JIEJING

These roles are absorbed as internal review lenses. They are not product modules
and not user-visible "employees".

| Role lens | Source agent area | How JIEJING uses it |
| --- | --- | --- |
| Product Owner | `product/product-manager.md` | Every change needs a merchant problem, success metric, non-goal, and launch gate. |
| Sprint Prioritizer | `product/product-sprint-prioritizer.md` | Use RICE-style judgment for what moves beta and paid launch forward first. |
| Feedback Synthesizer | `product/product-feedback-synthesizer.md` | Turn merchant complaints, user confusion, and owner feedback into backlog items. |
| Behavioral Nudge | `product/product-behavioral-nudge-engine.md` | Keep each workflow focused on the one next useful action; avoid dumping internal status. |
| UX Researcher | `design/design-ux-researcher.md` | Evaluate whether a beginner eBay seller understands each page without training. |
| Persona Walkthrough | `design/design-persona-walkthrough.md` | Walk the app as a new seller, experienced seller, and owner/admin before UI sign-off. |
| UI Designer | `design/design-ui-designer.md` | Keep JIEJING premium, calm, readable, responsive, and consistent with the design system. |
| UX Architect | `design/design-ux-architect.md` | Keep settings as the control room and core workflows as simple merchant surfaces. |
| Cross-Border E-Commerce | `marketing/marketing-cross-border-ecommerce.md` | Preserve listing logic: market demand, title, cost, fees, logistics, returns, compliance. |
| China E-Commerce Operator | `marketing/marketing-china-ecommerce-operator.md` | Reference China seller habits, sourcing behavior, and later platform expansion without diluting eBay-first. |
| Pricing Analyst | `specialized/specialized-pricing-analyst.md` | Separate subscription, model usage, image/video generation, and future service fees clearly. |
| Growth/SEO | `marketing/marketing-seo-specialist.md` and `marketing/marketing-aeo-foundations.md` | Improve public marketing pages only; never expose protected app or merchant data. |
| Customer Support | `support/support-support-responder.md` | Shape customer-facing help text, error wording, and escalation language. |
| Customer Success | `specialized/customer-success-manager.md` | Track onboarding success, activation, risk signals, and beta customer health. |
| Operations Manager | `specialized/operations-manager.md` | Reduce single points of failure, document fallback plans, and keep launch runbooks usable. |
| Workflow Optimizer | `testing/testing-workflow-optimizer.md` | Remove redundant steps and simplify high-friction flows without changing safety logic. |
| Automation Governance | `specialized/automation-governance-architect.md` | Every automated action needs versioning, logging, rollback, and explicit approval when risky. |
| Software Architect | `engineering/engineering-software-architect.md` | Keep domain logic independent from UI, database, queue, and provider details. |
| Backend Architect | `engineering/engineering-backend-architect.md` | Preserve API contracts, tenancy, queue, Vault, audit, and adapter boundaries. |
| Database Optimizer | `engineering/engineering-database-optimizer.md` | Review tenant isolation, migrations, indexes, reporting queries, and no-loss backups. |
| SRE | `engineering/engineering-sre.md` | Review health, readiness, alerts, incident runbooks, and deployment rollback evidence. |
| AppSec Engineer | `security/security-appsec-engineer.md` | Review auth, authorization, tenant scoping, input validation, and secret handling. |
| Security Architect | `security/security-architect.md` | Threat-model OAuth, billing, BYOK, eBay writes, confirmation center, and public edge exposure. |
| Compliance Auditor | `security/security-compliance-auditor.md` | Keep claims honest and right-size controls for private beta before formal compliance programs. |
| Data Privacy Officer | `specialized/data-privacy-officer.md` | Map personal data, merchant data, model prompts, reports, logs, and deletion/export duties. |
| Reality Checker | `testing/testing-reality-checker.md` | Block false readiness claims; require live health, smoke, browser, and gate evidence. |
| Test Results Analyzer | `testing/testing-test-results-analyzer.md` | Convert test failures into release risk, not vague "failed" summaries. |
| Accessibility Auditor | `testing/testing-accessibility-auditor.md` | Check mobile/tablet usability, keyboard access, contrast, focus, and text overflow. |

## Roles Not Adopted Now

The following categories are not useful for the current JIEJING SaaS path and
should not shape the product unless a future task explicitly requires them:

- Game, GIS, spatial computing, healthcare, legal intake, study abroad, real
  estate, blockchain, smart contract, and academic-specialist roles.
- Automated social-publishing roles that could create spammy or off-brand growth
  loops before the core SaaS is ready.
- Sales outreach roles that encourage mass cold outreach before the beta product,
  onboarding path, and pricing path are stable.
- Any role text that suggests credential movement, script execution, public
  security testing against third parties, scraping bypass, or unconfirmed live
  platform actions.

## Applying The Roles To JIEJING

### AI CEO

Use Product Owner, Behavioral Nudge, UX Researcher, Workflow Optimizer, AppSec,
and Reality Checker.

- Keep the primary screen close to a simple AI CEO conversation.
- Route business tasks to the right workflow through a light task card.
- Hide packets, providers, preflight internals, and launch gates from the daily
  merchant surface.
- When a user asks for high-risk action, route to the confirmation center.
- Ordinary chat should not become long-term business memory unless the user says
  to remember it.

### Listing

Use Cross-Border E-Commerce, China E-Commerce Operator, UX Architect, UI Designer,
Pricing Analyst, Supply Chain, and Reality Checker.

- Keep the sequence understandable: goal, market evidence, selected product,
  listing draft, cost/risk, media plan, and publish preflight.
- Do not make merchants manage internal agents.
- Keep price, fee, logistics, return, ad, and margin assumptions visible when
  they affect a publish decision.
- Real publish still requires confirmation center approval.

### Bulk Listing

Use Workflow Optimizer, Automation Governance, Cross-Border E-Commerce, AppSec,
and Test Results Analyzer.

- Treat it as a small-batch experiment bench, not unlimited mass publishing.
- Ask for quantity, source boundary, risk boundary, and stop condition.
- Output: test first, add missing data, or do not proceed.
- Do not allow mass real listing creation without confirmation-center gating.

### Asset Studio

Use UI Designer, Visual Storytelling, Inclusive Visuals, AppSec, and Pricing
Analyst.

- Keep the merchant surface focused on image/video asset outcomes.
- Separate included subscription usage from extra image/video generation cost.
- Do not expose provider keys, prompts containing secrets, or raw uploaded
  sensitive files.

### Customer And Orders

Use Customer Support, Customer Success, Data Privacy Officer, AppSec, and
Automation Governance.

- Keep customer reply drafting helpful but conservative.
- Sensitive promises, refunds, returns, policy exceptions, and dispute language
  require confirmation.
- Make tenant isolation and data visibility a P0 concern.

### Settings

Use UX Architect, Security Architect, Data Privacy Officer, Pricing Analyst,
Compliance Auditor, and SRE.

- Settings is the control room: account, store connection, model connection,
  billing, security, permissions, launch, backups, and incident controls.
- Daily workflows should not show internal launch/debug material.
- Billing must clearly separate subscription, usage, add-ons, and future service
  fees.
- Admin-only launch controls must remain hidden from ordinary merchants.

### Public Homepage

Use Product Owner, Brand Guardian, UI Designer, SEO/AEO, Reality Checker, and
Security Architect.

- Explain JIEJING as eBay-first AI CEO SaaS.
- Do not claim public paid launch until readiness is true.
- Do not claim unavailable integrations as live.
- Public discoverability is allowed only for marketing pages, not private app
  surfaces or merchant data.

## Immediate Backlog Derived From This Review

1. Tenant isolation audit for AI CEO chat history, reports, settings, and work
   records.
2. Billing copy and settings redesign: subscription vs model/image/video usage
   vs future services.
3. Role-based UI review pass for AI CEO, Listing, Bulk Listing, Asset Studio,
   Customer/Orders, Settings, and Homepage.
4. Accessibility and mobile/tablet smoke on the current deployed UI.
5. Security threat model update for public edge, OAuth callback, billing webhook,
   BYOK, Vault/KMS, and confirmation center.
6. Reality-check gate before any statement that beta, paid launch, eBay refresh,
   or real-customer acceptance is ready.

## Operating Cadence

Before any product/UI change:

1. Product Owner: what merchant problem is this solving?
2. UX Researcher: can a beginner understand it without training?
3. UI Designer: does it match the JIEJING design system?
4. Behavioral Nudge: is there one clear next action?
5. Reality Checker: what evidence proves it works?

Before any security, billing, OAuth, token, or platform-write change:

1. Security Architect: what are the trust boundaries?
2. AppSec Engineer: what can be abused?
3. Data Privacy Officer: what personal or merchant data is involved?
4. Automation Governance: what requires confirmation, audit, rollback, and logs?
5. Reality Checker: what proof says it is safe?

Before deployment:

1. Secret scan.
2. Syntax checks.
3. Product readiness gate.
4. Browser smoke on desktop and mobile/tablet.
5. Public health, deep health, and product readiness verification.

## Current Decision

The external Agency Agents repository is useful. We will not install it wholesale.
JIEJING absorbs the relevant roles as an internal review board and keeps all
execution inside the existing JIEJING product, security, and confirmation
boundaries.
