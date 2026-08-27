#!/usr/bin/env python3
"""Functional security and data-contract test for the independent operations console."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402

OUT = ROOT / "output" / "jiejing-operations-console-test"
PORT = 8867
ADMIN_EMAIL = "ops-owner@jiejing-shop.cn"
MERCHANT_EMAIL = "ordinary-merchant@jiejing-shop.cn"
SYNTHETIC_EMAIL = "synthetic-feedback@jiejing-shop.cn"
PASSWORD = "operations-console-test-password"
OPS_HOST = "ops.jiejing.shop"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _sanitized_backend_env() -> dict[str, str]:
    inherited = {"COMSPEC", "LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
    env = {name: value for name in inherited if (value := os.environ.get(name)) is not None}
    env.update(
        {
            "JIEJING_INTERNAL_ADMIN_EMAILS": ADMIN_EMAIL,
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_SAAS_SESSION_SECRET": "operations-console-tests-only-not-a-production-secret",
            "JIEJING_DATABASE_ENGINE": "sqlite",
            "JIEJING_DATABASE_ADAPTER": "sqlite-local",
            "JIEJING_QUEUE_PROVIDER": "local_worker",
            "JIEJING_VAULT_PROVIDER": "secret_ref_only",
            "JIEJING_VAULT_ENABLED": "false",
            "JIEJING_EXECUTION_ADAPTER": "demo_no_platform_write",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "false",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "false",
            "JIEJING_EBAY_READ_ONLY_LIVE": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_ALLOW_HERMES_ADAPTERS": "false",
            "JIEJING_MODEL_DISABLE_LIVE": "true",
            "JIEJING_PUBLIC_SEARCH_LIVE": "false",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "saas.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    env = _sanitized_backend_env()
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(db),
            "--runtime-db",
            str(runtime_db),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        base = f"http://127.0.0.1:{PORT}"
        _wait_for_health(base)
        merchant = _post_json(
            f"{base}/auth/register",
            {"email": MERCHANT_EMAIL, "password": PASSWORD, "company_name": "Ordinary Merchant"},
        )
        admin = _post_json(
            f"{base}/auth/register",
            {"email": ADMIN_EMAIL, "password": PASSWORD, "company_name": "Jiejing Operations"},
        )
        synthetic = _post_json(
            f"{base}/auth/register",
            {"email": SYNTHETIC_EMAIL, "password": PASSWORD, "company_name": "Synthetic Feedback"},
        )
        merchant_token = str(merchant["body"].get("token") or "")
        admin_token = str(admin["body"].get("token") or "")
        synthetic_token = str(synthetic["body"].get("token") or "")
        if not merchant_token or not admin_token or not synthetic_token:
            return fail("registration did not create test sessions")

        with sqlite3.connect(db) as conn:
            conn.execute(
                "update users set account_classification = 'synthetic_test' where email = ?",
                (SYNTHETIC_EMAIL,),
            )

        real_feedback = _post_json(
            f"{base}/product-feedback",
            {
                "idempotency_key": "ops-real-feedback-001",
                "feedback_type": "product_improvement",
                "module_key": "workflow",
                "reason": "unclear",
                "stage_title": "<b>确认经营步骤</b>",
                "detail": "<img src=x onerror=window.__opsXss=1>这里的下一步不够清楚。",
            },
            token=merchant_token,
        )
        synthetic_feedback = _post_json(
            f"{base}/product-feedback",
            {
                "idempotency_key": "ops-synthetic-feedback-001",
                "feedback_type": "product_improvement",
                "module_key": "media",
                "reason": "wrong_result",
                "stage_title": "自动化测试反馈",
                "detail": "这条 synthetic-test 记录不得计入真实经营聚合。",
            },
            token=synthetic_token,
        )
        if real_feedback["status"] != 201 or synthetic_feedback["status"] != 201:
            return fail(f"feedback fixtures were not persisted: {real_feedback}, {synthetic_feedback}")

        repository = SaaSRepository(db)
        with repository._connect() as conn:
            merchant_user_id = str(conn.execute("select user_id from users where email = ?", (MERCHANT_EMAIL,)).fetchone()["user_id"])
            admin_user_id = str(conn.execute("select user_id from users where email = ?", (ADMIN_EMAIL,)).fetchone()["user_id"])
            shared_company_id = "company_ops_shared_membership"
            created_at = datetime.now(timezone.utc).astimezone().isoformat()
            conn.execute(
                "insert into companies (company_id, name, created_at) values (?, ?, ?)",
                (shared_company_id, "Shared Merchant Company", created_at),
            )
            conn.execute(
                "insert into team_members (company_id, user_id, role, created_at) values (?, ?, ?, ?)",
                (shared_company_id, admin_user_id, "owner", created_at),
            )
        try:
            repository.create_product_feedback(
                company_id=shared_company_id,
                user_id=merchant_user_id,
                idempotency_key="ops-nonmember-feedback-must-fail",
                payload={
                    "feedback_type": "product_improvement",
                    "module_key": "service",
                    "reason": "missing_action",
                    "stage_title": "非成员反馈",
                    "detail": "非成员不得写入其他公司。",
                },
            )
        except KeyError:
            pass
        else:
            return fail("non-member product feedback crossed the company boundary")
        with repository._connect() as conn:
            conn.execute(
                "insert into team_members (company_id, user_id, role, created_at) values (?, ?, ?, ?)",
                (shared_company_id, merchant_user_id, "operator", created_at),
            )
        shared_feedback = repository.create_product_feedback(
            company_id=shared_company_id,
            user_id=merchant_user_id,
            idempotency_key="ops-shared-member-feedback-001",
            payload={
                "feedback_type": "product_improvement",
                "module_key": "service",
                "reason": "missing_action",
                "stage_title": "客服与物流步骤",
                "detail": "这里还缺一个适合新手的下一步动作。",
            },
        )
        with repository._connect() as conn:
            conn.execute(
                "delete from team_members where company_id = ? and user_id = ?",
                (shared_company_id, merchant_user_id),
            )
        if shared_feedback.get("status") != "open":
            return fail(f"shared-company feedback was not created: {shared_feedback}")

        unauthenticated = _get_json(f"{base}/owner/operations-overview", host=OPS_HOST)
        if unauthenticated["status"] != 401:
            return fail(f"unauthenticated overview should be 401: {unauthenticated}")

        merchant_overview = _get_json(f"{base}/owner/operations-overview", token=merchant_token, host=OPS_HOST)
        merchant_details = [
            _get_json(f"{base}/owner/operations/{section}", token=merchant_token, host=OPS_HOST)
            for section in ("traffic", "merchants", "transactions", "costs", "workflows", "audit", "feedback")
        ]
        if merchant_overview["status"] != 403 or any(item["status"] != 403 for item in merchant_details):
            return fail("ordinary merchant accessed internal operations data")

        merchant_ops_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": MERCHANT_EMAIL, "password": PASSWORD},
            host=OPS_HOST,
        )
        if merchant_ops_login["status"] != 403 or merchant_ops_login["headers"].get("set-cookie"):
            return fail(f"ordinary merchant received an operations session: {merchant_ops_login}")

        admin_app_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": ADMIN_EMAIL, "password": PASSWORD},
            host="app.jiejing.shop",
        )
        admin_local_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": ADMIN_EMAIL, "password": PASSWORD},
        )
        if (
            admin_app_login["status"] != 403
            or admin_local_login["status"] != 403
            or admin_app_login["headers"].get("set-cookie")
            or admin_local_login["headers"].get("set-cookie")
        ):
            return fail(
                "operations login did not fail closed outside ops host: "
                f"app={admin_app_login}, local={admin_local_login}"
            )

        admin_ops_login = _post_json(
            f"{base}/owner/auth/login",
            {"email": ADMIN_EMAIL, "password": PASSWORD},
            host=OPS_HOST,
        )
        admin_login_body = admin_ops_login["body"]
        admin_cookie = str(admin_ops_login["headers"].get("set-cookie") or "")
        if admin_ops_login["status"] != 200:
            return fail(f"internal admin login failed: {admin_ops_login}")
        if "token" in admin_login_body or admin_login_body.get("token_returned_to_frontend") is not False:
            return fail(f"operations login exposed bearer token: {admin_login_body}")
        if "HttpOnly" not in admin_cookie or "SameSite=Strict" not in admin_cookie:
            return fail(f"operations session cookie is not strict and HttpOnly: {admin_cookie}")

        app_host_overview = _get_json(
            f"{base}/owner/operations-overview?period_days=7",
            token=admin_token,
            host="app.jiejing.shop",
        )
        localhost_overview = _get_json(f"{base}/owner/operations-overview?period_days=7", token=admin_token)
        if app_host_overview["status"] != 403 or localhost_overview["status"] != 403:
            return fail(
                f"internal admin escaped the operations host boundary: app={app_host_overview}, local={localhost_overview}"
            )

        overview_response = _get_json(
            f"{base}/owner/operations-overview?period_days=7",
            token=admin_token,
            host=OPS_HOST,
        )
        if overview_response["status"] != 200:
            return fail(f"internal overview failed: {overview_response}")
        overview = overview_response["body"].get("operations_overview") or {}
        if overview.get("period", {}).get("days") != 7 or overview.get("audience") != "platform_internal_admin":
            return fail(f"overview period or audience is wrong: {overview}")
        if overview.get("merchant_navigation_visible") is not False or overview.get("secret_exposed") is not False:
            return fail("overview crossed merchant or secret boundary")
        feedback_summary = overview.get("product_feedback") or {}
        if feedback_summary.get("total") != 2 or feedback_summary.get("open") != 2:
            return fail(f"real merchant feedback aggregation is wrong: {feedback_summary}")
        if feedback_summary.get("reviewing") != 0 or feedback_summary.get("resolved") != 0:
            return fail(f"feedback lifecycle aggregation is wrong: {feedback_summary}")
        if feedback_summary.get("by_module") != {"service": 1, "workflow": 1} or feedback_summary.get("by_reason") != {"missing_action": 1, "unclear": 1}:
            return fail(f"feedback dimensions are wrong: {feedback_summary}")
        oldest_open_age_seconds = feedback_summary.get("oldest_open_age_seconds")
        if not isinstance(oldest_open_age_seconds, int) or oldest_open_age_seconds < 0:
            return fail(f"oldest open feedback age is missing: {feedback_summary}")
        if overview.get("data_quality", {}).get("synthetic_test_feedback_excluded") != 1:
            return fail(f"synthetic feedback exclusion is not explicit: {overview.get('data_quality')}")
        clamped_overview = _get_json(
            f"{base}/owner/operations-overview?period_days=999999",
            token=admin_token,
            host=OPS_HOST,
        )
        if clamped_overview["body"].get("operations_overview", {}).get("period", {}).get("days") != 366:
            return fail(f"overview period upper bound failed: {clamped_overview}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            concurrent_results = list(
                executor.map(
                    lambda _: _get_json(
                        f"{base}/owner/operations-overview?period_days=30",
                        token=admin_token,
                        host=OPS_HOST,
                    ),
                    range(16),
                )
            )
        if any(response["status"] != 200 for response in concurrent_results):
            return fail(f"concurrent read-only overview requests were unstable: {concurrent_results}")

        all_detail_payloads = {}
        for section in ("traffic", "merchants", "transactions", "costs", "workflows", "audit", "feedback"):
            response = _get_json(
                f"{base}/owner/operations/{section}?period_days=7&limit=1&cursor=not-a-valid-cursor",
                token=admin_token,
                host=OPS_HOST,
            )
            if response["status"] != 200:
                return fail(f"{section} detail failed: {response}")
            detail = response["body"].get("operations_detail") or {}
            if detail.get("section") != section or detail.get("secret_exposed") is not False:
                return fail(f"{section} detail contract is wrong: {detail}")
            if detail.get("merchant_content_exposed") is True:
                return fail(f"{section} detail exposed merchant content")
            all_detail_payloads[section] = detail

        feedback_detail_response = _get_json(
            f"{base}/owner/operations/feedback?period_days=7&status=open&module=workflow&limit=1",
            token=admin_token,
            host=OPS_HOST,
        )
        feedback_detail = feedback_detail_response["body"].get("operations_detail") or {}
        feedback_items = feedback_detail.get("items") or []
        if feedback_detail_response["status"] != 200 or len(feedback_items) != 1:
            return fail(f"feedback detail filters failed: {feedback_detail_response}")
        if feedback_detail.get("raw_merchant_content_exposed") is not False:
            return fail(f"feedback detail raw-content flag is wrong: {feedback_detail}")
        if feedback_detail.get("sanitized_feedback_text_internal_only") is not True:
            return fail(f"feedback detail internal-text flag is wrong: {feedback_detail}")
        feedback_item = feedback_items[0]
        expected_feedback_keys = {
            "feedback_id",
            "module_key",
            "reason",
            "status",
            "stage_title",
            "detail",
            "created_at",
            "updated_at",
            "resolved_at",
        }
        if set(feedback_item) != expected_feedback_keys:
            return fail(f"feedback detail exposed unexpected fields: {feedback_item}")
        serialized_feedback = json.dumps(feedback_detail, ensure_ascii=False).lower()
        for forbidden in (
            "company_id",
            "user_id",
            "store_id",
            "task_id",
            "report_id",
            "confirmation_id",
            "packet_id",
            "idempotency",
            "onerror",
            "<img",
        ):
            if forbidden in serialized_feedback:
                return fail(f"feedback detail exposed forbidden content: {forbidden}")
        if feedback_item.get("stage_title") != "确认经营步骤" or feedback_item.get("detail") != "这里的下一步不够清楚。":
            return fail(f"feedback detail did not return sanitized short text: {feedback_item}")
        departed_member_detail = _get_json(
            f"{base}/owner/operations/feedback?period_days=7&status=open&module=service&limit=10",
            token=admin_token,
            host=OPS_HOST,
        )
        departed_items = departed_member_detail["body"].get("operations_detail", {}).get("items") or []
        if departed_member_detail["status"] != 200 or len(departed_items) != 1:
            return fail(f"legitimate departed-member feedback history was hidden: {departed_member_detail}")

        real_feedback_id = str(real_feedback["body"].get("product_feedback", {}).get("feedback_id") or "")
        older_matching_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        newer_nonmatching_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with repository._connect() as conn:
            merchant_company_id = str(
                conn.execute("select default_company_id from users where user_id = ?", (merchant_user_id,)).fetchone()["default_company_id"]
            )
            conn.execute(
                "update merchant_product_feedback set created_at = ?, updated_at = ? where feedback_id = ?",
                (older_matching_at, older_matching_at, real_feedback_id),
            )
            conn.executemany(
                """
                insert into merchant_product_feedback (
                  feedback_id, company_id, user_id, store_id, feedback_type,
                  module_key, reason, status, idempotency_key_hash,
                  created_at, updated_at, resolved_at, feedback_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"feedback_nonmatching_{index:05d}",
                        merchant_company_id,
                        merchant_user_id,
                        None,
                        "product_improvement",
                        "media",
                        "wrong_result",
                        "resolved",
                        f"nonmatching-hash-{index:05d}",
                        newer_nonmatching_at,
                        newer_nonmatching_at,
                        newer_nonmatching_at,
                        json.dumps({"stage_title": "较新的非匹配反馈", "detail": "用于筛选下推上限测试。"}, ensure_ascii=False),
                    )
                    for index in range(5002)
                ],
            )
        capped_filtered = _get_json(
            f"{base}/owner/operations/feedback?period_days=7&status=open&module=workflow&limit=10",
            token=admin_token,
            host=OPS_HOST,
        )
        capped_filtered_detail = capped_filtered["body"].get("operations_detail", {})
        capped_filtered_items = capped_filtered_detail.get("items") or []
        if (
            capped_filtered["status"] != 200
            or len(capped_filtered_items) != 1
            or capped_filtered_items[0].get("feedback_id") != real_feedback_id
            or capped_filtered_detail.get("data_window_capped") is not False
        ):
            return fail(f"feedback SQL filters were applied after the 5001-row cap: {capped_filtered}")
        capped_unfiltered = _get_json(
            f"{base}/owner/operations/feedback?period_days=7&limit=1",
            token=admin_token,
            host=OPS_HOST,
        )
        if capped_unfiltered["body"].get("operations_detail", {}).get("data_window_capped") is not True:
            return fail(f"feedback detail cap semantics did not report a capped matching window: {capped_unfiltered}")

        serialized_details = json.dumps(all_detail_payloads, ensure_ascii=False).lower()
        if ADMIN_EMAIL in serialized_details or MERCHANT_EMAIL in serialized_details:
            return fail("operations detail exposed a raw account email")
        for forbidden in ("password", "refresh_token", "client_secret", "api_key"):
            if forbidden in serialized_details:
                return fail(f"operations detail exposed forbidden field: {forbidden}")

        invalid = _get_json(f"{base}/owner/operations/not-a-section", token=admin_token, host=OPS_HOST)
        if invalid["status"] != 400:
            return fail(f"invalid detail section should be 400: {invalid}")
        extreme = _get_json(
            f"{base}/owner/operations/merchants?period_days=-999&limit=9999&cursor=djE6OTk5OTk5",
            token=admin_token,
            host=OPS_HOST,
        )
        extreme_detail = extreme["body"].get("operations_detail") or {}
        if extreme["status"] != 200 or extreme_detail.get("period", {}).get("days") != 1 or len(extreme_detail.get("items") or []) > 100:
            return fail(f"detail bounds failed: {extreme}")
        malicious_query = urllib.parse.urlencode(
            {"status": "' OR 1=1 --", "plan": "<script>alert(1)</script>", "limit": "100"}
        )
        malicious = _get_json(
            f"{base}/owner/operations/merchants?{malicious_query}",
            token=admin_token,
            host=OPS_HOST,
        )
        if malicious["status"] != 200 or malicious["body"].get("operations_detail", {}).get("secret_exposed") is not False:
            return fail(f"malicious filter input crossed the operations boundary: {malicious}")

        throttled = None
        for _ in range(21):
            throttled = _post_json(
                f"{base}/owner/auth/login",
                {"email": "rate-limit-attacker@example.invalid", "password": "wrong-password"},
                host="ops.jiejing.shop",
            )
        if not throttled or throttled["status"] != 429:
            return fail(f"operations login did not enforce the shared authentication rate limit: {throttled}")

        ops_html = (ROOT / "ops.html").read_text(encoding="utf-8")
        ops_js = (ROOT / "ops.js").read_text(encoding="utf-8")
        browser_smoke = (ROOT / "tools" / "codex_jiejing_operations_console_smoke.js").read_text(encoding="utf-8")
        nginx = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
        caddy_systemd = (ROOT / "deploy" / "Caddyfile.public-staging.systemd").read_text(encoding="utf-8")
        if "noindex,nofollow" not in ops_html or "/owner/auth/login" not in ops_js:
            return fail("operations frontend security markers are missing")
        cache_versions = re.findall(
            r'(?:ops\.css|assets/jiejing-ops-panels\.js|ops\.js)\?v=([^"\s]+)',
            ops_html,
        )
        if len(cache_versions) != 3 or len(set(cache_versions)) != 1:
            return fail("operations asset cache version must match exactly across CSS and both JS bundles")
        for marker in (
            'data-view="feedback">产品反馈',
            "经营数据只读，反馈处理只更新内部状态",
        ):
            if marker not in ops_html + ops_js:
                return fail(f"operations feedback UI marker is missing: {marker}")
        for marker in (
            'feedback: "产品反馈"',
            'metric("待处理反馈"',
            'selectFilter("status", "全部状态"',
            'selectFilter("module", "全部模块"',
            '/owner/product-feedback/review',
            '/owner/product-feedback/resolve',
            "await Promise.all([",
            'loadDetail("feedback", filters)',
            "loadOverview(true)",
            'showAlert("反馈状态已更新，列表刷新失败，请刷新")',
            'setLoading(false, "反馈状态已更新，列表待刷新")',
        ):
            if marker not in ops_js:
                return fail(f"operations feedback interaction contract is missing: {marker}")
        if "localStorage" in ops_js or "sessionStorage" in ops_js:
            return fail("operations frontend persists a session token in browser storage")
        for marker in (
            "expireOpsSession(response.status)",
            "state.overview = null",
            "state.details.clear()",
            'setScreen(status === 403 ? "denied" : "login")',
            'elements.dataStatus.textContent = "登录已过期，请重新登录"',
        ):
            if marker not in ops_js:
                return fail(f"expired operations sessions must clear stale data: {marker}")
        if "server_name ops.jiejing.shop" not in nginx or "location = /ops.html { return 404; }" not in nginx:
            return fail("operations hostname isolation is missing")
        if "listen 80 default_server;" not in nginx or "server_name app.jiejing.shop jiejing.shop" not in nginx:
            return fail("merchant application is not the explicit default virtual host")
        if "location ~ ^/(auth|permissions|owner)(/|$)" in nginx:
            return fail("operations hostname exposes broad backend route prefixes")
        for allowed_route in ("auth/logout", "auth/refresh", "permissions/me", "owner/auth/login", "owner/operations-overview"):
            if allowed_route not in nginx:
                return fail(f"operations hostname is missing required route: {allowed_route}")
        app_server_start = nginx.find("server {\n    listen 80 default_server;")
        if app_server_start < 0:
            return fail("merchant application default server block is missing")
        ops_server = nginx[:app_server_start]
        app_server = nginx[app_server_start:]
        refresh_start = ops_server.find("location = /auth/refresh")
        refresh_end = ops_server.find("\n    location ", refresh_start + len("location = /auth/refresh"))
        refresh_block = ops_server[refresh_start : refresh_end if refresh_end >= 0 else len(ops_server)]
        if refresh_start < 0 or "$request_method != POST" not in refresh_block or "return 405" not in refresh_block or "proxy_pass" not in refresh_block:
            return fail("operations refresh proxy must be an exact POST-only route")
        for exact_location, method_guard in (
            ("location = /owner/operations/feedback", "$request_method != GET"),
            ("location = /owner/product-feedback/review", "$request_method != POST"),
            ("location = /owner/product-feedback/resolve", "$request_method != POST"),
        ):
            location_start = ops_server.find(exact_location)
            next_location = ops_server.find("\n    location ", location_start + len(exact_location))
            location_block = ops_server[location_start : next_location if next_location >= 0 else len(ops_server)]
            if ops_server.count(exact_location) != 1 or location_start < 0 or method_guard not in location_block or "return 405" not in location_block or "proxy_pass" not in location_block:
                return fail(f"operations feedback proxy allowlist is not exact: {exact_location}")
            app_location_start = app_server.find(exact_location)
            next_app_location = app_server.find("\n    location ", app_location_start + len(exact_location))
            app_location_block = app_server[app_location_start : next_app_location if next_app_location >= 0 else len(app_server)]
            if app_server.count(exact_location) != 1 or app_location_start < 0 or "return 404" not in app_location_block or "proxy_pass" in app_location_block:
                return fail(f"merchant application exposes operations feedback route: {exact_location}")
        if "ops.jiejing.shop" not in caddy_systemd or 'Referrer-Policy "no-referrer"' not in caddy_systemd:
            return fail("systemd edge is missing the isolated operations hostname")
        if any(name in ops_js.lower() for name in ("fal.ai", "fal_api", "runway")):
            return fail("operations frontend exposed a media supplier brand")
        if "Program Files\\\\Google\\\\Chrome" in browser_smoke:
            return fail("operations browser smoke hard-codes a Windows-only Chrome executable")
        for marker in ("JIEJING_PLAYWRIGHT_EXECUTABLE", "JIEJING_PLAYWRIGHT_CHANNEL", 'launchOptions.channel ='):
            if marker not in browser_smoke:
                return fail(f"operations browser smoke is missing its cross-platform launch contract: {marker}")

        print("PASS jiejing_operations_console")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_for_health(base: str) -> None:
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            if _get_json(f"{base}/health")["status"] == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("backend did not become healthy")


def _post_json(url: str, body: dict[str, Any], *, token: str = "", host: str = "") -> dict[str, Any]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if host:
        headers["host"] = host
        headers["x-forwarded-proto"] = "https"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    return _open_json(request)


def _get_json(url: str, *, token: str = "", host: str = "") -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if host:
        headers["host"] = host
        headers["x-forwarded-proto"] = "https"
    return _open_json(urllib.request.Request(url, headers=headers, method="GET"))


def _open_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return {
                "status": response.status,
                "body": json.loads(response.read().decode("utf-8")),
                "headers": {key.lower(): value for key, value in response.headers.items()},
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:200]}
        return {
            "status": exc.code,
            "body": body,
            "headers": {key.lower(): value for key, value in exc.headers.items()},
        }


if __name__ == "__main__":
    raise SystemExit(main())
