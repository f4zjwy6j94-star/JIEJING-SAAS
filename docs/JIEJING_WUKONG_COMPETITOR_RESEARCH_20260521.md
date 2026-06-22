# Jiejing Wukong Competitor Research - 2026-05-21

## Scope

This note records what Jiejing should learn from DingTalk / Alibaba Wukong without changing Jiejing's fixed direction.

Sources checked:

- Official Wukong homepage: https://wukong.dingtalk.com/
- Official Wukong manual: https://wukong.dingtalk.com/docs/
- Official Wukong introduction: https://wukong.dingtalk.com/docs/about/
- Official Wukong FAQ: https://wukong.dingtalk.com/docs/faq/
- Third-party summaries were used only to cross-check public positioning.

## Product Signals

Wukong positions itself as an enterprise AI work platform where the user says what they need and the system executes work through tools and skills.

Observed capability themes:

1. Action-first AI
   - Wukong explicitly moves from "AI that answers" to "AI that delivers".
   - It can operate the computer, local files, browser, and DingTalk work apps.

2. One Person Team
   - Wukong's core packaging is "one person + AI = a team".
   - It exposes industry scenarios such as one-person store, one-person e-commerce, one-person designer, one-person developer, finance, legal, manufacturing, and headhunting.

3. Skill Center
   - Wukong uses Skills as reusable business abilities.
   - Public docs mention e-commerce skills including hot-search keyword collection, store weekly report, 1688 product discovery, Amazon product discovery, 1688 same-product search, listing optimization, material generation, supplier communication, international listing, international store analysis, opportunity analysis, and 1688 sourcing/procurement.

4. Long-Term Memory
   - Wukong advertises memory of user context, preferences, and working habits.
   - This is a product-level dependency loop: the more work it does, the more difficult it becomes to switch.

5. Enterprise Integration
   - Wukong is deeply integrated into DingTalk.
   - It can be triggered from IM and sync task progress/results across devices.

6. Local Control And Security
   - FAQ describes a local desktop entry for deep control of files and applications.
   - It also frames local processing as better for privacy and performance.
   - Other public sources emphasize enterprise permission inheritance, sandboxing, audit, and token/cost visibility.

## What Jiejing Should Learn

The key product idea is not "make a bigger agent platform." The key idea is:

> Package complex specialist roles into a simple one-person operating team.

Jiejing should translate this into:

> One merchant + Jiejing AI CEO = one eBay operating team.

The merchant should not see raw technical agent orchestration. The merchant should see:

- AI CEO.
- Operating template.
- Skill packs.
- Work records.
- Source records.
- Confirmation center.
- Merchant Memory.
- Model and cost boundary.

## What Jiejing Must Not Copy

Jiejing should not become:

- A generic DingTalk replacement.
- A generic desktop-control product.
- A generic multi-scenario agent marketplace.
- A generic "one person can do every industry" tool.
- A tool that bypasses eBay official APIs with brittle browser automation.
- A tool that hides cost, data source, permission, or confirmation boundaries.

Jiejing's public scope remains:

- eBay-first cross-border seller AI CEO SaaS.
- Official read-only eBay data packet.
- BYOK model key stored as `secret_ref`.
- Reports, source records, work records, confirmation center.
- Real platform writes disabled until separately audited.

## Jiejing Adaptation: One-Person eBay Team

Wukong's "One Person Team" becomes Jiejing's "One-Person eBay Operating Team".

Default roles:

1. AI CEO
   - Receives merchant goal.
   - Selects the correct eBay operating template.
   - Keeps high-risk work behind confirmation.

2. Market Skill
   - Reads official packet and source records.
   - Produces Market Report.
   - Marks public web data separately from official eBay data.

3. Listing Skill
   - Produces Listing Package.
   - Validates category, item specifics, policy references, and missing facts.

4. Source / Profit Skill
   - Organizes supplier, cost, packaging, logistics, fees, and profit floor.
   - Stops before procurement, payment, address write, or final margin claims.

5. Asset Skill
   - Produces asset brief and generated-file manifest.
   - Stops before claiming unverified material, certification, effect, or media rights.

6. Service Skill
   - Produces product FAQ and buyer-message draft boundaries.
   - Stops before refund, compensation, dispute, arrival date, or exception promise.

7. Confirmation Skill
   - Converts risky actions into confirmation-center items.
   - Does not execute the platform write itself.

## Skill Pack Product Layer

