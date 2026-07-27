#!/usr/bin/env python3
"""Regression checks for public anti-scrape and no-index hardening."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROBOTS = ROOT / "robots.txt"
NGINX = ROOT / "deploy" / "nginx.public-staging.conf"
CADDY_FILES = [
    ROOT / "deploy" / "Caddyfile.public-staging",
    ROOT / "deploy" / "Caddyfile.public-staging.systemd",
    ROOT / "deploy" / "Caddyfile.route-a-edge",
    ROOT / "deploy" / "Caddyfile.production",
]
COMPOSE_FILES = [
    ROOT / "deploy" / "docker-compose.public-staging.yml",
    ROOT / "deploy" / "docker-compose.public-https-staging.yml",
    ROOT / "deploy" / "docker-compose.production-pilot.yml",
    ROOT / "deploy" / "docker-compose.staging-infra.yml",
]
BUNDLE = ROOT / "tools" / "jiejing_prepare_public_staging_bundle.py"
PATCH_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
API_SERVER = ROOT / "jiejing_saas" / "api_server.py"
ORIGIN_UFW = ROOT / "deploy" / "apply-cloudflare-origin-ufw.sh"
PUBLIC_HTML_FILES = [ROOT / "index.html", ROOT / "app.html"]


NOINDEX = "noindex, nofollow, noarchive, nosnippet, noimageindex"
DEDUP_HEADERS = [
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "X-Robots-Tag",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    robots = _read(ROBOTS)
    for marker in [
        "User-agent: *",
        "Disallow: /",
        "GPTBot",
        "Google-Extended",
        "ClaudeBot",
        "PerplexityBot",
        "AI training",
    ]:
        if marker not in robots:
            return fail(f"robots.txt missing marker: {marker}")

    nginx = _read(NGINX)
    for marker in [
        "location = /robots.txt",
        "location ~* \\.map$",
        "return 404",
        "add_header X-Robots-Tag",
        NOINDEX,
        'add_header Cache-Control "no-store" always',
        "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com https://challenges.cloudflare.com",
        "frame-src https://challenges.cloudflare.com",
        "post-publish",
        "location ~ ^/(?:\\.git|\\.github|deploy|tools|docs|tests|jiejing_saas|jiejing_runtime|schemas|output|private)(?:/|$)",
        "location ~* \\.(?:env|pem|key|sqlite|db|py|pyc|md|ya?ml|toml|ini|log|bak|zip|tar|gz|ps1|sh|conf)$",
    ]:
        if marker not in nginx:
            return fail(f"nginx anti-scrape config missing marker: {marker}")
    for forbidden_csp in ["script-src *", "unsafe-eval"]:
        if forbidden_csp in nginx:
            return fail(f"nginx CSP must not use broad script execution allowance: {forbidden_csp}")

    for path in CADDY_FILES:
        content = _read(path)
        if "X-Robots-Tag" not in content or NOINDEX not in content:
            return fail(f"{path.name} should add the no-index anti-scrape header")
        if "reverse_proxy" in content:
            for header in DEDUP_HEADERS:
                if f"header_down -{header}" not in content:
                    return fail(f"{path.name} should strip upstream duplicate header before edge emits {header}")
        if path.name in {"Caddyfile.public-staging", "Caddyfile.public-staging.systemd", "Caddyfile.production"}:
            for marker in [
                "blockedInternalPath",
                "path /.git* /.github* /deploy* /tools* /docs* /tests* /jiejing_saas* /jiejing_runtime* /schemas* /output* /private*",
                "blockedInternalFile",
                'respond "Not found" 404',
            ]:
                if marker not in content:
                    return fail(f"{path.name} should hard-block internal source paths: {marker}")
        if path.name == "Caddyfile.public-staging.systemd":
            for marker in [
                "jiejing.shop {",
                "redir https://app.jiejing.shop{uri} 308",
                "handle /robots.txt",
                "root * /opt/jiejing-staging/app",
                'header Cache-Control "no-store"',
                "file_server",
            ]:
                if marker not in content:
                    return fail(f"{path.name} should serve robots.txt directly through the stable domain edge: {marker}")
            for marker in [
                "http://43.129.205.244",
                "nip.io",
                "sslip.io",
            ]:
                if marker in content:
                    return fail(f"{path.name} should not serve direct-origin host marker: {marker}")

    for path in COMPOSE_FILES:
        content = _read(path)
        if "../robots.txt:/usr/share/nginx/html/robots.txt:ro" not in content:
            return fail(f"{path.name} should mount robots.txt into the public frontend")

    for path in PUBLIC_HTML_FILES:
        if "static.cloudflareinsights.com/beacon.min.js" in _read(path):
            return fail(f"{path.name} must rely on the Cloudflare edge beacon instead of embedding a duplicate copy")

    bundle = _read(BUNDLE)
    patch_script = _read(PATCH_SCRIPT)
    if "public_staging_patch_whitelist_v1" not in bundle or "_apply_patch_file_list" not in bundle:
        return fail("public staging bundle should derive its file scope from the patch whitelist")
    if '"robots.txt"' not in patch_script:
        return fail("public staging patch whitelist should include robots.txt")

    api = _read(API_SERVER)
    for marker in [
        'self.send_header("cache-control", "no-store")',
        'self.send_header("x-robots-tag",',
        NOINDEX,
    ]:
        if marker not in api:
            return fail(f"backend API responses should carry anti-index/cache headers: {marker}")

    origin_ufw = _read(ORIGIN_UFW)
    for marker in [
        "https://www.cloudflare.com/ips-v4",
        "https://www.cloudflare.com/ips-v6",
        "ufw default deny incoming",
        "ufw default allow outgoing",
        "existing_direct_web_denies",
        "existing_ops_public_allows",
        "ufw --force delete",
        "JIEJING_SSH_PORTS:-22 2222",
        "JIEJING_WEB_PORTS:-80 443",
        "JIEJING_OPS_PUBLIC_IPV4_RANGES:-0.0.0.0/1 128.0.0.0/1",
        'read -r cidr || [[ -n "$cidr" ]]',
        "Jiejing Cloudflare web",
        "Jiejing ops ACME HTTP IPv4",
        "Jiejing ops public TLS IPv4",
        "Jiejing deny direct origin web",
        "ufw --force enable",
    ]:
        if marker not in origin_ufw:
            return fail(f"origin UFW lock script missing marker: {marker}")

    print("PASS jiejing_public_anti_scrape_hardening")
    return 0


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
