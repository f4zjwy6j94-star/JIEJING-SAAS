# Jiejing GitHub / CI Status - 2026-06-17

## Current State

- Local git repository initialized on branch `main`.
- `.github/workflows/jiejing-ci.yml` added.
- `tools/jiejing_secret_scan.py` added and verified locally.
- `.gitignore` and `.dockerignore` now exclude local caches, output artifacts, portable tools, env files, private keys and secret directories.
- `python tools/jiejing_secret_scan.py` passes without printing sensitive values.

## Remote Status

The current Codex environment can read/update files in an existing GitHub repository through the GitHub connector, but it does not expose a repository-creation tool. The local machine also does not have the `gh` CLI installed.

To finish the remote private GitHub setup, create an empty private repository such as `jiejing-saas` under the intended GitHub owner, then the local repository can be connected and pushed:

```powershell
git remote add origin https://github.com/<owner>/jiejing-saas.git
git push -u origin main
```

Do not push until `python tools/jiejing_secret_scan.py` passes.

## CI Scope

The CI gate runs:

- no-secret-output secret scan
- Python compile checks for core SaaS backend modules
- `node --check app.js`
- queue/operational health regressions
- Postgres durable queue and infra readiness regressions
- frontend staging/session/settings contract tests

The CI does not require production eBay, model, billing, Vault, Tencent Cloud or database secrets.

## Boundary

No passwords, refresh tokens, model keys, eBay tokens, Tencent credentials or provider secrets should ever be committed. Filled env files remain ignored; only `.env.example` templates can be tracked.
