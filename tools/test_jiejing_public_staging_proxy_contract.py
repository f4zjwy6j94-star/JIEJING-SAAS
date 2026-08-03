#!/usr/bin/env python3
"""Static contract checks for the public staging reverse proxy profile."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF = ROOT / "deploy" / "nginx.public-staging.conf"
COMPOSE_FILE = ROOT / "deploy" / "docker-compose.public-staging.yml"


def main() -> int:
    nginx = _read(NGINX_CONF)
    compose = _read(COMPOSE_FILE)

    _assert_contains(nginx, "proxy_pass http://jiejing-saas:8788", "backend proxy target")
    _assert_contains(nginx, "try_files $uri $uri/ /index.html", "SPA fallback")
    _assert_contains(nginx, 'if ($arg_start != "app")', "bare app.html redirect guard")
    _assert_contains(nginx, "return 302 https://$host/index.html?source=direct_app_entry&start=site", "bare app.html HTTPS redirect target")
    _assert_contains(nginx, "43\\.129\\.205\\.244", "HK public IP host allowlist")
    for header in [
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "X-Robots-Tag",
    ]:
        _assert_contains(nginx, header, f"security header {header}")
    for marker in [
        "location = /robots.txt",
        "noindex, nofollow, noarchive, nosnippet, noimageindex",
        "location ~* \\.map$",
        "return 404",
        "../robots.txt:/usr/share/nginx/html/robots.txt:ro",
    ]:
        _assert_contains(nginx + compose, marker, f"anti-scrape marker {marker}")
    for route in [
        "/health",
        "/infrastructure",
        "/oauth",
        "/auth",
        "/owner",
        "/stores",
        "/secret-refs",
        "/connections",
        "/backup",
        "/billing",
        "/model",
        "/commercial",
        "/ebay-read-only",
        "/controlled-bridges",
        "/data-packets",
        "/ai-ceo",
        "/media-asset-jobs",
        "/confirmations",
        "/workers",
        "/webhooks",
    ]:
        _assert_contains(nginx, route.lstrip("/"), f"proxied API route {route}")

    _assert_contains(compose, "jiejing-saas:", "backend service")
    _assert_contains(compose, "jiejing-frontend:", "frontend service")
    _assert_contains(compose, "jiejing-vault:", "vault service")
    _assert_contains(compose, "nginx:1.27-alpine", "nginx image")
    _assert_contains(compose, "vault.public-staging.hcl", "persistent Vault config mount")
    _assert_contains(compose, "jiejing_public_staging_vault_data", "persistent Vault data volume")
    _assert_contains(compose, "jiejing-saas.staging-oauth.env", "private staging env file")
    _assert_contains(compose, "JIEJING_PUBLIC_HTTP_PORT", "public frontend port override")
    _assert_contains(compose, "../index.html:/usr/share/nginx/html/index.html:ro", "index mount")
    _assert_contains(compose, "../app.html:/usr/share/nginx/html/app.html:ro", "workbench app mount")
    _assert_contains(compose, "../app.js:/usr/share/nginx/html/app.js:ro", "app mount")
    _assert_contains(compose, "../styles.css:/usr/share/nginx/html/styles.css:ro", "styles mount")
    _assert_contains(compose, "../favicon.ico:/usr/share/nginx/html/favicon.ico:ro", "favicon mount")
    _assert_contains(compose, "../assets:/usr/share/nginx/html/assets:ro", "assets mount")
    _assert_contains(compose, "./nginx.public-staging.conf:/etc/nginx/conf.d/default.conf:ro", "nginx config mount")
    if "8788:8788" in compose:
        raise AssertionError("public staging profile must not expose backend port 8788 directly")
    if "vault server -dev" in compose:
        raise AssertionError("public staging profile must not use in-memory Vault dev mode")

    server_blocks = nginx.split("server {")
    if len(server_blocks) != 3:
        raise AssertionError("public staging nginx must keep exactly isolated ops and app server blocks")
    ops_server = server_blocks[1]
    app_server = server_blocks[2]
    for route, allowed_method in (
        ("/owner/operations/feedback", "GET"),
        ("/owner/product-feedback/review", "POST"),
        ("/owner/product-feedback/resolve", "POST"),
    ):
        ops_location = _exact_location_block(ops_server, route)
        if f"$request_method != {allowed_method}" not in ops_location or "return 405" not in ops_location or "proxy_pass http://jiejing-saas:8788" not in ops_location:
            raise AssertionError(f"ops host method contract is wrong for {route}")
        app_location = _exact_location_block(app_server, route)
        if "return 404" not in app_location or "proxy_pass" in app_location:
            raise AssertionError(f"app host must deny every method without proxying for {route}")

    print("PUBLIC_STAGING_PROXY_CONTRACT=pass")
    return 0


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def _assert_contains(content: str, needle: str, label: str) -> None:
    if needle not in content:
        raise AssertionError(f"missing {label}: {needle}")


def _exact_location_block(server_block: str, route: str) -> str:
    marker = f"location = {route}"
    start = server_block.find(marker)
    if start < 0:
        raise AssertionError(f"missing exact location: {route}")
    next_location = server_block.find("\n    location ", start + len(marker))
    return server_block[start : next_location if next_location >= 0 else len(server_block)]


if __name__ == "__main__":
    raise SystemExit(main())
