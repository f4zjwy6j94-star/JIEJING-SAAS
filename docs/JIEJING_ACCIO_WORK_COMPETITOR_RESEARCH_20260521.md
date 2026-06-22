# Jiejing Accio Work Competitor Research - 2026-05-21

## Scope

This note records what Jiejing should learn from Accio Work without drifting away from the current eBay-first AI CEO SaaS direction.

Sources checked:

- Douyin video: https://www.douyin.com/video/7627921777892911784
- Accio Work official page: https://www.accio.com/work
- Accio Work permissions page: https://www.accio.com/work/permissions

## What Accio Work Is Showing

Accio Work positions itself as a local-first desktop AI agent workspace for business execution, not only a chat UI.

Observed capability map:

1. Agent Center
   - Create and manage agents with custom roles, instructions, capabilities, and model choices.
   - Models shown include Gemini, GPT-4o, Claude, and Qwen.

2. Skills
   - Skills extend agents with domain abilities.
   - Users can use built-in skills, install from a library, or create their own skills.
   - The official page mentions MCP support for external tool servers.

3. Browser and Computer Operation
   - Agents can use a real browser to search, open pages, collect information, fill forms, take screenshots, and navigate multi-step workflows.
   - Browser access is treated as sensitive and requires explicit permission.

4. Connectors and Channels
   - Connectors are advertised for Gmail, Google Drive, Slack, Notion, and similar work apps.
   - Channels include Telegram, Discord, DingTalk, Feishu, and WeChat.

5. Automations
   - Users can schedule recurring tasks similar to cron.
   - Tasks can be described in natural language or configured in an automation page.

6. Teams
   - Multiple agents can work together.
   - The public FAQ describes a Team Lead that delegates subtasks and coordinates member agents through group chat.
   - The Douyin video chapter summary frames this as leader + members collaboration.

7. Permissions and Audit
   - Permissions are scoped to a workspace, agent profile, and session.
   - Tool calls are checked against a session manifest.
   - OAuth tokens are encrypted and revocable.
   - Tool calls and permission changes can be logged or exported depending on deployment tier.

## What Matters For Jiejing

Accio Work proves that users are starting to expect an AI product to do work, not only produce text.

For Jiejing, the useful lesson is not "make a generic agent platform." The useful lesson is:

> Turn the merchant's e-commerce workflow into configurable, auditable AI work teams.

Jiejing already has a stronger commerce-specific base than a generic agent workspace:

- eBay-first official data packet.
- BYOK model boundary through `secret_ref`.
- Merchant Memory.
- Role contracts for AI CEO, Market, Source/Finance, Listing, Asset, Service, and Confirmation.
- Confirmation center for high-risk actions.
- Real platform writes disabled until separately audited.

The missing product layer is merchant-visible workflow configuration:

- Which role modules are active for this merchant.
- Which role modules are required before a report can be trusted.
- Which low-risk tasks can run automatically.
- Which actions must always enter confirmation center.
- Which agent skills are reusable for the merchant's category, supplier style, fulfillment pattern, and customer-service policy.

## Jiejing Must Not Copy

Do not copy Accio Work into a generic desktop agent product.

Jiejing should not become:

- A generic local computer-control tool.
- A general browser automation app.
- A general "create any agent" playground.
- A chat/channel bot platform.
- A connector marketplace before the eBay value loop is proven.

The public product should still say:

- Jiejing / AI CEO.
- Work records.
- Source records.
- Standard data packets.
- Confirmation center.
- Merchant Memory.

Internal implementation can use "agents", "skills", "team lead", and "tool scopes"; merchant-facing copy should translate those into e-commerce operating language.

## Product Design Direction

### Merchant-Facing Layer

Name it around merchant work, not generic agents:

- `经营模板`
- `AI 岗位`
- `技能包`
- `工作队列`
- `确认规则`
- `商家记忆`

The first version should show a fixed but configurable workflow:

