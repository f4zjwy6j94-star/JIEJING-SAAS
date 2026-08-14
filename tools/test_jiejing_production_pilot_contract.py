#!/usr/bin/env python3
"""Contract checks for the isolated production-pilot deployment surface."""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ENV = ROOT / "deploy" / "jiejing-saas.production.env.example"
PRODUCTION_COMPOSE = ROOT / "deploy" / "docker-compose.production-pilot.yml"
PRODUCTION_IMAGES_LOCK = ROOT / "deploy" / "production-images.lock.json"
PRODUCTION_REQUIREMENTS_LOCK = ROOT / "requirements.saas.lock.txt"
PRODUCTION_BUILD_REQUIREMENTS_LOCK = ROOT / "requirements.saas-build.lock.txt"
STAGING_PATCH_APPLY = ROOT / "deploy" / "apply-staging-patch.sh"
CI_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "jiejing-ci.yml",
    ROOT / ".github" / "workflows" / "jiejing-cloud-fallback-self-check.yml",
    ROOT / ".github" / "workflows" / "jiejing-staging-manual-deploy.yml",
)
PRODUCTION_CADDY = ROOT / "deploy" / "Caddyfile.production"
PRODUCTION_ROBOTS = ROOT / "deploy" / "robots.production.txt"
PRODUCTION_NGINX = ROOT / "deploy" / "nginx.production.conf"
PRODUCTION_NGINX_SECURITY_HEADERS = ROOT / "deploy" / "nginx-security-headers.production.conf"
PRODUCTION_VAULT = ROOT / "deploy" / "vault.production.hcl"
PRODUCTION_VAULT_POLICY = ROOT / "deploy" / "vault-policy.production.hcl"
LOW_COST_SECRET_RUNBOOK = ROOT / "docs" / "JIEJING_LOW_COST_PRODUCTION_SECRET_BOUNDARY_20260814.md"
API_SERVER = ROOT / "jiejing_saas" / "api_server.py"
OWNER_LAUNCH_CONTROL = ROOT / "jiejing_saas" / "owner_launch_control.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _backend_route_samples(source: str) -> set[str]:
    routes = set(re.findall(r'''path\s*==\s*["']([^"']+)["']''', source))
    for group in re.findall(r'''path\s+in\s+\{([^}]+)\}''', source):
        routes.update(re.findall(r'''["']([^"']+)["']''', group))
    dynamic_roots = re.findall(r'''parts\[0\]\s*==\s*["']([^"']+)["']''', source)
    routes.update(f"{root}/__sample__" for root in dynamic_roots)
    routes.update(re.findall(r'''path\.startswith\(["']([^"']+)["']\)''', source))
    internal_only_routes = {"/health/startup"}
    return {
        f"/{route.strip('/')}"
        for route in routes
        if route and route.strip(" /,\t\r\n") and not route.startswith("http")
    } - internal_only_routes


def _compose_service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^volumes:\n|^networks:\n|\Z)",
        compose,
    )
    return match.group("body") if match else ""


