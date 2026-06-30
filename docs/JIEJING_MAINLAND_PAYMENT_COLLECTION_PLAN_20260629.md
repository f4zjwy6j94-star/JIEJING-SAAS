# JIEJING Mainland Payment Collection Plan

Date: 2026-06-29

This plan keeps JIEJING aligned with mainland China users while avoiding fake paid-launch readiness. It does not store payment secrets in frontend code and does not trigger real charges.

## Decision

JIEJING should use domestic collection as the main route for mainland users:

1. Private beta: manual WeChat/Alipay personal collection code plus manual account activation.
2. Formal launch: WeChat Pay, Alipay, UnionPay/Cloud QuickPass, or a licensed aggregate acquirer.
3. Cross-border fallback: Stripe or PayPal only for overseas customers or supported international billing.
4. Settlement tools such as WorldFirst or Payoneer are not the primary SaaS checkout.

## Why Not Personal QR For Formal SaaS

Personal collection codes are acceptable for small private beta reconciliation, but not for formal automated SaaS billing.

They do not give JIEJING a signed webhook, automatic subscription renewal, reliable order-to-company mapping, failed-payment quota stop, refund workflow, invoice/audit evidence, or dispute handling.

## Current Product Position

The product can show the domestic payment strategy and can run no-real-charge rehearsals. It must not claim paid public launch readiness until a real merchant provider is onboarded and callback proofs are recorded.

Current safe state:

- Email login remains the only login path.
- QR login has been removed from the current product path.
- Domestic payment strategy can be displayed and tested without secrets.
- Manual collection remains private-beta-only.
- Real payment credentials must enter backend Vault/env only.

## Recommended Rollout

1. Keep private beta payment manual: collect via personal WeChat/Alipay code, then manually activate subscription/quota in admin tooling.
2. Prepare merchant qualification: individual business license or company entity for formal payment provider onboarding.
3. Choose formal provider: direct WeChat Pay/Alipay/UnionPay if qualifications are ready; otherwise evaluate a licensed aggregate acquirer.
4. Build backend provider adapter before live cutover: create order, signed callback, order query, refund status, subscription/quota update, audit record, and no-real-charge rehearsal.
5. Only after provider sandbox/live credentials are ready: configure callbacks on `https://app.jiejing.shop`, run no-real-charge rehearsal, then owner-approved live cutover.

## Formal Launch Architecture

The production payment spine should stay the same regardless of whether the first formal provider is Alipay, WeChat Pay, UnionPay, LianLian, Airwallex, Stripe, or another approved acquirer:

1. JIEJING creates an internal billing order for the signed-in company and selected plan.
2. The backend creates a provider checkout/QR order through a merchant account.
3. The provider redirects or notifies the backend callback URL.
4. The backend verifies a signed callback and, when needed, actively queries the provider order.
5. Only verified provider evidence updates subscription status, quota, invoice/audit records, and entitlement shutdown.
6. Refunds, disputes, abnormal chargebacks, and manual overrides stay in the owner/admin confirmation boundary.
7. The owner approves live cutover after no-real-charge rehearsal passes.

Personal Alipay or WeChat collection codes can be used only for private beta manual reconciliation. They must not automatically activate quotas or be described as a paid public launch provider.

## Private Beta Manual Order Flow

The current test path is a manual beta bridge, not a formal payment provider:

1. A signed-in merchant creates a 99 CNY / 30-day starter beta payment order in Settings.
2. JIEJING generates a random payment note such as `JJ-BETA-******` and writes an audit record.
3. The personal QR image, collection account details, and any payment proof stay outside the repository and frontend bundle.
4. An internal owner/admin confirms external receipt after checking the payment note.
5. Only that confirmation writes a `manual_beta` subscription event and activates the starter entitlement for the company.

Ordinary merchants cannot confirm receipt. This keeps the test usable before a merchant payment account is ready, while preserving the later production spine: real provider order, signed callback, subscription state, quota update, and audit.

## Domain, ICP, and Entity Path

The current public app entry can remain on the Hong Kong/overseas route for private beta and global access. This should not be described as "Hong Kong ICP filing"; mainland ICP filing is normally tied to mainland-hosted websites and mainland review flows.

When the owner later opens a mainland company or individual business entity, there is no inherent conflict with the current `app.jiejing.shop` route if the payment/domain plan is kept clean:

- keep `app.jiejing.shop` as the current SaaS app entry;
- prepare `cn.jiejing.shop` or `pay.jiejing.shop` if a domestic payment provider requires a reviewed mainland website/domain;
- keep the payment merchant subject, ICP subject or authorization, provider callback URL, and public product description consistent;
- keep all provider secrets and certificate private keys in backend Vault/env only.

This adds operational steps, but it is manageable. The risky path would be mixing a personal static QR, an unreviewed website, and automatic subscription activation while claiming paid public launch readiness.

## Formal Merchant Payment Application Packet

Before JIEJING can use WeChat Pay, Alipay, UnionPay/Cloud QuickPass, LianLian, Airwallex, or another licensed acquirer as the automated paid SaaS collection rail, the owner needs a review packet that is consistent with the registered subject and public website.

The current product surfaces this packet in Settings as a public-safe readiness checklist. It is for preparation only; it does not upload identity files, store settlement bank details, expose provider secrets, or trigger a real charge.

The packet covers:

- merchant subject: individual business or company license;
- operator KYC and settlement account readiness;
- service agreement, privacy policy, risk/refund explanation, and customer support contact;
- pricing, subscription, quota, and overdue shutdown rules;
- reviewed app domain and payment callback URLs such as `https://app.jiejing.shop/billing/webhook`;
- backend-only signed webhook and active order-query proof before automatic entitlement activation.

This keeps the beta path simple while preserving the formal target: merchant order creation, signed provider evidence, subscription/quota update, invoice/audit record, and owner-approved live cutover.

## External Items The Owner Must Provide Later

- Merchant entity information and payment provider approval.
- Provider app/merchant IDs and certificate/key references.
- Webhook/callback URLs configured in the provider console.
- Backend Vault/env entries for secrets and certificates.

No provider secret, key, certificate private material, or webhook secret should be written into docs, frontend code, screenshots, or chat.
