#!/usr/bin/env python3
"""Validate stable Tencent Cloud deployment-channel scripts stay safe."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "deploy" / "tencentcloud-install-jiejing-ssh-key.sh"
DEPLOY_TOOL = ROOT / "tools" / "jiejing_staging_deploy.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8") if BOOTSTRAP.exists() else ""
    deploy_tool = DEPLOY_TOOL.read_text(encoding="utf-8") if DEPLOY_TOOL.exists() else ""
    required_bootstrap = [
        "JIEJING_SSH_KEY_INSTALLED=1",
        "authorized_keys",
        "PubkeyAuthentication yes",
        "jiejing-deploy",
        "sshd -t",
    ]
    required_deploy = [
        "jiejing_deploy_channel_doctor.py",
        'default="ubuntu"',
        "43.129.205.244",
        '"-T"',
        '"LogLevel=ERROR"',
        "deploy_channel_ready",
        "scp",
        "--transfer-mode",
        "ssh-stdin",
        "cat >",
        "BatchMode=yes",
        "sudo -n JIEJING_APP_DIR=",
        "apply-staging-patch.sh",
        "--remote-temp-keep",
        "REMOTE_TMP_CLEANUP_ARTIFACTS_BEFORE",
        "/tmp/jiejing-public-staging-*",
        "secret_exposed",
    ]
    missing = [marker for marker in required_bootstrap if marker not in bootstrap]
    missing += [marker for marker in required_deploy if marker not in deploy_tool]
    if missing:
        return fail("stable deploy channel contract missing markers: " + ",".join(missing))
    forbidden = [
        "rm -rf /",
        "docker compose down -v",
        "docker volume rm",
        "DROP DATABASE",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        'default="root"',
    ]
    present = [marker for marker in forbidden if marker in bootstrap or marker in deploy_tool]
    if present:
        return fail("stable deploy channel contains forbidden marker: " + ",".join(present))
    print("PASS jiejing_staging_deploy_channel_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
