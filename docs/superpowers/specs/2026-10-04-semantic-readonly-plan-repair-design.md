# Read-only semantic-plan repair

## Scope and evidence

Continue the user-approved three-product acceptance and autonomous defect repair. Do not redesign the product or introduce keyword routing. Production cost consultation `8725aa5608e5330c58248980fdbc331a` was rejected with `semantic_plan_non_workflow_mutation`; the existing strict validator protects product state but gives the model no chance to correct a contradictory non-workflow plan.

Alternatives considered: prompt-only clarification is inexpensive but does not recover malformed combinations; relaxing the validator weakens the boundary. Chosen: clarify the prompt and allow one narrowly bounded model repair, still subject to the unchanged validator and a read-only ceiling.

## Contract

- Only the existing model client can reconsider intent. No local text/keyword interpretation.
- Retry at most once, only for a structurally valid plan rejected for non-workflow binding. Rejected model fields are never authorization. Other malformed, sensitive, authority-bearing, provider-failed or truncated outputs fail immediately. The one repair uses a 20-second provider timeout after the initial 45-second limit.
- Send original merchant message/context plus a fixed safe validation code and contract guidance. Never forward invalid model output, exception text or credentials.
- The corrected plan must still be read-only: no new project, artifact, image consumption, fact proposal, simulation mutation, live action, remembered rule or new external search. It must pass the existing validator. Otherwise fail closed.
- Existing metering records both planner requests. HTTP replay does not repeat them. No changes to authentication, tenant/project scope, costs/quota policy, eBay permissions, confirmation gates or persistence rules.

## Implementation and verification plan

1. Add a provider-boundary sequential fixture to the existing real authenticated HTTP simulation suite. Reproduce chat/current with no effects, then a valid read-only model plan; before fix it must fail.
2. Add one repair to the semantic planner, not API/repository. Retain original validator unmodified.
3. Verify successful consultation preserves complete facts, checkpoint/revision, all 35 saved publishing fields, rights and simulation. Verify repeated invalid output, escalation on repair, timeout, sensitive/unknown fields stay blocked; metering and replay remain honest.
4. Run focused semantic/HTTP tests and scoped code review, then the normal release gate/dry-run/apply procedure for the exact candidate. Do not reuse d320's gate as proof of a new candidate.
5. Replay the original B consultation through normal SaaS UI; finish B, then C, then return to A. Existing A/B copy/images are not regenerated. No real eBay write.

Small adjacent UI correction: the actual B precheck returned `listing.item_specifics.Brand`, but the page reduced it to “相关必填资料”. Add explicit safe labels for Brand/Type/Material, retaining the same blocked state. Unknown fields remain generic rather than exposing raw diagnostics. The old advanced draft-only panel is a separately recorded display inconsistency, not proof of missing saved publishing values or an excuse to clear safeguards.

This narrow non-visual fix implements the user's existing autonomous repair approval; no new product-direction choice is needed. Completion requires actual UI evidence, not only tests.