Wukong's Skill Center should become Jiejing's merchant-specific Skill Packs.

V0 skill packs should be narrow and commerce-specific:

- `eBay Title Optimizer`
  - Inputs: official category, title draft, keyword source records.
  - Output: title candidates, forbidden terms, source notes.

- `Supplier Verification Checklist`
  - Inputs: supplier link, quote, product image, packaging facts.
  - Output: missing questions and risk notes.

- `Item Specifics Gap Scanner`
  - Inputs: eBay taxonomy / item specifics packet.
  - Output: missing fields and publish blockers.

- `Profit Floor Checker`
  - Inputs: price, cost, shipping, platform fees, return reserve.
  - Output: safe price range and stop condition.

- `Customer Promise Guard`
  - Inputs: listing package, policy, logistics facts.
  - Output: allowed reply scope and escalation triggers.

- `Vero / Brand / IP First Screen`
  - Inputs: title, description, image filenames, known risk lexicon.
  - Output: risk hits and confirmation suggestions.

Every skill pack must define:

```text
skill_id
tenant_id
store_id
role_id
platform_scope
category_scope
inputs
outputs
source_requirements
forbidden_claims
confirmation_triggers
quality_checks
memory_write_policy
audit_policy
```

## Memory Product Layer

Wukong's long-term memory validates Jiejing's Merchant Memory direction.

Jiejing memory should be scoped and explainable:

- account memory
- store memory
- project memory
- category memory
- supplier memory
- customer-service memory
- confirmation-rule memory

Do not store:

- eBay raw token
- model raw key
- refresh token
- cloud credentials
- raw payment credentials
- buyer-sensitive data beyond a minimized task need

Memory should store:

- merchant preferences
- allowed words and forbidden claims
- category-specific listing rules
- supplier questions
- profit floor
- confirmation defaults
- accepted and rejected AI suggestions
- report-quality feedback

## Cost And Usage Layer

Wukong's token/cost visibility is important.

Jiejing should show a merchant-facing cost ledger:

- BYOK provider.
- model used.
- report run count.
- token estimate or provider-reported usage when available.
- failed run count.
- last successful value proof.
- whether costs are paid to Jiejing or merchant's own provider.

For MVP, show only safe metadata and estimates. Do not infer exact provider charges unless provider usage data is available.

## Execution Boundary

Wukong can operate local computers and apps. Jiejing should not make that the core SaaS path.

Jiejing's order of preference:

1. Official eBay APIs.
2. Merchant-provided files, images, links, tables, or exports.
3. Public web/source record collector.
4. Controlled browser research agent.
5. Human-assisted manual step.

Browser or desktop automation must be:

- optional
- explicitly authorized
- source-record only by default
- revocable
- audited
- blocked from publish, payment, refund, ad, procurement, policy, and sensitive buyer promises

## Roadmap Impact

### Do Now

Do not derail the current model_value_proof blocker.

Keep the immediate MVP path:

```text
merchant login
-> official eBay read-only packet
-> save BYOK model key
-> live Market Report + Listing Package
-> confirmation center
-> Merchant Memory
```

### V0.1

Expose the already-added operating-template idea more clearly:

- "One-Person eBay Operating Team"
- show the seven default roles
- show what each role can read and cannot do
- show which skills are active
- show confirmation triggers

### V0.2

Add merchant Skill Packs:

- title optimizer
- supplier checklist
- item specifics scanner
- profit floor checker
- customer promise guard
- IP / brand first screen

These must be templates backed by Jiejing role contracts, not free-form arbitrary agents.

### V0.3

Add memory-driven dependency:

- after each report, ask merchant if output is useful
- write accepted preferences into Merchant Memory
- let future reports explain which memories were applied

### V0.4

Add cost and run ledger:

- model usage
- report count
- failed/successful runs
- value proof status
- merchant BYOK boundary

### V0.5

Add optional source collector:

- collect public competitor/supplier/source pages
- attach screenshots and source records
- no autonomous platform writes

## Strategic Takeaway

Accio Work teaches "agent workspace and tool permission".

Wukong teaches "one-person team packaging, skill packs, long-term memory, and enterprise-grade execution confidence".

Jiejing should combine both into a narrower and stronger commerce product:

> A one-person eBay operating team where AI CEO coordinates specialist skill packs, every conclusion has source records, every risky action enters confirmation center, and every useful decision becomes merchant memory.

