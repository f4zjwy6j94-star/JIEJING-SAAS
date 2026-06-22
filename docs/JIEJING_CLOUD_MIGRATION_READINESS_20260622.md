# JIEJING Cloud Migration Readiness - 2026-06-22

This note records the current local-to-cloud migration state for JIEJING.
It is a preparation checklist only. It does not mean production billing or live
eBay execution is ready.

## Current Conclusion

JIEJING is ready for the next safe step: create a private GitHub repository and
push the source tree after the existing secret scan passes.

Do not upload local build outputs, deployment bundles, filled env files,
databases, logs, private keys, or third-party reference repositories.

## Checked Today

- Secret scan passed: `python tools/jiejing_secret_scan.py`.
- GitHub CI file exists: `.github/workflows/jiejing-ci.yml`.
- Upload candidate size after ignore rules: about 489 files / 93.51 MB.
- No upload candidate is above 50 MB or 100 MB.
- Largest valid upload candidates are frontend/media assets; no Git LFS is
  required for the current tree.
- Local `output/` is about 23 GB, but it is ignored and must not be pushed.
- `external_references/`, browser test output, cache folders, env files,
  private key formats, local databases, logs, and generated artifacts are
  ignored.
- Archive and database dump patterns were added to `.gitignore` and
  `.codexignore` to reduce future accidental uploads.

## Cost-Safe Direction

Use this order:

1. Private GitHub repository for source control.
2. Codex Cloud connected to that private repository for phone/tablet work.
3. Existing Tencent Cloud server remains the runtime target.
4. Cloud deployment automation is added later, after the repository and CI are
   verified.

This avoids paying for a second always-on development server just to run Codex.
The main extra cost is the user's existing ChatGPT/Codex plan and any usage
limits attached to it. GitHub private source storage should be small for this
repo because the 23 GB local output folder is ignored.

Official references checked:

- OpenAI Codex with ChatGPT plan:
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- GitHub pricing:
  https://github.com/pricing
- GitHub Actions billing:
  https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions
- GitHub large-file guidance:
  https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github

## Deployment Direction

Current deployment still depends on a local SSH path and a local private deploy
key. That private key must not be committed.

For a no-local-PC workflow later, prefer one of these:

- GitHub Actions with a restricted deployment key and minimal secrets.
- A GitHub self-hosted runner on the Tencent Cloud server, so deployment runs
  from the server side instead of from the user's PC.

The self-hosted runner route is usually cleaner for this project because the
server can pull the verified private repo without opening broad SSH access to
random cloud runner IPs.

## Must Not Move Into Git

- `.env`, `*.env`, filled files under `deploy/`.
- Any eBay token, refresh token, Stripe secret, model key, Tencent secret, API
  key, client secret, SSH private key, certificate key, or Vault material.
- `output/`, deployment bundles, logs, databases, and test artifacts.
- `external_references/` and other third-party cloned repositories.

## Next User Actions

1. Create an empty private GitHub repository, for example `jiejing-saas`.
2. Do not add a public README, license, demo secrets, or env files in GitHub.
3. Send the repository URL to Codex.
4. After push, verify GitHub CI and only then connect Codex Cloud to the repo.

## Current Blockers For Public Paid Launch

These are unchanged by the cloud migration:

- Stripe live provider or an alternative payment provider is not finalized.
- New eBay account live validation is not complete.
- eBay token refresh success proof is still not ready.
- Production public launch and real paid customer onboarding remain blocked
  until the external account/payment pieces are resolved.
