#!/usr/bin/env python3
"""Static contract for the merchant registration challenge experience."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")

    for marker in ('id="authChallengeShell"', 'id="authChallengeWidget"', 'id="authChallengeStatus"'):
        if marker not in app_html:
            return fail(f"registration modal is missing challenge UI marker: {marker}")
    if 'id="authChallengeWidget" aria-hidden="true"' in app_html:
        return fail("interactive registration challenge widget must remain available to assistive technology")

    required_js = (
        "/auth/challenge-config",
        "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit",
        "turnstile.render",
        'appearance: "interaction-only"',
        'execution: "execute"',
        "turnstile.execute",
        "turnstile.reset",
        "trial_activation_challenge",
        "platform_trial_activation",
    )
    for marker in required_js:
        if marker not in app_js:
            return fail(f"registration challenge client contract is missing: {marker}")

    if "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com https://challenges.cloudflare.com" not in nginx:
        return fail("CSP must allow the official challenge script origin")
    if "frame-src https://challenges.cloudflare.com" not in nginx:
        return fail("CSP must allow only the official challenge frame origin")

    public_text = f"{app_html}\n{app_js}"
    for forbidden in ("JIEJING_TURNSTILE_SECRET_KEY", "test-secret", "cf-turnstile-secret"):
        if forbidden in public_text:
            return fail(f"frontend leaked a backend verification secret marker: {forbidden}")

    print("PASS jiejing_registration_challenge_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
