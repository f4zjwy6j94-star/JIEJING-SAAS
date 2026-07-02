# Jiejing Commercial Launch Runbook - 2026-05-26

This runbook is for paid SaaS launch operations. It must not contain payment
secrets, eBay tokens, model keys, passwords, or raw webhook payloads.

## Launch Gates

Paid public launch is blocked until all gates are green:

1. Stable HTTPS domain is selected and DNS resolves to the production edge.
2. TLS is valid and security headers are verified.
3. eBay RuName/callback uses the stable HTTPS domain.
4. CORS allows only the stable frontend origin.
5. Stripe or Paddle is configured with real plan IDs and a signed webhook.
6. Quota enforcement is enabled and merchant-visible.
7. Managed Postgres, queue, Vault/KMS, backup, monitoring, and restore evidence are present.
8. Market Report and Listing Package are generated in Chinese from sanitized official packet data.
9. Real platform writes remain behind confirmation center records.

## Incident Response

### eBay OAuth Or Token Resolution Failure

- Do not repeat OAuth automatically.
- Check connection status, secret_ref presence, and backend token resolution result.
- Never print raw access tokens, refresh tokens, auth codes, or client secrets.
- If merchant reauthorization is required, create a clear action in Settings.

### eBay Read-Only Packet Failure

- Check route health per resource: store profile, business policies, inventory/offers,
  orders/fulfillment, finances, taxonomy.
- Preserve partial official packet data with source gaps.
- Do not replace missing official data with demo products.

### Real Publish Failure Or Ambiguous 502

- Do not retry blindly.
- Check eBay by SKU, offer id, and listing id first.
- If eBay already published the offer, backfill the SaaS execution record.
- If eBay returned seller quota, restricted category, policy, or VeRO errors, treat them
  as business constraints and show them in the confirmation/execution record.
- Cleanup of live test listings must create a separate confirmation item.

### Billing Webhook Failure

- Verify provider, endpoint URL, signature secret presence, and timestamp tolerance.
- Do not store raw webhook body or payment method data.
- If subscription state is uncertain, mark quota status as review required rather than
  silently upgrading or blocking the merchant.

### Backup Or Restore Drill Failure

- Confirm managed database backup/PITR policy, object storage target, alert policy,
  and last restore drill timestamp.
- Restore drill must verify users, companies, stores, connections, secret_refs,
  packets, tasks, reports, confirmations, execution_results, and audit_logs.
- Raw secrets must remain in Vault/KMS and must not be exported into backup artifacts.

### Model Provider Failure Or Cost Spike

- Keep existing BYOK secret_ref unchanged.
- Report provider error category: auth, model rejected, quota/balance, timeout, or
  client injection failure.
- Fall back to blocked status, not fake model output.
- Large model or media batches require quota/cost gate before execution.

## Required Environment Evidence

Set these only after the corresponding operational evidence exists:

```text
JIEJING_PUBLIC_BASE_URL=https://app.<domain>
JIEJING_STABLE_DOMAIN=app.<domain>
JIEJING_DOMAIN_DNS_VERIFIED=1
JIEJING_TLS_VERIFIED=1
JIEJING_EBAY_CALLBACK_VERIFIED=1
JIEJING_DEPLOYMENT_HARDENED=1
JIEJING_SECURITY_HEADERS_VERIFIED=1
JIEJING_BILLING_PROVIDER=stripe|paddle
JIEJING_BILLING_WEBHOOK_URL=https://app.<domain>/billing/webhook
JIEJING_STRIPE_WEBHOOK_API_VERSION=2026-06-24.dahlia
JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED=1
JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID=<recorded duplicate/delayed/out-of-order webhook drill id>
JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID=<recorded portal/cancel/invoice/payment-failure drill id>
JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID=<recorded rollback/secret-scan/readiness/browser-smoke packet id>
JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID=<owner approval packet id after all evidence is attached>
JIEJING_BILLING_PLANS_PUBLISHED=1
JIEJING_QUOTA_ENFORCEMENT_ENABLED=1
JIEJING_INCIDENT_RUNBOOK_PUBLISHED=1
JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED=1
JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED=1
JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED=1
JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED=1
```

Provider secrets and price IDs are configured in the deployment secret store,
not in this file.
