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

## Same acceptance pass: additional proven blockers

The first candidate gate was stopped before packaging because C exposed further direct blockers. Production remains on the previous release until a new exact candidate passes its full gate.

- `semantic_plan_missing_research_queries`: one bounded model correction is allowed only for open research with no project, image reading, facts or simulation mutation. First validate all other fields independently. Preserve every nonquery scope/authority field, including count, exclusions and whether to save its report; only the query pair and nonexecuting explanatory text may change. The strict validator still checks the corrected result. Any escalation, second invalid result, timeout or other invalid field fails closed. Invalid raw model output is never echoed into feedback.
- A neutral aligned Markdown availability label can look like a positive assertion when its value is split away. Pair each label with its own value for this check only. Do not let another field/footer's disclaimer cancel positive assertions, including headings. Malformed tables stay conservative. Sources, item relevance, price/brand and factual evidence validators are unchanged. This locally reproduced issue is not presented as the proven cause of the unavailable raw production answer.
- Monthly operating-task usage incorrectly counted request/attempt/fact-save/vision bookkeeping as extra operations. Exclude only `ai_ceo_chat_request`, `merchant_ceo_chat_attempt`, `merchant_product_facts`, and `ai_ceo_product_vision` from this single usage projection. Preserve all audit records and meter actual business tasks and unknown legacy types, regardless of status. No changes to plan amounts, entitlements, provider usage, 20-turn trial, keys or permissions. Real authenticated HTTP must prove 120 internal records do not consume business slots, 99→100 still works, replay does not consume again, and repeated fresh requests at the real limit stay blocked without model consumption.

These additions remain within the approved autonomous acceptance repairs. Re-run full affected suites and the exact clean release gate; do not reuse the stopped candidate's partial evidence. Do not claim completion until the actual SaaS path is exercised.

Live C also remained in “正在思考” after a terminal quota rejection, even after normal reload. The frontend filtered all `blocked_before_model_chat` turns, so neither the immediate result nor server archive could replace a pending turn. Retain those terminal answers, while still filtering historical technical placeholders. The real-browser regression must fail before the fix (996838) and prove immediate settlement, exact-identity archive recovery, no duplicate, and preserved pagination/account isolation. Update the shared app cache tag; no visual redesign.
