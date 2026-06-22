#!/usr/bin/env python3
"""Regression test for the Jiejing staging deployment channel doctor."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from jiejing_deploy_channel_doctor import _recommended_actions, classify_ssh_result  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    usable = classify_ssh_result(returncode=0, stdout="remote_app_path=/opt/jiejing-staging/app", stderr="")
    if usable.get("status") != "usable" or usable.get("blocker") is not None:
        return fail("successful SSH should be classified as usable")
    usable_actions = _recommended_actions(usable)
    if "rerun_deploy_channel_doctor_after_server_access_is_fixed" in usable_actions:
        return fail("usable SSH should not recommend fixing already-working server access")
    if "deploy_patch_over_ubuntu_2222_ssh_when_code_changes_are_ready" not in usable_actions:
        return fail("usable SSH should recommend the stable ubuntu 2222 deploy channel")

    qcloud = classify_ssh_result(
        returncode=255,
        stdout="请使用微信扫码安全登录。如果二维码无法正常显示, 建议打开下方URL查看:\nhttps://up.yd.qcloud.com/qr/?m=123",
        stderr="root@42.194.158.47: Permission denied (publickey,password,keyboard-interactive).",
    )
    if qcloud.get("blocker") != "qcloud_security_login_and_ssh_key_rejected":
        return fail("Tencent QR plus permission denied should be classified as the known deploy-channel blocker")
    if qcloud.get("qcloud_security_login_seen") is not True or qcloud.get("permission_denied") is not True:
        return fail("Tencent QR classification should expose precise boolean facts")

    denied = classify_ssh_result(
        returncode=255,
        stdout="",
        stderr="Permission denied (publickey).",
    )
    if denied.get("blocker") != "ssh_key_rejected":
        return fail("plain permission denied should be classified as key rejection")

    host_key = classify_ssh_result(
        returncode=255,
        stdout="",
        stderr="WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\nPermission denied (publickey,password).",
    )
    if host_key.get("blocker") != "ssh_host_key_changed":
        return fail("host key mismatch should be classified before plain key rejection")

    timeout = classify_ssh_result(
        returncode=255,
        stdout="",
        stderr="ssh: connect to host 42.194.158.47 port 22: Connection timed out",
    )
    if timeout.get("blocker") != "ssh_network_timeout":
        return fail("connection timeout should be classified as network timeout")

    print("PASS jiejing_deploy_channel_doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
