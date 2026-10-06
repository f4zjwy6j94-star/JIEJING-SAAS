from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "jiejing_deploy_ops_staging_with_key.ps1"


def main() -> int:
    if not SCRIPT.exists():
        raise AssertionError("ops staging deploy script is missing")

    text = SCRIPT.read_text(encoding="utf-8")
    required = (
        "ops.html",
        "ops.css",
        "ops.js",
        "assets/jiejing-ops-panels.js",
        "deploy/nginx.public-staging.conf",
        "StrictHostKeyChecking=yes",
        "UserKnownHostsFile=",
        "docker run --rm --network deploy_default",
        "nginx -t",
        "rollback_applied=1",
        "DEPLOY_OPS_ROLLBACK_APPLIED=%s",
        "DEPLOY_OPS_STATUS=ok",
        "app_ops_status",
        'test "$app_ops_status" = "404"',
        "jiejing-ops-panels.js",
        "20260828-ops-performance-v2",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise AssertionError("ops staging deploy contract missing: " + ", ".join(missing))

    forbidden = (
        "docker compose down",
        "docker system prune",
        "rm -rf /opt/jiejing-staging",
        "ufw ",
        "iptables",
        "production-compose.env",
    )
    present = [marker for marker in forbidden if marker in text]
    if present:
        raise AssertionError("ops staging deploy contains broad/destructive action: " + ", ".join(present))

    print("PASS jiejing_ops_staging_deploy_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
