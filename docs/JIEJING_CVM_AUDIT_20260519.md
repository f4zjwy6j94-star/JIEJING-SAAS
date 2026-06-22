# Jiejing CVM Audit 2026-05-19

## Scope

- Target instance: `ins-01hsr6ti`
- Public IP: `159.75.102.10`
- Private IP: `172.16.0.4`
- Region/zone: Guangzhou / Guangzhou Zone 6
- System disk: `disk-fmmjj0o6`, 50 GiB
- Mode: read-only audit after snapshot protection
- Boundary: no eBay OAuth repeat, no eBay sync repeat, no real platform writes

## Snapshot Evidence

- Created snapshot: `snap-rq3ysy51`
- Snapshot name: `jiejing-cvm-preaudit-ins-01hsr6ti-20260519`
- Associated disk: `disk-fmmjj0o6`
- Associated instance: `ins-01hsr6ti`
- Console verification time: 2026-05-19 15:11 CST
- Console state at verification: created successfully, data upload in progress

Do not delete this snapshot before the CVM retirement decision is finished. Before stopping or releasing the CVM, re-check that the snapshot is in a normal/available state.

## Key Findings

This CVM is not the current Jiejing SaaS staging host.

Evidence:

- Current Jiejing staging host remains the Lighthouse host `42.194.158.47`.
- This CVM exposes only SSH externally on port 22.
- No `nginx`, `cloudflared`, `postgres`, `redis`, `mysql`, `node`, `gunicorn`, `uvicorn`, or `jiejing` process was found.
- Docker is not active and appears not installed/enabled.
- `/opt`, `/srv`, and `/var/www` are effectively empty.
- No Docker compose deployment was found under `/opt`, `/srv`, `/var/www`, `/home/ubuntu`, or `/home/agentuser`.

What is present:

- Ubuntu 24.04.4 LTS, hostname `VM-0-4-ubuntu`.
- A dedicated `agentuser` environment.
- A running Hermes gateway process:
  `/home/agentuser/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace`
- Hermes/OpenClaw directories under `/home/agentuser/.hermes` and `/home/agentuser/.openclaw`.
- Tencent Cloud agent services, including `tat_agent`, `stargate`, and `yunjing` cron files.
- `/home/agentuser/.hermes/.env` exists, but its contents were not read.

## Security Notes

- Console detail showed this CVM has no SSH key bound.
- `/home/ubuntu/.ssh/authorized_keys` and `/root/.ssh/authorized_keys` are empty.
- Access is currently password-based.
- The initial password was exposed during console-assisted login. Rotate the password or bind an SSH key before keeping this instance online.

## Recommendation

Treat `ins-01hsr6ti / 159.75.102.10` as a historical Hermes/OpenClaw agent host, not as a dependency of the current Jiejing SaaS staging stack.

Recommended next sequence:

1. Verify `snap-rq3ysy51` has reached a normal/available state.
2. Rotate the exposed password or bind a controlled SSH key if the instance must remain online.
3. Stop the instance for an observation window.
4. Confirm current Jiejing staging, eBay read-only packet, reports, and public workbench remain unaffected.
5. If no dependency appears, release the CVM before its 2026-05-26 expiry.

## Evidence Files

- `output/jiejing-cvm-audit-20260519/cvm-audit-ins-01hsr6ti-159.75.102.10-20260519.md`
- `output/jiejing-cvm-audit-20260519/cvm-audit-focused-ins-01hsr6ti-20260519.md`