1. AI CEO receives merchant goal.
2. Market role reads official packet and public source records.
3. Listing role creates Listing Package.
4. Source/Finance role checks missing cost, fulfillment, and risk facts.
5. Asset role creates an asset brief, not fake finished files.
6. Service role creates product FAQ and customer-service boundaries.
7. Confirmation role sends risky items to confirmation center.

The merchant can adjust:

- Role on/off for a project.
- Required evidence before a role can complete.
- Category-specific rules.
- Low-risk automation level.
- Confirmation rules.

The merchant should not need to manually manage ten raw agents every day.

### Internal Runtime Layer

Add a `Merchant Workflow Template` contract:

```text
template_id
tenant_id
store_id
platform
merchant_stage
enabled_roles
role_order
required_inputs
allowed_tools
permission_policy
confirmation_policy
memory_scope
output_contracts
```

Add a `Merchant Skill Pack` contract:

```text
skill_pack_id
tenant_id
role_id
name
category_scope
instructions
source_requirements
forbidden_claims
quality_checks
created_by
version
```

Add a `Team Run` contract:

```text
run_id
template_id
store_id
goal
official_packet_ref
source_record_refs
role_runs
handoffs
quality_gates
confirmation_items
memory_writes
audit_events
```

### Browser Research Boundary

Jiejing can learn from Accio's browser automation, but only after the live eBay value loop is proven.

Safe boundary:

- Browser research is a source-record collector, not an executor.
- It can collect public competitor pages, supplier pages, product specs, screenshots, and citations.
- It cannot log into platform accounts unless the merchant grants a scoped session.
- It cannot publish, pay, refund, send buyer commitments, change policy, or buy ads.
- Every browser-derived fact must be marked as public webpage / merchant-provided / platform official / AI inference.

## Recommended Roadmap

### Now: Do Not Derail The MVP

Finish the current blocker first:

```text
merchant login
-> official eBay read-only packet
-> save BYOK model key
-> live model-backed Market Report + Listing Package
-> confirmation center
-> Merchant Memory
```

This is still the model_value_proof gate.

### V0.1: Show Existing Roles As A Configurable Operating Template

This is the fastest Accio-inspired improvement with low risk.

Add a settings/workflow page that shows:

- AI CEO
- Market
- Listing
- Source/Finance
- Asset
- Service
- Confirmation

For each role show:

- What it does.
- What data it can read.
- What it cannot do.
- Whether it is active.
- Whether it requires confirmation.

This reuses the existing Jiejing role contracts and does not require a full agent builder.

### V0.2: Merchant Skill Packs

Let merchants save reusable instructions:

- Category listing rules.
- Supplier verification checklist.
- Product claim forbidden words.
- Return/refund wording limits.
- Preferred profit floor.
- Shipping and handling preferences.

These should update role behavior through Merchant Memory and workflow templates.

### V0.3: Team Runs And Low-Risk Automation

Add an execution view where a merchant can see:

- Which role is running.
- Which evidence it used.
- What it handed off.
- What failed.
- What needs confirmation.

Low-risk recurring tasks can run automatically:

- Daily listing health report.
- Competitor price change watch.
- Missing field scan.
- Customer-service FAQ refresh.
- Policy mismatch scan.

High-risk actions still go to confirmation center.

### V0.4: Controlled Browser Research Agent

Add a browser/source collector only after:

- Tenant isolation tests pass.
- Permission policy is designed.
- Audit log captures every browser action.
- Merchant can revoke the capability.
- The output enters source records, not raw reports.

## Strategic Takeaway

Accio Work's moat is broad execution infrastructure. Jiejing's moat should be narrower and deeper:

1. eBay-first official data model.
2. Standard data packet and source record discipline.
3. Commerce-specific AI role contracts.
4. Confirmation center as the safety boundary.
5. Merchant Memory and workflow templates that improve with each run.
6. BYOK and tenant-scoped secret boundaries.
7. Evidence-backed reports and listing packages, not generic chat output.

The next product move should be:

> expose Jiejing's existing role system as configurable merchant operating templates, while keeping the AI CEO as the main merchant interface.

