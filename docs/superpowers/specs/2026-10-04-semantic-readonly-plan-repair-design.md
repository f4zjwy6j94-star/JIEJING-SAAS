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

## Post-deployment C: query-only completion

Release 0c119a1 passed273 and deployed. Exact B consultation now answers and all35 saved fields remain unchanged. Exact C research request `05a412621dcd3e787c6e5ca7abb7949d` still failed: read-only production b36eff established `semantic_plan_repair_scope_changed` at request `task_ai_ceo_request_f2b4d70e1100de3add4233125d5d7b77b319431a`. This proves the bounded repair changed a protected field; raw rejected plans are not retained, so the exact changed field and whether it was synonym-only remain unknown.

The previous repair asked for another complete plan without supplying the first validated scope. Instead of loosening comparison or repeatedly rewording the merchant's request, make the provider repair interface strictly query-only. Independently validate the first plan's other fields as before, freeze every nonquery field (including explanatory steps/question), and give the same model the merchant message plus that validated scope, without irrelevant current-product/history or invalid query text. Require exactly `{research_queries:[{subject,query}]}`. Reject any extra fields rather than ignoring attempted scope changes. Mechanically project the first generated query into the redundant top-level query and validate the entire assembled plan with the unchanged validator. The model still determines intent and search terms; no local keyword interpretation, new authority, third attempt, or hidden permission is introduced. Initial45/repair20second budgets and normal metering remain.

Regression: provider-boundary query-only completion RED71c9ce to GREEN2e5f64; preserve every frozen field, reject full-plan/extra-key scope changes, malformed queries and retries. The existing authenticated HTTP research/replay/report-isolation scenario must now use this provider contract, and an attempted new-project patch must leave all reports unchanged. No API/repository/frontend or price/entitlement change is needed. This is a narrow continuation of the already authorised autonomy, not a new product-direction decision. Complete focused verification, exact-source gate, same-package deploy and actual C webpage replay remain required.

## Idle-session precheck found during the same acceptance

After more than30minutes on B, the actual publish-precheck action returned to the session-expired login page. Normal original-account login restored all35 saved values, and the same UI check then completed12passed/4simulation-account-source blockers/1not-applicable. The production POST path has no session preflight, while generic automatic refresh intentionally only replays reads and a narrowly approved history-sync request. Do not widen that replay list or extend token lifetime.

The owned real-browser/HTTP-boundary regression reproduces an expired access session as401 before the change (8998da). Add the existing protected GET/session-renewal check before the original precheck POST, verify the returned live identity, bound this verification to10seconds, and invalidate it on product/source/input/account changes. Exactly one original read-only product check may follow; revoked refresh, changed scope, timeout or cookie-account mismatch sends none. An ordinary post-preflight POST401 is not refreshed or replayed. No authentication policy, permissions, eBay write, charging, product facts or confirmation boundary changes. Extend the existing session browser suite and unit fixtures, atomically update frontend asset versions, and use a newly frozen exact-source full gate. The3c2 candidate's failed gate must remain failed evidence, not be overwritten by isolated successful reruns.

## Post-90a source-format compatibility

Production C request f2a8f9ffa58848c9bfd5093cd1d189b1 reached two successful searches and five product sources, but the answer failed price, availability and source-attribution checks. Its rejected raw answer was not retained, so do not claim its precise wording or all causes are known. One bounded merchant revision24429c644fded8b266390b8a1e3f01f2 produced the correct read-only research plan and two successful searches, but zero accepted item sources. Read-only task metadata72e04b showed explicit bilingual subjects, including `自粘桌面理线夹 adhesive cable clips`. The source filter treated any Chinese-containing subject as an exact whole phrase, incorrectly rejecting the corresponding reordered English listing title.

Recognize explicit space/parenthesis/slash bilingual labels, without translating, generating synonyms, selecting intent locally, or changing model authority. English aliases keep the existing head-term and overlap threshold; Chinese aliases retain exact phrase matching. A lone acronym/model/size is not enough to split a mixed label. Reuse this parsing in report-to-planned-subject binding so a Chinese report heading can use its own planned English alias, never another candidate's sources. The authenticated HTTP regression uses only model/search provider doubles: initialRED8ec334, thenGREEN33fad2; Chinese-only headings separatelyRED eff8f4, thenGREEN be9b51. It covers report persistence, replay, existing-product preservation, reordered titles, peer-source rejection and three explicit alias formats. These fixtures do not prove live C completion.

Local adversarial validation also reproduced a related format defect: `当前在售状态：未知` (and 不详/待确认) was treated as a positive current-sale claim (RED4febac). Exempt only a complete, explicitly labelled unknown status clause. Unknown price/stock, peer cells or a footer cannot exempt a positive sale assertion. The complete42 source-evidence tests passed2a885d. This is independently demonstrated compatibility, not proof that f2 used this exact phrase. Ambiguous-price and positive-availability blockers are not disabled. No API, repository, permission, fact, billing or frontend changes are included. Full exact-source release verification and actual UI C replay remain required.
