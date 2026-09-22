"""Offline contracts for the production-only operations migration candidate."""
from __future__ import annotations

import re
import hashlib
import importlib.util
import sys
import os
import subprocess
import tempfile
import unittest
import zipfile
import stat
import types
import shutil
from unittest.mock import patch
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
OPS_ASSETS = (
    "ops.html", "ops.js", "ops.css", "assets/jiejing-logo-mark.svg",
    "assets/jiejing-app-icon.svg", "assets/jiejing-ops-panels.js",
)


def deploy_module():
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("ops_deploy_contract", ROOT / "tools/jiejing_production_deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bash_function(name):
    source = (ROOT / "deploy/jiejing-production-release-apply.sh").read_text()
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", source, re.M | re.S)
    if not match: raise AssertionError(f"missing bash contract: {name}")
    return match.group(0)


def run_bash(script):
    bash = shutil.which('bash')
    if not bash: raise AssertionError('bash is required for operations runtime contracts')
    os_keys = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "ALLUSERSPROFILE", "COMPUTERNAME", "USERNAME", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "OS", "HOME", "PATH", "PATHEXT"}
    env = {key: value for key, value in os.environ.items() if key.upper() in os_keys}
    # WSL may report host-launch warnings before Bash starts. Capture the
    # script's stderr inside Bash; retain the unfiltered launcher bytes apart.
    # Exact TLS/hash/auth/redirect error assertions below remain unchanged.
    with tempfile.TemporaryDirectory(prefix='jiejing-ops-bash-', dir=ROOT) as directory:
        script_stderr = Path(directory) / 'script.stderr'
        capture_path = script_stderr.relative_to(ROOT).as_posix()
        payload = f'exec 2>"$PWD/{capture_path}"\n' + script.replace('\r\n', '\n')
        result = subprocess.run([str(bash), "--noprofile", "--norc", "-s"], input=payload.encode('utf-8'), capture_output=True, cwd=ROOT, env=env, timeout=30)
        if not script_stderr.is_file():
            raise AssertionError('Bash contract script did not start')
        stderr = script_stderr.read_bytes()
    return types.SimpleNamespace(returncode=result.returncode, stdout=result.stdout.decode('utf-8', errors='replace'), stderr=stderr.decode('utf-8', errors='replace'), launcher_stderr=result.stderr)


