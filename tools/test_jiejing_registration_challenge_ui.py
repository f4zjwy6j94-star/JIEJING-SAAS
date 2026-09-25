#!/usr/bin/env python3
"""Static contract for the merchant registration challenge experience."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]

HOMEPAGE_BEHAVIOR = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('index.html', 'utf8');
const source = html.slice(html.indexOf('let entryChallengeScriptPromise = null;'), html.indexOf('function showEntryLogin()'));
async function scenario(kind) {
  let callbacks, calls = [], tokens = 0, removed = 0, toast = [];
  const config = { required:true, verification_ready:kind!=='missing', site_key:'fixture-public-site', action:'jiejing_register' };
  const api = {
    render: (_, opts) => { callbacks=opts; return 'widget-fixture'; },
    execute: () => { calls.push('execute'); if(kind==='timeout')return; queueMicrotask(()=>{
      if(kind==='provider-error') callbacks['error-callback']();
      else if(kind==='expired') callbacks['expired-callback']();
      else callbacks.callback('synthetic-token-'+(++tokens));
    }); },
    reset: () => {}, remove: () => { removed++; },
  };
  const c = {
    window:{turnstile:api,setTimeout:(fn,ms)=>setTimeout(fn,ms===30000?5:ms),clearTimeout},
    AbortSignal, console,
    document:{ querySelector:()=>({value:'',textContent:'',classList:{toggle(){}}}),
      createElement:()=>({addEventListener(event,fn){this[event]=fn;}, remove(){}}),
      head:{appendChild(script){queueMicrotask(()=>script.error());}} },
    entrySaasApiUrl:p=>p,
    fetch:async (url, opts={})=>{
      calls.push(url);
      if(url==='/auth/challenge-config') {
        if(kind==='network-error')throw new Error('fixture-network');
        return {ok:true,json:async()=>({registration_challenge:config})};
      }
      const body=JSON.parse(opts.body);
      calls.push(body);
      return {ok:kind!=='auth-reject',json:async()=>({platform_trial_activation:{platform_trial_allowed:!!body.trial_activation_challenge?.token}})};
    },
    readEntryAuthCredentials:()=>({email:'new@example.test',password:'synthetic-password',company:''}),
    isValidEntryEmail:()=>true, setEntryAuthPending(){},setEntryAuthStatus(){},
    showToast:m=>toast.push(m),entryAuthErrorMessage:()=> 'fixture-rejected',
    saveEntryAuthSession(){},warmWorkspaceAssets(){},continueAfterLogin:async()=>{},
  };
  if(kind==='script-error') c.window.turnstile=null;
  vm.createContext(c);vm.runInContext(source,c);
  if(kind==='duplicate')await Promise.all([c.submitEntryAuth('register'),c.submitEntryAuth('register')]);
  else await c.submitEntryAuth(kind==='login'?'login':'register');
  let bodies=calls.filter(x=>typeof x==='object');assert.equal(bodies.length,1);
  assert.equal(c.window.__jiejingEntryAuthPending,false);
  if(kind==='login') {assert(!calls.includes('/auth/challenge-config'));assert(!('trial_activation_challenge' in bodies[0]));}
  else if(['missing','network-error','script-error','provider-error','expired','timeout'].includes(kind)) {
    assert.equal(bodies[0].trial_activation_challenge.token,'');
    assert(toast.some(x=>x.includes('体验额度未激活')));
  } else {
    assert.equal(bodies[0].trial_activation_challenge.token,'synthetic-token-1');
    assert.equal(bodies[0].trial_activation_challenge.action,'jiejing_register');
    assert(calls.indexOf('execute')<calls.indexOf('/auth/register'));
    assert.equal(removed,1);
  }
  if(kind==='auth-reject') {
    await c.submitEntryAuth('register');bodies=calls.filter(x=>typeof x==='object');
    assert.equal(bodies[1].trial_activation_challenge.token,'synthetic-token-2');
    assert.equal(removed,2);
  }
}
(async()=>{for(const kind of ['success','duplicate','login','missing','network-error','script-error','provider-error','expired','timeout','auth-reject'])await scenario(kind);console.log('PASS homepage registration behavior 10/10');})().catch(()=>{console.error('FAIL homepage registration behavior');process.exitCode=1;});
'''


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    homepage = (ROOT / "index.html").read_text(encoding="utf-8")
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
        if marker not in homepage:
            return fail(f"homepage registration omits challenge contract: {marker}")
    if 'id="entryChallengeWidget"' not in homepage:
        return fail("homepage registration needs an accessible challenge container")

    if "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com https://challenges.cloudflare.com" not in nginx:
        return fail("CSP must allow the official challenge script origin")
    if "frame-src https://challenges.cloudflare.com" not in nginx:
        return fail("CSP must allow only the official challenge frame origin")

    public_text = f"{app_html}\n{app_js}\n{homepage}"
    for forbidden in ("JIEJING_TURNSTILE_SECRET_KEY", "test-secret", "cf-turnstile-secret"):
        if forbidden in public_text:
            return fail(f"frontend leaked a backend verification secret marker: {forbidden}")

    behavior = subprocess.run(["node", "-e", HOMEPAGE_BEHAVIOR], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if behavior.returncode:
        return fail("homepage registration behavior regression")
    print(behavior.stdout.strip())
    print("PASS jiejing_registration_challenge_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
