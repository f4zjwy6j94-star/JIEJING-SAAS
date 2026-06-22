# Jiejing Cloud Clean Deploy Status - 2026-05-20

## What Changed

- Deployed the cleaned merchant-facing SaaS surface to the active Hong Kong staging host.
- Active host: `43.129.205.244`.
- Active temporary HTTPS route: `https://individually-buffalo-prescribed-blocking.trycloudflare.com`.
- Kept eBay OAuth untouched.
- Did not rerun official eBay sync.
- Kept real platform writes disabled.

## Product Surface Cleanup

- Public homepage and merchant workbench no longer render visible demo/mock/simulated wording.
- Runtime product-copy filter remains in place to keep legacy internal branches from leaking demo language into merchant-facing UI.
- `assets/cable-organizer.svg` replaces the old demo-named frontend asset path.
- Static guard now blocks visible public text containing `模拟`, `演示`, `内测`, `测试用`, `demo`, `mock`, `sample`, `simulated`, or `tutorial`.

## Cloud Deploy Notes

- Remote backup created on the HK host under `/home/ubuntu/jiejing-backups/`.
- Deployed current source package to `/opt/jiejing-staging/app`.
- Rebuilt and restarted:
  - `deploy-jiejing-saas-1`
  - `deploy-jiejing-worker-1`
  - `deploy-jiejing-frontend-1`
- Kept `deploy-jiejing-vault-1` running.

## Hong Kong Routing Fix

The HK host uses host-level Caddy on port 80:

```text
host Caddy :80 -> 127.0.0.1:18080 -> deploy-jiejing-frontend-1 -> backend
```

To prevent future deploys from breaking this route:

- `deploy/docker-compose.public-https-staging.yml` now maps frontend to `127.0.0.1:18080:80`.
- The optional compose-managed edge service is behind the `compose-edge` profile and does not start during normal HK deploys.

Normal HK deploy command:

```bash
cd /opt/jiejing-staging/app
sudo docker compose -f deploy/docker-compose.public-https-staging.yml -p deploy up -d --build
```

Do not start the `compose-edge` profile on the current HK host unless host Caddy is stopped first.

## Verification

Local and remote checks passed:

```text
python -m compileall jiejing_saas jiejing_runtime
node --check app.js
python tools/test_jiejing_merchant_byok_model_and_memory.py
python tools/test_jiejing_model_value_rehearsal.py
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_frontend_staging_config.py
python tools/test_jiejing_saas_p0_security_guardrails.py
```

Cloud checks:

- `http://43.129.205.244/health`: 200
- `https://individually-buffalo-prescribed-blocking.trycloudflare.com/health`: 200
- `POST /auth/demo-session`: 403
- `readiness.environment`: `staging`
- `readiness.real_platform_writes_enabled`: `false`
- `readiness.blocker_count`: `1`
- remaining blocker: live model-backed value proof

Rendered page checks:

- `http://43.129.205.244/`: forbidden visible demo markers = 0
- `http://43.129.205.244/app.html`: forbidden visible demo markers = 0
- `https://individually-buffalo-prescribed-blocking.trycloudflare.com/`: forbidden visible demo markers = 0
- `https://individually-buffalo-prescribed-blocking.trycloudflare.com/app.html`: forbidden visible demo markers = 0

## Next Real Flow Test

Next step is not another eBay OAuth or official sync. Use the existing official packet and run:

1. Merchant login.
2. Confirm existing eBay official packet is visible.
3. Save a merchant BYOK model key through the model account panel.
4. Trigger live model-backed Market Report and Listing Package.
5. Review report quality and confirmation-center outputs.

