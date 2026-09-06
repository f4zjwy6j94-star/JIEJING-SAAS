#!/usr/bin/env python3
"""Unit contract for the seven-day platform-funded AI trial window."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.repository import SaaSRepository


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def assert_merchant_trial_display() -> None:
    """Replay backend quota packets through the real settings state and renderer."""
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app.js', 'utf8');
const names = ['isSaasMerchantModelConfigured', 'isSaasPlatformTrialModelAvailable',
  'isSaasModelConfigured', 'saasPlatformTrialModelState', 'saasPrimaryTextAiState',
  'renderSaasMerchantModelProviderPanel'];
const functions = names.map((name) => {
  const start = source.indexOf(`function ${name}(`);
  assert(start >= 0, `missing real settings function ${name}`);
  return source.slice(start, source.indexOf('\nfunction ', start + 1));
}).join('\n');
const base = {contract_version:'seven_day_trial', trial_limit:20, used:0, remaining:20,
  allowed:true, activation_status:'active', platform_trial_activated:true, trial_expired:false};
const cases = [
  ['expired_unused', {...base,allowed:false,trial_expired:true,blocked_by:'platform_default_model_trial_expired'}, false, '到期', false],
  ['expired_empty', {...base,allowed:false,remaining:0,used:20,trial_expired:true,blocked_by:'platform_default_model_trial_expired'}, false, '到期', false],
  ['inactive', {...base,allowed:false,platform_trial_activated:false,activation_status:'verification_required',blocked_by:'platform_trial_activation_required'}, false, '未激活', false],
  ['blocked_unused', {...base,allowed:false,blocked_by:'platform_model_unavailable'}, false, '暂不可用', false],
  ['unknown', {...base,allowed:undefined}, false, '待确认', false],
  ['missing_quota', {}, false, '待确认', false],
  ['exhausted', {...base,allowed:false,remaining:0,used:20,blocked_by:'platform_default_model_trial_exhausted'}, false, '用完', false],
  ['active', base, false, '可用', true],
  ['byok_expired', {...base,allowed:false,trial_expired:true,blocked_by:'platform_default_model_trial_expired'}, true, '账号 AI', true],
];
for (const [name,quota,byok,label,available] of cases) {
  const context = {
    state:{saasModelSettings:{configured:byok,platform_trial_quota:quota},
      saasModelValueGate:{platform_default_model:{configured:true,enabled:true}}},
    saasActiveModelSecretRef:()=>null, saasModelSecretRefReady:()=>false,
    saasModelProviderRows:()=>[], escapeHtml:(value)=>String(value ?? ''),
    saasImageRecognitionState:()=>({tone:'amber'}),saasPublicSearchState:()=>({tone:'amber'}),
    saasMediaGenerationState:()=>({tone:'amber'}),saasModelConnectionAttemptState:()=>({state:'save_failed'}),
  };
  vm.createContext(context); vm.runInContext(functions,context);
  const trial=vm.runInContext('saasPlatformTrialModelState()',context);
  const text=vm.runInContext('saasPrimaryTextAiState()',context);
  const html=vm.runInContext('renderSaasMerchantModelProviderPanel({store:{},hasPacket:true})',context);
  assert.equal(vm.runInContext('isSaasModelConfigured()',context),available,name);
  assert.equal(text.configured,available,name);
  assert(text.title.includes(label),`${name}: ${text.title}`);
  assert.equal(text.tone,available?'green':'amber',name);
  const card=html.match(/<article[^>]*data-ai-media-capability="text_analysis"[\s\S]*?<\/article>/)[0];
  assert(card.includes(label),name);
  if (!available) {
    assert(!trial.quotaLabel.includes('次可用'),name);
    assert(!card.includes('is-green'),name);
    assert(!html.includes('可先试用，再连接账号自己的 AI'),name);
    assert(/data-saas-action="run-model-value-rehearsal" disabled/.test(html),name);
  }
  if (name==='expired_unused') {
    assert(!trial.guardrailDetail.includes('额度已用完'),name);
    assert(trial.guardrailDetail.includes('到期'),name);
    assert.equal(trial.remaining,20,'display must not rewrite remaining quota');
  }
  if (byok) assert.equal(trial.allowed,false,'BYOK must not reactivate platform trial');
}
const attemptStart=source.indexOf('function saasModelConnectionAttemptState(');
const attemptContext={state:{saasModelSettings:{configured:false,connection_state:'save_failed',latest_attempt:{
  created_at:'2026-07-03T00:00:00Z',status:'store_blocked',verification_status:'failed',verification_error_code:'model_secret_resolve_blocked',
}}},saasModelBlockedReasonText:()=> '系统暂时无法核对当前账号的 AI 连接状态。'};
vm.createContext(attemptContext);
vm.runInContext(source.slice(attemptStart,source.indexOf('\nfunction ',attemptStart+1)),attemptContext);
const attempt=vm.runInContext('saasModelConnectionAttemptState()',attemptContext);
assert(attempt.title.includes('尚无可用'), 'old saved failure is not a new save attempt');
assert(attempt.detail.includes('上次') && !attempt.detail.includes('系统暂时'), 'old failure is not a current GET failure');
assert.equal(attempt.accountDefault,false);
assert.equal(attempt.requiresReentry,true);
console.log('PASS merchant_trial_display 10 cases');
"""
    result = subprocess.run(["node", "-"], input=script, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise AssertionError(result.stderr.strip())


def main() -> int:
    assert_merchant_trial_display()
    old_limit = os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT")
    old_days = os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS")
    os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = "1"
    os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS"] = "7"
    try:
        with tempfile.TemporaryDirectory(prefix="jiejing-trial-window-", ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "trial.sqlite"
            repository = SaaSRepository(db_path)
            repository.initialize()
            repository.upsert_platform_trial_activation(
                company_id="company-trial-window",
                user_id="user-trial-window",
                status="active",
                platform_trial_allowed=True,
                welcome_media_points_granted=0,
                requires_challenge=True,
                challenge_attested=True,
                decision_reason="unit_test",
            )

            handler = object.__new__(SaaSBackendHandler)
            handler.repository = repository
            active = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if active.get("allowed") is not True or active.get("trial_limit") != 1:
                return fail(f"fresh seven-day trial should be active with one request: {active}")
            if active.get("trial_duration_days") != 7 or active.get("trial_expired") is not False:
                return fail(f"fresh trial should expose the seven-day window: {active}")

            first_started_at = active.get("trial_started_at")
            reservation = handler._reserve_platform_model_trial(
                identity={"company_id": "company-trial-window"},
                route_scope="listing_draft_generation",
            )
            if reservation.get("allowed") is not True:
                return fail(f"fresh trial should reserve its only request: {reservation}")

            repository.upsert_platform_trial_activation(
                company_id="company-trial-window",
                user_id="user-trial-window",
                status="active",
                platform_trial_allowed=True,
                welcome_media_points_granted=0,
                requires_challenge=True,
                challenge_attested=True,
                decision_reason="unit_test_repeated_active_decision",
            )
            repeated = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if repeated.get("trial_started_at") != first_started_at:
                return fail(f"repeated active decision must preserve the first trial start: {repeated}")
            if repeated.get("used") != 1 or repeated.get("remaining") != 0 or repeated.get("allowed") is not False:
                return fail(f"repeated active decision must not refill an exhausted trial: {repeated}")

            activation = repository.get_platform_trial_activation(company_id="company-trial-window") or {}
            expired_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            activation["activated_at"] = expired_at
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "update platform_trial_activations set activated_at = ?, activation_json = ? where company_id = ?",
                    (expired_at, json.dumps(activation, ensure_ascii=False), "company-trial-window"),
                )

            expired = handler._platform_model_trial_quota(identity={"company_id": "company-trial-window"})
            if expired.get("allowed") is not False or expired.get("trial_expired") is not True:
                return fail(f"trial older than seven days must be blocked: {expired}")
            if expired.get("blocked_by") != "platform_default_model_trial_expired":
                return fail(f"expired trial should expose the value-free expiry reason: {expired}")
            if expired.get("merchant_byok_unaffected") is not True:
                return fail(f"trial expiry must not block merchant BYOK: {expired}")
    finally:
        if old_limit is None:
            os.environ.pop("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT", None)
        else:
            os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = old_limit
        if old_days is None:
            os.environ.pop("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS", None)
        else:
            os.environ["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_DURATION_DAYS"] = old_days

    print("PASS jiejing_platform_trial_window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