def main() -> int:
    values = _values(PRODUCTION_ENV.read_text(encoding="utf-8"))
    expected = {
        "JIEJING_SAAS_ENV": "production",
        "JIEJING_PRIMARY_CUSTOMER_REGION": "mainland_china",
        "JIEJING_DOMESTIC_PAYMENT_PROVIDER": "wechat_pay_native",
        "JIEJING_BILLING_PROVIDER": "wechat_pay_native",
        "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "false",
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "false",
        "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "false",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
        "JIEJING_EBAY_WRITE_LIVE": "false",
        "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "true",
        "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "false",
        "JIEJING_VAULT_BACKUP_ARTIFACT_ID": "",
        "JIEJING_VAULT_RESTORE_DRILL_LAST_AT": "",
        "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED": "false",
        "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED": "false",
        "JIEJING_VAULT_UNSEAL_KEY_SHARES": "0",
        "JIEJING_VAULT_UNSEAL_KEY_THRESHOLD": "0",
        "JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED": "false",
    }
    mismatches = {
        key: {"expected": expected_value, "actual": values.get(key)}
        for key, expected_value in expected.items()
        if values.get(key) != expected_value
    }
    if mismatches:
        return fail(f"production pilot must select safe-held WeChat Native: {mismatches}")
    if any(key.startswith("JIEJING_STRIPE_") for key in values):
        return fail("production pilot must not retain the obsolete Stripe launch lane")

    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    if not PRODUCTION_REQUIREMENTS_LOCK.exists():
        return fail("production Python dependencies must have an exact hash lock")
    if not PRODUCTION_BUILD_REQUIREMENTS_LOCK.exists():
        return fail("production Python wheel toolchain must have an exact hash lock")
    requirements_lock = PRODUCTION_REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    if "--hash=sha256:" not in requirements_lock or re.search(r"(?m)^[a-zA-Z0-9_.-]+\s*[><~]", requirements_lock):
        return fail("production Python dependency lock must use exact versions and package hashes")
    build_requirements_lock = PRODUCTION_BUILD_REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    for build_tool in ("pip==", "setuptools==", "wheel==", "setuptools-scm==7.1.0", "pkgconfig=="):
        if build_tool not in build_requirements_lock:
            return fail(f"production Python wheel toolchain lock is incomplete: {build_tool}")
    for workflow in CI_WORKFLOWS:
        workflow_text = workflow.read_text(encoding="utf-8")
        if (
            'python-version: "3.12"' not in workflow_text
            or "--no-cache-dir --require-hashes -r requirements.saas-build.lock.txt" not in workflow_text
            or "--no-cache-dir --use-pep517 --no-build-isolation --require-hashes -r requirements.saas.lock.txt" not in workflow_text
            or "pip install --upgrade pip" in workflow_text
        ):
            return fail(f"CI/deploy must install the reviewed lock under production Python 3.12: {workflow.name}")
    if not PRODUCTION_IMAGES_LOCK.exists():
        return fail("production images must have one reviewed immutable digest lock")
    staging_patch_text = STAGING_PATCH_APPLY.read_text(encoding="utf-8")
    for release_lock in (
        '"deploy/production-images.lock.json"',
        '"requirements.saas.lock.txt"',
        '"requirements.saas-build.txt"',
        '"requirements.saas-build.lock.txt"',
    ):
        if release_lock not in staging_patch_text:
            return fail(f"production supply-chain lock must travel through the controlled release whitelist: {release_lock}")
    image_lock = json.loads(PRODUCTION_IMAGES_LOCK.read_text(encoding="utf-8"))
    locked_images = image_lock.get("images") if isinstance(image_lock, dict) else None
    if not isinstance(locked_images, dict) or set(locked_images) != {
        "jiejing-python-runtime",
        "jiejing-vault",
        "jiejing-frontend",
        "jiejing-edge",
    }:
        return fail("production image lock must cover the exact four runtime image boundaries")
    locked_refs: dict[str, str] = {}
    for name, record in locked_images.items():
        if not isinstance(record, dict):
            return fail(f"production image lock entry must be an object: {name}")
        repository = record.get("repository")
        tag = record.get("tag")
        digest = record.get("digest")
        if not isinstance(repository, str) or not isinstance(tag, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)):
            return fail(f"production image lock entry must use an exact tag and sha256 digest: {name}")
        locked_refs[name] = f"{repository}:{tag}@{digest}"
    dockerfile = (ROOT / "Dockerfile.saas").read_text(encoding="utf-8")
    for marker in (
        "COPY requirements.saas.lock.txt /build/requirements.saas.lock.txt",
        "COPY requirements.saas-build.lock.txt /build/requirements.saas-build.lock.txt",
        "pip install --require-hashes --no-cache-dir -r requirements.saas-build.lock.txt",
        "pip wheel --use-pep517 --no-build-isolation --require-hashes --no-cache-dir --wheel-dir /wheels -r requirements.saas.lock.txt",
        "COPY requirements.saas.lock.txt /app/requirements.saas.lock.txt",
        "pip install --no-cache-dir --no-index /wheels/*.whl",
    ):
        if marker not in dockerfile:
            return fail(f"production image must install only from the reviewed dependency lock: {marker}")
    python_from_refs = re.findall(r"(?m)^FROM\s+(\S+)\s+AS\s+", dockerfile)
    if python_from_refs != [locked_refs["jiejing-python-runtime"]] * 2:
        return fail("every production Python stage must use the reviewed immutable image digest")
    expected_compose_refs = {
        "jiejing-vault": 2,
        "jiejing-frontend": 1,
        "jiejing-edge": 1,
    }
    for name, expected_count in expected_compose_refs.items():
        if compose.count(f'image: {locked_refs[name]}') != expected_count:
            return fail(f"production Compose must use the reviewed immutable digest for {name}")
    for service in ("jiejing-saas", "jiejing-worker"):
        build_block = _compose_service_block(compose, service)
        if "sbom: true" not in build_block or "provenance: mode=max" not in build_block:
            return fail(f"{service} production image must emit native SBOM and provenance attestations")
    for service in (
        "jiejing-saas:",
        "jiejing-worker:",
        "jiejing-vault:",
        "jiejing-vault-token-renewer:",
        "jiejing-frontend:",
        "jiejing-edge:",
    ):
        if service not in compose:
            return fail(f"production pilot is missing required service {service}")
    for required_mount in (
        "../app.html:/usr/share/nginx/html/app.html:ro",
        "../privacy.html:/usr/share/nginx/html/privacy.html:ro",
        "../terms.html:/usr/share/nginx/html/terms.html:ro",
        "../refund-policy.html:/usr/share/nginx/html/refund-policy.html:ro",
        "../support.html:/usr/share/nginx/html/support.html:ro",
        "../risk-disclosure.html:/usr/share/nginx/html/risk-disclosure.html:ro",
    ):
        if required_mount not in compose:
            return fail(f"production frontend is missing required customer surface {required_mount}")
    if "tools/jiejing_worker_cli.py" not in compose or "redis_streams" not in values.get("JIEJING_QUEUE_PROVIDER", ""):
        return fail("production pilot must run the durable queue worker")
    if compose.count("../../private/jiejing-saas.production.env") != 2 or "./jiejing-saas.production.env" in compose.replace("../../private/jiejing-saas.production.env", ""):
        return fail("production credentials must be injected from the server-private env boundary")
    if compose.count("jiejing_production_data:/data") != 2:
        return fail("production API and worker must share one durable application-data volume")
    if compose.count("jiejing_production_media:/var/lib/jiejing/media-assets") != 2:
        return fail("production API and worker must share one durable generated-media volume")
    vault = PRODUCTION_VAULT.read_text(encoding="utf-8") if PRODUCTION_VAULT.exists() else ""
    vault_policy = PRODUCTION_VAULT_POLICY.read_text(encoding="utf-8") if PRODUCTION_VAULT_POLICY.exists() else ""
    if values.get("JIEJING_VAULT_ADDR") != "http://jiejing-vault:8200":
        return fail("budget production must use the private self-hosted Vault service instead of requiring paid KMS")
    for marker in (
        "hashicorp/vault:1.21.4@sha256:",
        "vault.production.hcl",
        "jiejing_production_vault_data:/vault/file",
        "IPC_LOCK",
    ):
        if marker not in compose:
            return fail(f"production self-hosted Vault boundary is missing {marker}")
    if "ports:" in compose.split("jiejing-vault:", 1)[1].split("jiejing-frontend:", 1)[0]:
        return fail("production Vault must not expose a host port")
    if "jiejing_secrets:\n    internal: true" not in compose:
        return fail("production Vault must run on a dedicated internal Docker network")
    vault_service = _compose_service_block(compose, "jiejing-vault")
    if "- jiejing_secrets" not in vault_service or "- jiejing_app" in vault_service:
        return fail("Vault must attach only to the internal secrets network")
    for public_service in ("jiejing-frontend", "jiejing-edge"):
        block = _compose_service_block(compose, public_service)
        if "jiejing_secrets" in block:
            return fail(f"{public_service} must not be able to reach the Vault network")
    if "vault status -format=json" not in vault_service or "condition: service_healthy" not in compose:
        return fail("API startup must wait for initialized and unsealed Vault health")
    renewer_block = _compose_service_block(compose, "jiejing-vault-token-renewer")
    if "vault token renew" not in renewer_block or "vault token lookup -field=renewable" not in renewer_block or "vault token lookup -field=period" not in renewer_block:
        return fail("periodic backend Vault token must be renewed and monitored")
    if "../../private/jiejing-vault-token:/run/secrets/jiejing-vault-token:ro" not in compose:
        return fail("API, worker and renewer must share one read-only Vault token file")
    if compose.count("../../private/jiejing-vault-token:/run/secrets/jiejing-vault-token:ro") != 3:
        return fail("exactly API, worker and renewer must receive the single Vault token file")
    if 'JIEJING_VAULT_TOKEN_FILE: "/run/secrets/jiejing-vault-token"' not in compose:
        return fail("application services must resolve the shared Vault token file")
    if "../../private/jiejing-saas.production.env" in renewer_block:
        return fail("Vault renewer must not receive application, eBay, model, database or payment secrets")
    if "cat /run/secrets/jiejing-vault-token" not in renewer_block:
        return fail("Vault renewer must read the same token file as API and worker")
    if "http://127.0.0.1:8788/health/startup" not in compose:
        return fail("API container health must use the non-2xx dependency startup probe")
    for marker in ('storage "file"', 'path = "/vault/file"', 'address = "0.0.0.0:8200"', "tls_disable = true"):
        if marker not in vault:
            return fail(f"production Vault config is missing {marker}")
    if "disable_mlock = false" not in vault:
        return fail("production Vault must lock decrypted secret pages out of host swap")
    if any(marker in vault.lower() for marker in ("dev-root-token", "root_token", "unseal_key", "auto_unseal")):
        return fail("production Vault config must not contain root tokens, unseal keys, or unsafe auto-unseal material")
    for policy_marker in (
        'path "secret/data/jiejing-production/*"',
        'capabilities = ["create", "update", "read", "delete"]',
        'path "secret/metadata/jiejing-production/*"',
        'capabilities = ["list", "read", "delete"]',
        'path "auth/token/lookup-self"',
        'path "auth/token/renew-self"',
    ):
        if policy_marker not in vault_policy:
            return fail(f"production Vault least-privilege policy is missing {policy_marker}")
    if any(marker in vault_policy for marker in ('path "secret/*"', 'path "*"', 'capabilities = ["sudo"]')):
        return fail("production Vault policy must not grant wildcard or sudo access")
    secret_runbook = LOW_COST_SECRET_RUNBOOK.read_text(encoding="utf-8") if LOW_COST_SECRET_RUNBOOK.exists() else ""
    for marker in (
        "kms is optional",
        "manual unseal",
        "offline",
        "encrypted off-host backup",
        "never store the unseal key",
    ):
        if marker not in secret_runbook.lower():
            return fail(f"low-cost production secret runbook is missing {marker}")

    caddy = PRODUCTION_CADDY.read_text(encoding="utf-8")
    if "{$JIEJING_PRODUCTION_HOST}" not in caddy or "app.example.com" in caddy:
        return fail("production edge must require an explicitly injected production hostname")
    if 'JIEJING_PRODUCTION_HOST: "${JIEJING_PRODUCTION_HOST:?set an isolated production hostname}"' not in compose:
        return fail("production compose must inject the required hostname into the edge container")
    if 'JIEJING_ACME_EMAIL: "${JIEJING_ACME_EMAIL:?set the production ACME contact}"' not in compose:
        return fail("production compose must inject the required ACME contact into the edge container")
    if "{$JIEJING_ACME_EMAIL}" not in caddy or "ops@example.com" in caddy:
        return fail("production edge must not retain a placeholder ACME identity")
    global_header = caddy.split("@blockedInternalPath", 1)[0]
    if "X-Robots-Tag" in global_header:
        return fail("production public website must not send a global noindex header")
    for protected_path in ("/app.html", "/auth/*", "/owner/*", "/billing/*", "/confirmations*"):
        if protected_path not in caddy:
            return fail(f"production private surface must remain noindex: {protected_path}")
    if "X-Robots-Tag \"noindex, nofollow, noarchive, nosnippet, noimageindex\"" not in caddy:
        return fail("production private surfaces must keep the strict noindex header")
    for api_path in (
        "/health/deep",
        "/schema/chain",
        "/platforms",
        "/infrastructure/drivers",
        "/product-feedback",
        "/analytics/*",
        "/companies*",
        "/permissions/*",
        "/security/*",
        "/data-packets",
        "/data-packets/*",
        "/ip-risk-screening",
        "/ip-risk-screening/*",
        "/merchant-memory",
        "/merchant-memory/*",
        "/media-source-assets/*",
        "/merchant-onboarding/*",
        "/ai-ceo/*",
        "/workers/*",
        "/controlled-bridges",
        "/controlled-bridges/*",
    ):
        if api_path not in caddy:
            return fail(f"production edge API allowlist is missing {api_path}")
    api_matcher_line = next((line.strip() for line in caddy.splitlines() if line.strip().startswith("@api path ")), "")
    api_patterns = api_matcher_line.split()[2:]
    backend_routes = _backend_route_samples(API_SERVER.read_text(encoding="utf-8"))
    uncovered_routes = sorted(
        route
        for route in backend_routes
        if not any(fnmatch.fnmatchcase(route, pattern) for pattern in api_patterns)
    )
    if uncovered_routes:
        return fail(f"production edge must route every backend HTTP surface to the API: {uncovered_routes}")
    if "/health/startup" in api_patterns:
        return fail("internal dependency startup probe must not be exposed by the public edge")
    if "./robots.production.txt:/usr/share/nginx/html/robots.txt:ro" not in compose:
        return fail("production frontend must use a production-specific robots policy")
    if "./nginx.production.conf:/etc/nginx/conf.d/default.conf:ro" not in compose or "nginx.public-staging.conf" in compose:
        return fail("production frontend must not reuse the staging host allowlist")
    if "./nginx-security-headers.production.conf:/etc/nginx/snippets/jiejing-security-headers.conf:ro" not in compose:
        return fail("production frontend must mount the shared security-header contract")
    nginx = PRODUCTION_NGINX.read_text(encoding="utf-8") if PRODUCTION_NGINX.exists() else ""
    nginx_security_headers = (
        PRODUCTION_NGINX_SECURITY_HEADERS.read_text(encoding="utf-8")
        if PRODUCTION_NGINX_SECURITY_HEADERS.exists()
        else ""
    )
    for marker in (
        "server_name _;",
        "location = /app.html",
        "return 302 https://$host/index.html?source=direct_app_entry&start=site",
        "location = /ops.html { return 404; }",
        "location ~* \\.map$",
        "location ~ ^/(?:\\.git|\\.github|deploy|tools|docs|tests|jiejing_saas|jiejing_runtime|schemas|output|private)(?:/|$)",
    ):
        if marker not in nginx:
            return fail(f"production static server is missing safety marker: {marker}")
    for security_header in (
        'X-Frame-Options "DENY" always',
        'X-Content-Type-Options "nosniff" always',
        'Referrer-Policy "strict-origin-when-cross-origin" always',
        'Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always',
        "Content-Security-Policy $jiejing_csp always",
    ):
        if security_header not in nginx_security_headers:
            return fail(f"production shared header contract is missing {security_header}")
    if nginx.count("include /etc/nginx/snippets/jiejing-security-headers.conf;") < 7:
        return fail("every production response location with local add_header values must include the shared security headers")
    if "app.jiejing.shop" in nginx or "trycloudflare.com" in nginx or "43.129.205.244" in nginx:
        return fail("production static server must not retain staging host identities")
    robots = PRODUCTION_ROBOTS.read_text(encoding="utf-8") if PRODUCTION_ROBOTS.exists() else ""
    if "Allow: /" not in robots or "Disallow: /app.html" not in robots or "Disallow: /owner/" not in robots:
        return fail("production robots policy must index the public site while excluding private surfaces")
    if values.get("JIEJING_PUBLIC_BASE_URL") != "https://<production-host>" or values.get("JIEJING_CORS_ORIGIN") != "https://<production-host>":
        return fail("production URLs must use one explicit isolated production host placeholder")
    canonical_host_expression = "${JIEJING_PRODUCTION_HOST:?set an isolated production hostname}"
    runtime_host_bindings = {
        "JIEJING_PUBLIC_BASE_URL": f'"https://{canonical_host_expression}"',
        "JIEJING_PUBLIC_APP_URL": f'"https://{canonical_host_expression}"',
        "JIEJING_STABLE_DOMAIN": f'"{canonical_host_expression}"',
        "JIEJING_TARGET_APP_HOST": f'"{canonical_host_expression}"',
        "JIEJING_CORS_ORIGIN": f'"https://{canonical_host_expression}"',
        "JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL": (
            f'"https://{canonical_host_expression}/webhooks/ebay/marketplace-account-deletion"'
        ),
        "JIEJING_WECHAT_PAY_NOTIFY_URL": (
            f'"https://{canonical_host_expression}/billing/domestic/wechat-pay/notify"'
        ),
        "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL": (
            f'"https://{canonical_host_expression}/billing/domestic/wechat-pay/refund-notify"'
        ),
        "JIEJING_TURNSTILE_ALLOWED_HOSTNAMES": f'"{canonical_host_expression}"',
    }
    missing_runtime_bindings = {
        key: compose.count(f"{key}: {expected_value}")
        for key, expected_value in runtime_host_bindings.items()
        if compose.count(f"{key}: {expected_value}") != 2
    }
    if missing_runtime_bindings:
        return fail(
            "API and worker must derive every public URL/callback/CORS host from "
            f"the edge hostname: {missing_runtime_bindings}"
        )
    owner_launch_control = OWNER_LAUNCH_CONTROL.read_text(encoding="utf-8")
    if owner_launch_control.count("https://app.jiejing.shop") != 1 or "JIEJING_PUBLIC_BASE_URL" not in owner_launch_control:
        return fail("production owner proof links must derive from JIEJING_PUBLIC_BASE_URL, with staging only as the default fallback")
    api_server_source = API_SERVER.read_text(encoding="utf-8")
    if 'environment == "production" and not readiness.get("production_ready")' in api_server_source:
        return fail("safe-held production candidates must boot before paid/public readiness is approved")
    if "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED" not in api_server_source:
        return fail("production candidate boot must require an explicit fail-closed deployment flag")
    if "effective_ebay_draft_save_enabled" not in api_server_source:
        return fail("production candidate boot must explicitly reject the controlled eBay draft-save write lane")
    production_urls = {
        key: value
        for key, value in values.items()
        if key.endswith("_URL") or key.endswith("_HOSTNAMES")
    }
    stale_urls = {key: value for key, value in production_urls.items() if "app.jiejing.shop" in value or "app.example.com" in value}
    if stale_urls:
        return fail(f"production callbacks must not target staging or example hosts: {stale_urls}")
    print("PASS jiejing_production_pilot_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