class ProductionOpsConsolidationTest(unittest.TestCase):
    def test_bash_contract_keeps_launcher_diagnostics_separate_from_script_errors(self):
        launch = subprocess.run
        warning = b"HOST_LAUNCHER_DIAGNOSTIC\n"

        def noisy_launch(*args, **kwargs):
            result = launch(*args, **kwargs)
            return subprocess.CompletedProcess(
                result.args, result.returncode, result.stdout, warning + result.stderr,
            )

        with patch('subprocess.run', side_effect=noisy_launch):
            result = run_bash("printf 'SCRIPT_OUT'; printf 'SCRIPT_ERROR' >&2; exit 7\n")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'SCRIPT_OUT')
        self.assertEqual(result.stderr, 'SCRIPT_ERROR')
        self.assertIn(warning, result.launcher_stderr)

    def test_bash_contract_rejects_launcher_success_without_script_start(self):
        not_started = subprocess.CompletedProcess(['bash'], 0, b'', b'LAUNCH_ONLY')
        with patch('subprocess.run', return_value=not_started):
            with self.assertRaisesRegex(AssertionError, 'Bash contract script did not start'):
                run_bash('exit 0\n')

    def test_operations_service_is_isolated_and_serves_only_its_release_assets(self):
        compose = (ROOT / "deploy/docker-compose.production-pilot.yml").read_text()
        match = re.search(r"^  jiejing-ops-frontend:\n(.*?)(?=^  [a-z]|^volumes:)", compose, re.M | re.S)
        self.assertIsNotNone(match, "production must contain its own operations frontend")
        block = match.group(1)
        for name in OPS_ASSETS:
            self.assertIn(f"../{name}:/usr/share/nginx/html/{name}:ro", block)
        self.assertNotIn("../assets:", block)
        self.assertNotIn("env_file:", block)
        self.assertNotIn("jiejing_secrets", block)
        self.assertNotIn("ports:", block)
        self.assertIn("jiejing_ops", block)
        self.assertIn("./nginx.ops.production.conf:/etc/nginx/conf.d/default.conf:ro", block)
        nginx = (ROOT / "deploy/nginx.ops.production.conf").read_text()
        self.assertEqual(nginx.count("server_name ops.jiejing.shop;"), 1)
        self.assertNotIn("server_name app.jiejing.shop", nginx)
        self.assertIn("location / {\n        return 404;", nginx)
        self.assertIn("listen 80 default_server;\n    server_name _;\n    return 404;", nginx)
        self.assertNotIn("proxy_set_header X-Forwarded-Proto $scheme;", nginx)
        self.assertIn("proxy_set_header X-Forwarded-Proto https;", nginx)

    def test_ops_and_apex_routes_do_not_make_internal_paths_public(self):
        caddy = (ROOT / "deploy/Caddyfile.production").read_text()
        self.assertIn("ops.jiejing.shop {", caddy)
        self.assertIn("reverse_proxy jiejing-ops-frontend:80", caddy)
        self.assertIn("jiejing.shop {\n\tredir https://app.jiejing.shop{uri} permanent", caddy)
        self.assertIn('respond @blockedOpsAsset "Not found" 404', caddy)
        self.assertIn('respond @blockedMerchantInternalApi "Not found" 404', caddy)
        self.assertNotRegex(caddy, r"(?m)^\s*tls\s+(?:internal|/)")
        nginx = (ROOT / "deploy/nginx.ops.production.conf").read_text()
        self.assertIn("location ~ ^/owner(?:/|$) {\n        return 404;", nginx)
        self.assertIn("location ~ ^/owner/billing/domestic/refunds/[A-Za-z0-9_-]+/(review|execute|query)$", nginx)

    def test_existing_ops_permissions_and_method_contracts_are_preserved(self):
        old = (ROOT / 'deploy/nginx.public-staging.conf').read_text().split('\nserver {', 1)[0].strip()
        expected = old.replace('proxy_set_header X-Forwarded-Proto $scheme;', 'proxy_set_header X-Forwarded-Proto https;')
        for location in ('/', '/ops.html'):
            expected = expected.replace(f'    location = {location} {{\n', f'    location = {location} {{\n        if ($request_method !~ ^(?:GET|HEAD)$) {{ return 405; }}\n')
        new = (ROOT / 'deploy/nginx.ops.production.conf').read_text()
        start = new.index('server {\n    listen 80;\n    server_name ops.jiejing.shop;')
        self.assertEqual(new[start:].strip(), expected)

    def test_packager_requires_every_ops_asset(self):
        spec = importlib.util.spec_from_file_location('ops_bundle_fixture', ROOT / 'tools/jiejing_prepare_public_staging_bundle.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        public = {name: b'PUBLIC_FIXTURE' for name in (*module.ATOMIC_FRONTEND_FILES, *OPS_ASSETS)}
        self.assertEqual(set(module._bundle_file_hashes(public)), set(public))
        for omitted in OPS_ASSETS:
            with self.assertRaises(RuntimeError): module._bundle_file_hashes({name: data for name, data in public.items() if name != omitted})
        whitelist = (ROOT / 'deploy/apply-staging-patch.sh').read_text()
        for name in ('deploy/nginx.ops.production.conf', 'tools/test_jiejing_production_ops_consolidation.py', *OPS_ASSETS):
            self.assertIn(f'  "{name}"', whitelist)

    def test_six_operations_assets_are_bound_and_mixed_versions_are_rejected(self):
        module = deploy_module()
        contents = {name: (ROOT / name).read_bytes() for name in OPS_ASSETS}
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "ops.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                for name, data in contents.items():
                    archive.writestr(name, data)
            manifest = {"ops_files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
            module.validate_atomic_ops_release(bundle, manifest)
            for bad in ({}, {"ops_files_sha256": {**manifest["ops_files_sha256"], "ops.js": "0" * 64}}, {"ops_files_sha256": {**manifest["ops_files_sha256"], "app.js": "a" * 64}}):
                with self.assertRaises(ValueError):
                    module.validate_atomic_ops_release(bundle, bad)
            bad_html = contents["ops.html"].replace(b"ops.css?v=", b"ops.css?v=MIXED-")
            contents["ops.html"] = bad_html
            with zipfile.ZipFile(bundle, "w") as archive:
                for name, data in contents.items(): archive.writestr(name, data)
            manifest["ops_files_sha256"]["ops.html"] = hashlib.sha256(bad_html).hexdigest()
            with self.assertRaises(ValueError): module.validate_atomic_ops_release(bundle, manifest)

    def test_apply_has_certificate_and_route_gates_and_honest_transition_rollback(self):
        apply = (ROOT / "deploy/jiejing-production-release-apply.sh").read_text()
        self.assertIn("verify_ops_stored_certificates()", apply)
        self.assertIn('verify_ops_stored_certificates || refuse "REFUSE_OPS_CERTIFICATE_PREFLIGHT=1"', apply)
        self.assertLess(apply.index('verify_ops_stored_certificates || refuse'), apply.index('release_dir="$RELEASE_ROOT/${STAMP}-${short_sha}"'))
        self.assertIn("OPS_ROLLBACK_NEEDS_DNS_CUTBACK=1", apply)
        self.assertIn("APPLICATION_RELEASE_RESTORED=1", apply)
        self.assertIn("verify_ops_surface \"$candidate_app\"", apply)
        self.assertIn('up -d --no-deps --force-recreate jiejing-ops-frontend', apply)
        self.assertIn('--noproxy', apply)
        self.assertNotIn('--insecure', apply)

    def test_each_asset_content_change_rejects_old_immutable_cache_token(self):
        module = deploy_module()
        original = {name: (ROOT / name).read_bytes() for name in OPS_ASSETS}
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'ops.zip'
            def validate(contents):
                with zipfile.ZipFile(bundle, 'w') as archive:
                    for name, data in contents.items(): archive.writestr(name, data)
                module.validate_atomic_ops_release(bundle, {'ops_files_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}})
            validate(original)
            for name in ('ops.js', 'ops.css', 'assets/jiejing-ops-panels.js'):
                changed = {**original, name: original[name] + b'\n/* public changed asset */\n'}
                with self.assertRaisesRegex(ValueError, 'ops_asset_content_version_mismatch'): validate(changed)
            forged = {**original, 'ops.html': re.sub(rb'\?v=[A-Za-z0-9_-]+', b'?v=ops-v1-000000000000', original['ops.html'])}
            with self.assertRaisesRegex(ValueError, 'ops_asset_content_version_mismatch'): validate(forged)
            normalized = dict(original)
            for name in ('ops.js', 'ops.css', 'assets/jiejing-ops-panels.js'):
                normalized[name] = original[name].replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
            validate(normalized)

    def test_ops_html_references_are_actual_unique_local_loads(self):
        module = deploy_module()
        version = module.ops_asset_version({name: b'PUBLIC_FIXTURE' for name in OPS_ASSETS}).encode()
        valid = b'<link rel="stylesheet" href="./ops.css?v=one"><script src="./assets/jiejing-ops-panels.js?v=one"></script><script src="./ops.js?v=one"></script>'.replace(b'?v=one', b'?v=' + version)
        invalid = (
            valid.replace(b'./ops.js?', b'https://untrusted.example/ops.js?'),
            valid.replace(b'./ops.js?', b'./ops.css?'),
            valid + b'<script src="./ops.js"></script>',
            b'<!-- ' + valid + b' -->',
            valid.replace(b'rel="stylesheet"', b'rel="prefetch"'),
            valid.replace(b'<script src="./ops.js?', b'<script src="https://untrusted.example/ops.js" src="./ops.js?'),
        )
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "ops.zip"
            for data in invalid:
                contents = {name: b'PUBLIC_FIXTURE' for name in OPS_ASSETS}
                contents['ops.html'] = data
                with zipfile.ZipFile(bundle, 'w') as archive:
                    for name, value in contents.items(): archive.writestr(name, value)
                manifest = {'ops_files_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}}
                with self.assertRaises(ValueError): module.validate_atomic_ops_release(bundle, manifest)

    def test_ops_stop_fails_closed_for_daemon_error_and_wrong_owner(self):
        fixture = f'''set -euo pipefail
{bash_function("stop_candidate_ops_if_owned")}
candidate_app=/fixture/candidate
docker() {{
  [[ "$MODE" != daemon ]] || return 2
  if [[ "$1 $2" == 'ps -aq' ]]; then
    [[ "$MODE" == absent ]] || printf '%064d\\n' 1
  elif [[ "$1" == inspect ]]; then
    [[ "$MODE" != foreign ]] && printf '%s\\n' "$candidate_app/deploy/docker-compose.production-pilot.yml" || printf '/foreign/deploy/docker-compose.production-pilot.yml\\n'
  elif [[ "$1" == stop ]]; then STOPPED=1
  elif [[ "$1 $2" == 'container inspect' ]]; then return 1
  else return 8; fi
}}
stop_candidate_ops_if_owned
printf 'STOPPED=%s\\n' "${{STOPPED:-0}}"
'''
        for mode in ('owned', 'absent', 'foreign', 'daemon'):
            result = run_bash(f'MODE={mode}\n' + fixture)
            self.assertEqual(result.returncode == 0, mode in ('owned', 'absent'), result.stderr)
            self.assertEqual('STOPPED=1' in result.stdout, mode == 'owned')

    def test_certificate_preflight_needs_both_hosts_valid_chain_and_private_metadata(self):
        shell = bash_function('verify_ops_stored_certificates')
        code = shell.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        cases = ('none', 'caddy_sticky', 'missing_apex', 'wrong_san', 'expired', 'chain',
                 'key_permissions', 'symlink', 'changed', 'caddy_nonsticky',
                 'caddy_other_sticky_mode', 'caddy_wrong_owner', 'caddy_wrong_group',
                 'caddy_not_directory', 'caddy_symlink', 'writable_other_ancestor',
                 'writable_descendant', 'caddy_replaced', 'ancestor_replaced',
                 'caddy_permissions_changed')
        storage = '/var/lib/docker/volumes/deploy_jiejing_caddy_data/_data/caddy'
        for failure in cases:
            completed_checks = [False]
            class PublicPath:
                def __init__(self, value): self.value = PurePosixPath(value)
                def __str__(self): return str(self.value)
                def __truediv__(self, value): return PublicPath(self.value / value)
                def with_suffix(self, suffix): return PublicPath(self.value.with_suffix(suffix))
                @property
                def parents(self): return tuple(PublicPath(p) for p in self.value.parents)
                def exists(self): return not (failure == 'missing_apex' and self.value.name.startswith('jiejing.shop.'))
                def lstat(self):
                    is_key = self.value.suffix == '.key'
                    regular = self.value.suffix in ('.crt', '.key')
                    mode = (stat.S_IFREG | 0o600) if regular else (stat.S_IFDIR | 0o700)
                    is_storage = str(self.value) == storage
                    owner = group = 0
                    inode = 2 + int(failure == 'changed' and completed_checks[0])
                    if is_storage and failure.startswith('caddy_'):
                        mode = stat.S_IFDIR | 0o1777
                        if failure == 'caddy_nonsticky': mode = stat.S_IFDIR | 0o777
                        if failure == 'caddy_other_sticky_mode': mode = stat.S_IFDIR | 0o1775
                        if failure == 'caddy_wrong_owner': owner = 1000
                        if failure == 'caddy_wrong_group': group = 1000
                        if failure == 'caddy_not_directory': mode = stat.S_IFREG | 0o1777
                        if failure == 'caddy_symlink': mode = stat.S_IFLNK | 0o1777
                        if failure == 'caddy_replaced' and completed_checks[0]: inode += 1
                        if failure == 'caddy_permissions_changed' and completed_checks[0]: mode = stat.S_IFDIR | 0o1775
                    if str(self.value) == str(PurePosixPath(storage).parent):
                        if failure == 'writable_other_ancestor': mode = stat.S_IFDIR | 0o1777
                        if failure == 'ancestor_replaced' and completed_checks[0]: inode += 1
                    if str(self.value) == storage + '/certificates' and failure == 'writable_descendant':
                        mode = stat.S_IFDIR | 0o1777
                    if is_key and failure == 'key_permissions': mode = stat.S_IFREG | 0o644
                    if is_key and failure == 'symlink': mode = stat.S_IFLNK | 0o777
                    return types.SimpleNamespace(st_dev=1, st_ino=inode, st_uid=owner, st_gid=group, st_mode=mode, st_size=2048, st_mtime_ns=1234, st_ctime_ns=1234)
            commands = []
            def openssl(args, **kwargs):
                commands.append(args)
                self.assertEqual(args[0], 'openssl')
                self.assertFalse(any(str(arg).endswith('.key') for arg in args), 'private key must never be opened by this preflight')
                self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
                if '-ext' in args:
                    host = PurePosixPath(args[args.index('-in') + 1]).name[:-4]
                    return types.SimpleNamespace(returncode=0, stdout=('DNS:' + ('wrong.example' if failure == 'wrong_san' else host)).encode())
                if '-checkend' in args: return types.SimpleNamespace(returncode=int(failure == 'expired'), stdout=b'')
                self.assertIn('-verify_hostname', args); self.assertIn('-CApath', args)
                completed_checks[0] = True
                return types.SimpleNamespace(returncode=int(failure == 'chain'), stdout=b'')
            with patch('pathlib.Path', PublicPath), patch('subprocess.run', side_effect=openssl):
                if failure in ('none', 'caddy_sticky'): exec(compile(code, '<certificate-fixture>', 'exec'), {})
                else:
                    with self.assertRaises(SystemExit) as result: exec(compile(code, '<certificate-fixture>', 'exec'), {})
                    self.assertEqual(result.exception.code, 1)
            if failure in ('none', 'caddy_sticky'):
                self.assertEqual({args[args.index('-verify_hostname')+1] for args in commands if '-verify_hostname' in args}, {'ops.jiejing.shop', 'jiejing.shop'})

    def test_transition_rollback_restores_app_but_never_hides_ops_dns_failure(self):
        fixture = f'''set -euo pipefail
{bash_function('rollback_application_release')}
active_app=/fixture/old
candidate_app=/fixture/new
ACTIVE_LINK=/fixture/active
rollback_image_holds_ready=1
ROLLBACK_API_HOLD_REF=hold-api
ROLLBACK_WORKER_HOLD_REF=hold-worker
previous_api_image_ref=live-api
previous_worker_image_ref=live-worker
previous_api_image_id=api-id
previous_worker_image_id=worker-id
image_ref_id() {{ [[ "$1" == *api ]] && printf api-id || printf worker-id; }}
docker() {{ [[ "$1 $2" == 'image tag' ]]; }}
compose() {{ printf 'RESTORE:%s\\n' "${{@: -1}}"; }}
previous_compose=(compose)
wait_container_healthy() {{ return 0; }}
readlink() {{ printf '%s\\n' "$active_app"; }}
verify_previous_runtime_restored() {{ printf 'APP_VERIFIED\\n'; }}
wait_public_json() {{ printf 'PUBLIC:%s\\n' "$1"; }}
stop_candidate_ops_if_owned() {{ printf 'STOP_CANDIDATE_OPS\\n'; }}
ops_dns_points_to_old_host() {{ [[ "$MODE" == old ]]; }}
verify_ops_surface() {{ [[ "$MODE" != bad_surface ]]; }}
rollback_application_release
'''
        for mode, supported in (('old', 0), ('new', 0), ('new', 1), ('bad_surface', 1)):
            result = run_bash(f'MODE={mode}\nprevious_ops_supported={supported}\n' + fixture)
            self.assertIn('APP_VERIFIED', result.stdout)
            self.assertIn('PUBLIC:/readiness/product-saas', result.stdout)
            self.assertIn('APPLICATION_RELEASE_RESTORED=1', result.stdout)
            self.assertEqual(result.returncode == 0, mode != 'bad_surface' and supported == 1, result.stderr)
            self.assertEqual('OPS_ROLLBACK_NEEDS_DNS_CUTBACK=1' in result.stderr, supported == 0 and mode == 'new')
            self.assertEqual('OPS_APEX_TRANSITION_ROLLBACK_REQUIRES_VERIFICATION=1' in result.stderr, supported == 0)
            self.assertEqual('RESTORE:jiejing-ops-frontend' in result.stdout, supported == 1)

    def test_actual_surface_gate_rejects_tls_asset_auth_and_apex_failures(self):
        # Caddy's configured `permanent` redirect is exactly 301, not 308:
        # https://caddyserver.com/docs/caddyfile/directives/redir
        with tempfile.TemporaryDirectory(prefix='jiejing-ops-surface-', dir=ROOT) as directory:
            root = Path(directory)
            for name in OPS_ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"OPS_ASSET\n")
            source = f'''set -euo pipefail
{bash_function("verify_ops_surface")}
curl() {{
  local url="${{@: -1}}"
  [[ "$*" == *--noproxy* && "$*" == *--resolve* && "$*" != *--insecure* ]] || return 90
  [[ "$MOCK_FAIL" != tls ]] || return 60
  case "$url" in
    https://ops.jiejing.shop/owner/operations-overview|https://ops.jiejing.shop/owner/billing/domestic/refunds|https://ops.jiejing.shop/permissions/me)
      [[ "$MOCK_FAIL" != auth ]] && printf 401 || printf 200 ;;
    https://ops.jiejing.shop/owner/not-allowlisted|https://ops.jiejing.shop/app.html)
      [[ "$MOCK_FAIL" != ops ]] && printf 404 || printf 200 ;;
    https://app.jiejing.shop/*) [[ "$MOCK_FAIL" != app ]] && printf 404 || printf 200 ;;
    https://jiejing.shop/*)
      case "$MOCK_FAIL" in
        apex) printf '200 ' ;;
        apex_308) printf '%s' '308 https://app.jiejing.shop/migration-check?source=ops' ;;
        apex_302) printf '%s' '302 https://app.jiejing.shop/migration-check?source=ops' ;;
        apex_location) printf '%s' '301 https://app.jiejing.shop/WRONG_SECRET_SENTINEL' ;;
        apex_status) printf '%s' 'SECRET_STATUS_SENTINEL https://app.jiejing.shop/migration-check?source=ops' ;;
        *) printf '%s' '301 https://app.jiejing.shop/migration-check?source=ops' ;;
      esac ;;
    https://ops.jiejing.shop/*) [[ "$MOCK_FAIL" != asset ]] && printf 'OPS_ASSET\\n' || printf WRONG ;;
    *) return 91 ;;
  esac
}}
verify_ops_surface "$PWD/{root.relative_to(ROOT).as_posix()}"
'''
            failures = {
                "none": None, "tls": "asset_tls_or_http", "asset": "asset_hash",
                "auth": "anonymous_auth", "ops": "ops_isolation", "app": "app_isolation",
                "apex": "apex_redirect", "apex_308": "apex_redirect", "apex_302": "apex_redirect",
                "apex_location": "apex_redirect", "apex_status": "apex_redirect",
            }
            for failure, marker in failures.items():
                with self.subTest(failure=failure):
                    result = run_bash(f"MOCK_FAIL={failure}\n" + source)
                    self.assertEqual(result.returncode == 0, failure == "none", result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, f"OPS_SURFACE_FAILED={marker}\n" if marker else "")
                    self.assertNotIn("SECRET", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
