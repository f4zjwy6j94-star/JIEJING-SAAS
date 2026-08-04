#!/usr/bin/env python3
"""Fail-closed ownership checks for Jiejing staging runtime env files.

The public report is deliberately value-free.  Values are read only so the
checker can validate exact Compose safety clamps; they are never copied into a
report, exception, or diagnostic message.

Compose ``env_file`` references are resolved relative to the Compose file and
must identify the exact files supplied by the three CLI path arguments.  A
candidate/pre-copy caller must stage those audited files at the referenced
paths; same-basename files elsewhere are intentionally not accepted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


SCHEMA_VERSION = "jiejing_runtime_env_overlap_guard_v1"
MANAGED_SOURCE = "tencent-managed.env"
SECRET_SOURCE = "jiejing-saas.staging-oauth.env"
POSTGRES_SOURCE = "postgres-localqueue.env"
COMPOSE_SOURCE = "compose"

KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMPOSE_MAPPING_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*?))?\s*$")
COMPOSE_LIST_PATTERN = re.compile(r"^-\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

POSTGRES_PREFIXES = (
    "JIEJING_DATABASE_",
    "JIEJING_POSTGRES_",
    "JIEJING_QUEUE_",
    "JIEJING_REDIS_",
)
MANAGED_PREFIXES = (
    "JIEJING_BACKUP_",
    "JIEJING_COS_",
    "JIEJING_CLS_",
    "JIEJING_RESTORE_",
    "JIEJING_TENCENT_",
    "JIEJING_PROVIDER_",
)
SECRET_EXACT_KEYS = {
    "DEEPSEEK_API_KEY",
    "EBAY_ACCESS_TOKEN",
    "EBAY_CLIENT_ID",
    "EBAY_CLIENT_SECRET",
    "EBAY_REFRESH_TOKEN",
    "EBAY_RU_NAME",
    "FAL_KEY",
    "FAL_KEY_ID",
    "FAL_KEY_SECRET",
    "OPENAI_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "TAVILY_API_KEY",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_OPERATOR_BOOTSTRAP_SECRET",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_NAMESPACE",
    "JIEJING_VAULT_PATH_TEMPLATE",
    "JIEJING_VAULT_SECRET_FIELD",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_EBAY_OAUTH_ENV",
    "JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL",
    "JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN",
    "JIEJING_EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_RU_NAME",
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_EBAY_AUTO_REFRESH",
    "JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED",
    "JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH",
    "JIEJING_EBAY_ACCESS_TOKEN",
    "JIEJING_EBAY_ACCOUNT_READ_TOKEN",
    "JIEJING_EBAY_READ_TOKEN",
    "JIEJING_EBAY_REFRESH_TOKEN",
    "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
    "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
    "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
    "JIEJING_WECHAT_PAY_APP_ID",
    "JIEJING_WECHAT_PAY_MCH_ID",
    "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
    "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
    "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
    "JIEJING_WECHAT_PAY_API_V3_KEY",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
    "JIEJING_WECHAT_PAY_NOTIFY_URL",
    "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
    "JIEJING_MODEL",
    "JIEJING_MODEL_API_KEY",
    "JIEJING_MODEL_API_STYLE",
    "JIEJING_MODEL_BASE_URL",
    "JIEJING_MODEL_ENDPOINT",
    "JIEJING_MODEL_PROVIDER",
    "JIEJING_PUBLIC_SEARCH_API_KEY",
    "JIEJING_PUBLIC_SEARCH_LIVE",
    "JIEJING_PUBLIC_SEARCH_LIVE_ENABLED",
    "JIEJING_PUBLIC_SEARCH_PROVIDER",
    "JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED",
    "JIEJING_MEDIA_GENERATED_ASSET_DIR",
    "JIEJING_MEDIA_GENERATION_API_KEY",
    "JIEJING_MEDIA_GENERATION_LIVE",
    "JIEJING_MEDIA_GENERATION_PROVIDER",
    "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
    "JIEJING_MEDIA_LIVE_VIDEO_ENABLED",
    "JIEJING_MEDIA_OPENAI_API_KEY",
    "JIEJING_FAL_KEY_ID",
    "JIEJING_FAL_KEY_SECRET",
    "JIEJING_STRIPE_SECRET_KEY",
    "JIEJING_STRIPE_WEBHOOK_SECRET",
    "VAULT_TOKEN",
}
SECRET_CREDENTIAL_SUFFIXES = (
    "_ACCESS_TOKEN",
    "_API_KEY",
    "_BOOTSTRAP_SECRET",
    "_CLIENT_SECRET",
    "_PRIVATE_KEY_PEM",
    "_PRIVATE_KEY_PEM_B64",
    "_REFRESH_TOKEN",
    "_SECRET_KEY",
    "_SESSION_SECRET",
    "_VERIFICATION_TOKEN",
    "_WEBHOOK_SECRET",
)
MANAGED_VAULT_EVIDENCE_KEYS = {
    "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
    "JIEJING_VAULT_BACKUP_VERIFIED_AT",
    "JIEJING_VAULT_KMS_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_SSM_ENABLED",
}
MANAGED_EXACT_KEYS = MANAGED_VAULT_EVIDENCE_KEYS | {
    "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_LIVE_PROBE_PASSED",
    "TENCENTCLOUD_SECRET_ID",
    "TENCENTCLOUD_SECRET_KEY",
    "TENCENTCLOUD_TOKEN",
    "VAULT_ADDR",
}
COMPOSE_SAFETY_VALUES = {
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
    "JIEJING_EBAY_WRITE_LIVE": "false",
    "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": "disabled_public_staging",
}
COMPOSE_BILLING_PROVIDER_VALUE = "stripe_test_mock"
COMPOSE_REQUIRED_VALUES = {
    **COMPOSE_SAFETY_VALUES,
    "JIEJING_BILLING_PROVIDER": COMPOSE_BILLING_PROVIDER_VALUE,
}
RUNTIME_SERVICE_NAMES = frozenset({"jiejing-saas", "jiejing-worker"})
FALSE_OR_DISABLED_VALUES = frozenset({"false", "0", "no", "off", "disabled"})
STAGING_VALUE_CONSTRAINTS: dict[str, frozenset[str]] = {
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES": FALSE_OR_DISABLED_VALUES,
    "JIEJING_EBAY_WRITE_LIVE": FALSE_OR_DISABLED_VALUES,
    "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": frozenset({"disabled_public_staging"}),
    "JIEJING_BILLING_PROVIDER": frozenset({COMPOSE_BILLING_PROVIDER_VALUE}),
    "JIEJING_PUBLIC_CHARGING_ALLOWED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_DOMESTIC_PAYMENT_LIVE_CUTOVER_APPROVED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_MANUAL_QR_COLLECTION_ENABLED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_WECHAT_PAY_REFUND_ALLOWED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED": FALSE_OR_DISABLED_VALUES,
    "JIEJING_MEDIA_GENERATION_LIVE": FALSE_OR_DISABLED_VALUES,
}


@dataclass(frozen=True)
class Declaration:
    key: str
    source: str
    line_number: int
    private_value: str = field(repr=False)
    service_occurrence: int | None = None
    environment_block_occurrence: int | None = None


@dataclass(frozen=True)
class SourceDeclarationGroup:
    source: str
    declarations: tuple[Declaration, ...]
    comparison: str


@dataclass(frozen=True)
class KeyAnalysis:
    key: str
    owner: str | None
    declarations: tuple[Declaration, ...]
    source_groups: tuple[SourceDeclarationGroup, ...]
    source_roles: tuple[str, ...]
    comparison: str
    unauthorized_duplicate: bool


@dataclass(frozen=True)
class AnalyzedDeclaration:
    declaration: Declaration
    owner: str | None
    classification: str


@dataclass(frozen=True)
class GuardAnalysis:
    declarations: tuple[Declaration, ...]
    keys: tuple[KeyAnalysis, ...]
    analyzed_declarations: tuple[AnalyzedDeclaration, ...]
    blockers: tuple[dict[str, object], ...]
    warnings: tuple[dict[str, object], ...]
    compose_services: tuple[str, ...]
    unauthorized_duplicate_keys: frozenset[str]


@dataclass(frozen=True)
class ComposeEnvironmentBlock:
    service: str
    service_occurrence: int
    block_occurrence: int
    keys: frozenset[str]


@dataclass(frozen=True)
class ComposeEnvFileBlock:
    service: str
    service_occurrence: int
    block_occurrence: int
    resolved_sources: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class ComposeParseResult:
    declarations: tuple[Declaration, ...]
    blockers: tuple[dict[str, object], ...]
    services_section_count: int
    service_occurrences: tuple[tuple[str, int], ...]
    environment_blocks: tuple[ComposeEnvironmentBlock, ...]
    env_file_blocks: tuple[ComposeEnvFileBlock, ...]


def _strip_yaml_comment(raw: str) -> str:
    text = raw.strip()
    quote: str | None = None
    escaped = False
    comment_at: int | None = None
    for index, character in enumerate(text):
        if quote is not None:
            if quote == '"' and escaped:
                escaped = False
                continue
            if quote == '"' and character == "\\":
                escaped = True
                continue
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            continue
        if character == "#" and (index == 0 or text[index - 1].isspace()):
            comment_at = index
            break
    return text[:comment_at].strip() if comment_at is not None else text


def _strip_yaml_scalar(raw: str) -> str:
    scalar = _strip_yaml_comment(raw)
    if len(scalar) >= 2 and scalar[0] == scalar[-1] and scalar[0] in {'"', "'"}:
        return scalar[1:-1]
    return scalar


def _is_unambiguous_compose_environment_scalar(raw: str) -> bool:
    scalar = _strip_yaml_comment(raw)
    if not scalar:
        return False
    if scalar[0] in {'"', "'"}:
        return len(scalar) >= 2 and scalar[-1] == scalar[0]
    if scalar.casefold() in {"null", "~"}:
        return False
    if scalar.startswith(("[", "{", "|", ">", "&", "*", "!", "- ")):
        return False
    if re.search(r":(?:\s|$)", scalar):
        return False
    return True


def _compose_structural_key(
    stripped: str,
    *,
    expected_names: Sequence[str],
) -> tuple[str, bool, str] | None:
    match = re.fullmatch(
        r"((?:\"(?:\\.|[^\"\\])*\"|'(?:''|[^'])*'|[^:]+))\s*:\s*(.*)",
        stripped,
    )
    if match is None:
        return None
    raw_key = match.group(1).strip()
    tail = match.group(2)
    expected = frozenset(expected_names)
    if raw_key in expected:
        return raw_key, True, tail

    decoded_key = raw_key
    if len(raw_key) >= 2 and raw_key[0] == raw_key[-1] == '"':
        try:
            json_compatible_key = re.sub(
                r"\\x([0-9A-Fa-f]{2})",
                lambda item: f"\\u00{item.group(1)}",
                raw_key,
            )
            decoded = json.loads(json_compatible_key)
            decoded_key = decoded if isinstance(decoded, str) else raw_key
        except (json.JSONDecodeError, UnicodeError):
            decoded_key = raw_key
    elif len(raw_key) >= 2 and raw_key[0] == raw_key[-1] == "'":
        decoded_key = raw_key[1:-1].replace("''", "'")
    elif "\\" in raw_key:
        try:
            json_compatible_key = re.sub(
                r"\\x([0-9A-Fa-f]{2})",
                lambda item: f"\\u00{item.group(1)}",
                raw_key,
            )
            decoded = json.loads(f'"{json_compatible_key}"')
            decoded_key = decoded if isinstance(decoded, str) else raw_key
        except (json.JSONDecodeError, UnicodeError):
            decoded_key = raw_key

    if decoded_key in expected:
        return decoded_key, False, tail
    explicit_key = re.sub(r"^\?\s+", "", decoded_key).strip()
    anchor_key = re.sub(r"^[&*!][^\s]+\s+", "", explicit_key).strip()
    alias_key = decoded_key.lstrip("&*!").strip()
    if explicit_key in expected or anchor_key in expected or alias_key in expected:
        for candidate in (explicit_key, anchor_key, alias_key):
            if candidate in expected:
                return candidate, False, tail
    if raw_key == "<<":
        return "merge", False, tail
    return None


def _has_non_literal_mapping_key_syntax(stripped: str) -> bool:
    match = re.fullmatch(
        r"((?:\"(?:\\.|[^\"\\])*\"|'(?:''|[^'])*'|[^:]+))\s*:\s*(.*)",
        stripped,
    )
    if match is None:
        return False
    raw_key = match.group(1).strip()
    if raw_key == "<<" or not raw_key:
        return True
    if raw_key.startswith(('"', "'", "?", "&", "*", "!", "\\")):
        return True
    return bool(re.search(r"(?:^|\s)[&*!][^\s]*(?:\s|$)", raw_key))


def _is_canonical_explicit_mapping_line(stripped: str) -> bool:
    return bool(re.fullmatch(r"\?(?:\s+[^:]*)?", stripped) or re.fullmatch(r":(?:\s+.*)?", stripped))


def _input_path_blocker(path: Path, source: str) -> dict[str, object] | None:
    try:
        if path.is_symlink():
            return {"code": "source_symlink", "source": source}
    except OSError:
        return {"code": "source_unreadable", "source": source}
    return None


def _normalized_path_identity(path: Path, *, relative_to: Path | None = None) -> str:
    candidate = path
    if not candidate.is_absolute():
        candidate = (relative_to if relative_to is not None else Path.cwd()) / candidate
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(candidate))))


def _normalize_compose_env_file_source(raw: str, *, compose_parent: Path) -> str | None:
    scalar = _strip_yaml_scalar(raw)
    if not scalar or any(marker in scalar for marker in ("$", "%", "~", "\x00")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", scalar) and not re.match(r"^[A-Za-z]:[\\/]", scalar):
        return None
    return _normalized_path_identity(Path(scalar), relative_to=compose_parent)


def _parse_env_file(path: Path, source: str) -> tuple[list[Declaration], list[dict[str, object]]]:
    blockers: list[dict[str, object]] = []
    path_blocker = _input_path_blocker(path, source)
    if path_blocker is not None:
        return [], [path_blocker]
    if not path.is_file():
        return [], [{"code": "source_missing", "source": source}]

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return [], [{"code": "source_unreadable", "source": source}]

    declarations: list[Declaration] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            blockers.append({"code": "invalid_env_syntax", "source": source, "line": line_number})
            continue
        key, private_value = stripped.split("=", 1)
        key = key.strip()
        if not KEY_PATTERN.fullmatch(key):
            blockers.append({"code": "invalid_env_key", "source": source, "line": line_number})
            continue
        declarations.append(Declaration(key, source, line_number, private_value.strip()))
    return declarations, blockers


def _parse_compose(path: Path) -> ComposeParseResult:
    path_blocker = _input_path_blocker(path, COMPOSE_SOURCE)
    if path_blocker is not None:
        return ComposeParseResult((), (path_blocker,), 0, (), (), ())
    if not path.is_file():
        return ComposeParseResult((), ({"code": "source_missing", "source": COMPOSE_SOURCE},), 0, (), (), ())
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return ComposeParseResult((), ({"code": "source_unreadable", "source": COMPOSE_SOURCE},), 0, (), (), ())

    declarations: list[Declaration] = []
    blockers: list[dict[str, object]] = []
    services_section_count = 0
    service_occurrence_counts: dict[str, int] = {}
    service_occurrences: list[tuple[str, int]] = []
    environment_block_counts: dict[tuple[str, int], int] = {}
    environment_block_keys: dict[tuple[str, int, int], set[str]] = {}
    env_file_block_counts: dict[tuple[str, int], int] = {}
    env_file_block_sources: dict[tuple[str, int, int], list[str]] = {}
    services_indent: int | None = None
    service_indent: int | None = None
    service_property_indent: int | None = None
    current_service: str | None = None
    current_service_occurrence: int | None = None
    environment_indent: int | None = None
    current_environment_block: int | None = None
    environment_entry_indent: int | None = None
    env_file_indent: int | None = None
    current_env_file_block: int | None = None
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        leading_whitespace = line[: len(line) - len(line.lstrip())]
        if "\t" in leading_whitespace:
            blockers.append({"code": "invalid_compose_indentation", "source": COMPOSE_SOURCE, "line": line_number})
            continue
        indent = len(line) - len(line.lstrip(" "))

        guarded_structural_scope = indent == 0
        if services_indent is not None and indent > services_indent:
            if service_indent is None or indent == service_indent:
                guarded_structural_scope = True
            elif current_service in RUNTIME_SERVICE_NAMES:
                if environment_indent is not None and indent > environment_indent:
                    guarded_structural_scope = True
                elif env_file_indent is not None and indent > env_file_indent:
                    guarded_structural_scope = True
                elif service_property_indent is None or indent == service_property_indent:
                    guarded_structural_scope = True
        if guarded_structural_scope and _is_canonical_explicit_mapping_line(stripped):
            blockers.append(
                {
                    "code": "unsupported_explicit_compose_mapping_syntax",
                    "source": (
                        f"{COMPOSE_SOURCE}:{current_service}"
                        if current_service in RUNTIME_SERVICE_NAMES
                        and service_indent is not None
                        and indent > service_indent
                        else COMPOSE_SOURCE
                    ),
                    "line": line_number,
                }
            )
            continue
        if guarded_structural_scope and _has_non_literal_mapping_key_syntax(stripped):
            detected_structural_key = _compose_structural_key(
                stripped,
                expected_names=(
                    "services",
                    *tuple(sorted(RUNTIME_SERVICE_NAMES)),
                    "environment",
                    "env_file",
                ),
            )
            blockers.append(
                {
                    "code": "non_literal_compose_structural_key",
                    "source": (
                        f"{COMPOSE_SOURCE}:{current_service}"
                        if current_service in RUNTIME_SERVICE_NAMES
                        and service_indent is not None
                        and indent > service_indent
                        else COMPOSE_SOURCE
                    ),
                    "key": (
                        detected_structural_key[0]
                        if detected_structural_key is not None
                        else "structural_mapping"
                    ),
                    "service": (
                        current_service
                        if current_service in RUNTIME_SERVICE_NAMES
                        and service_indent is not None
                        and indent > service_indent
                        else None
                    ),
                    "line": line_number,
                }
            )
            continue

        top_level_structural_key = _compose_structural_key(
            stripped,
            expected_names=("services",),
        )
        if indent == 0 and top_level_structural_key is not None and not top_level_structural_key[1]:
            blockers.append(
                {
                    "code": "non_literal_compose_structural_key",
                    "source": COMPOSE_SOURCE,
                    "key": top_level_structural_key[0],
                    "line": line_number,
                }
            )
            continue

        services_header = re.fullmatch(r"services\s*:\s*(.*)", stripped)
        if services_header:
            if indent != 0:
                blockers.append(
                    {"code": "non_top_level_compose_services", "source": COMPOSE_SOURCE, "line": line_number}
                )
                services_indent = None
                service_indent = None
                service_property_indent = None
                current_service = None
                current_service_occurrence = None
                environment_indent = None
                current_environment_block = None
                env_file_indent = None
                current_env_file_block = None
                continue
            services_section_count += 1
            inline_tail = services_header.group(1).strip()
            if inline_tail and not inline_tail.startswith("#"):
                blockers.append(
                    {"code": "unsupported_inline_compose_services", "source": COMPOSE_SOURCE, "line": line_number}
                )
                services_indent = None
            else:
                services_indent = indent
            service_indent = None
            service_property_indent = None
            current_service = None
            current_service_occurrence = None
            environment_indent = None
            current_environment_block = None
            env_file_indent = None
            current_env_file_block = None
            continue

        if services_indent is None:
            continue
        if indent <= services_indent:
            services_indent = None
            service_indent = None
            service_property_indent = None
            current_service = None
            current_service_occurrence = None
            environment_indent = None
            current_environment_block = None
            env_file_indent = None
            current_env_file_block = None
            continue

        service_header = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*:\s*(#.*)?", stripped)
        service_structural_key = _compose_structural_key(
            stripped,
            expected_names=tuple(sorted(RUNTIME_SERVICE_NAMES)),
        )
        if (service_indent is None or indent == service_indent) and (
            service_structural_key is not None and not service_structural_key[1]
        ):
            if service_indent is None:
                service_indent = indent
            blockers.append(
                {
                    "code": "non_literal_compose_structural_key",
                    "source": COMPOSE_SOURCE,
                    "service": service_structural_key[0],
                    "key": service_structural_key[0],
                    "line": line_number,
                }
            )
            service_property_indent = None
            current_service = None
            current_service_occurrence = None
            environment_indent = None
            current_environment_block = None
            env_file_indent = None
            current_env_file_block = None
            continue
        if service_indent is None:
            service_indent = indent
            if not service_header:
                blockers.append({"code": "invalid_compose_service_syntax", "source": COMPOSE_SOURCE, "line": line_number})
                current_service = None
                current_service_occurrence = None
                continue
            current_service = service_header.group(1)
            current_service_occurrence = service_occurrence_counts.get(current_service, 0) + 1
            service_occurrence_counts[current_service] = current_service_occurrence
            service_occurrences.append((current_service, current_service_occurrence))
            environment_indent = None
            current_environment_block = None
            service_property_indent = None
            env_file_indent = None
            current_env_file_block = None
            continue

        if indent == service_indent:
            if not service_header:
                blockers.append({"code": "invalid_compose_service_syntax", "source": COMPOSE_SOURCE, "line": line_number})
                current_service = None
                current_service_occurrence = None
                environment_indent = None
                current_environment_block = None
                continue
            current_service = service_header.group(1)
            current_service_occurrence = service_occurrence_counts.get(current_service, 0) + 1
            service_occurrence_counts[current_service] = current_service_occurrence
            service_occurrences.append((current_service, current_service_occurrence))
            environment_indent = None
            current_environment_block = None
            service_property_indent = None
            env_file_indent = None
            current_env_file_block = None
            continue
        if indent < service_indent:
            blockers.append({"code": "invalid_compose_indentation", "source": COMPOSE_SOURCE, "line": line_number})
            current_service = None
            current_service_occurrence = None
            environment_indent = None
            current_environment_block = None
            service_property_indent = None
            env_file_indent = None
            current_env_file_block = None
            continue
        if current_service is None or current_service_occurrence is None:
            blockers.append({"code": "orphan_compose_service_property", "source": COMPOSE_SOURCE, "line": line_number})
            continue

        if environment_indent is not None and indent > environment_indent:
            if environment_entry_indent is None:
                environment_entry_indent = indent
            elif indent != environment_entry_indent:
                blockers.append(
                    {
                        "code": "ambiguous_compose_environment_entry_indent",
                        "source": f"{COMPOSE_SOURCE}:{current_service}",
                        "line": line_number,
                    }
                )
                continue
            match = COMPOSE_MAPPING_PATTERN.fullmatch(stripped) or COMPOSE_LIST_PATTERN.fullmatch(stripped)
            if not match:
                blockers.append(
                    {
                        "code": "invalid_compose_environment_syntax",
                        "source": f"{COMPOSE_SOURCE}:{current_service}",
                        "line": line_number,
                    }
                )
                continue
            key, private_value = match.groups()
            if not _is_unambiguous_compose_environment_scalar(private_value or ""):
                blockers.append(
                    {
                        "code": "non_scalar_compose_environment_value",
                        "key": key,
                        "source": f"{COMPOSE_SOURCE}:{current_service}",
                        "line": line_number,
                    }
                )
                continue
            declarations.append(
                Declaration(
                    key=key,
                    source=f"{COMPOSE_SOURCE}:{current_service}",
                    line_number=line_number,
                    private_value=_strip_yaml_scalar(private_value or ""),
                    service_occurrence=current_service_occurrence,
                    environment_block_occurrence=current_environment_block,
                )
            )
            if current_environment_block is not None:
                environment_block_keys[
                    (current_service, current_service_occurrence, current_environment_block)
                ].add(key)
            continue
        if environment_indent is not None and indent <= environment_indent:
            environment_indent = None
            current_environment_block = None
            environment_entry_indent = None

        if env_file_indent is not None and indent > env_file_indent:
            env_file_entry = re.fullmatch(r"-\s*(.+)", stripped)
            resolved_source = (
                _normalize_compose_env_file_source(env_file_entry.group(1), compose_parent=path.parent)
                if env_file_entry is not None
                else None
            )
            if resolved_source is None:
                blockers.append(
                    {
                        "code": "unsupported_compose_env_file_entry",
                        "source": f"{COMPOSE_SOURCE}:{current_service}",
                        "line": line_number,
                    }
                )
                continue
            if current_env_file_block is not None:
                env_file_block_sources[
                    (current_service, current_service_occurrence, current_env_file_block)
                ].append(resolved_source)
            continue
        if env_file_indent is not None and indent <= env_file_indent:
            env_file_indent = None
            current_env_file_block = None

        structural_key = _compose_structural_key(
            stripped,
            expected_names=("environment", "env_file"),
        )
        if service_property_indent is None:
            service_property_indent = indent
        if indent != service_property_indent:
            if structural_key is not None:
                reserved_name, literal, _tail = structural_key
                blockers.append(
                    {
                        "code": (
                            "nested_reserved_compose_key"
                            if literal
                            else "non_literal_compose_structural_key"
                        ),
                        "source": f"{COMPOSE_SOURCE}:{current_service}",
                        "service": current_service,
                        "key": reserved_name,
                        "line": line_number,
                    }
                )
            continue

        if structural_key is not None and not structural_key[1]:
            blockers.append(
                {
                    "code": "non_literal_compose_structural_key",
                    "source": f"{COMPOSE_SOURCE}:{current_service}",
                    "service": current_service,
                    "key": structural_key[0],
                    "line": line_number,
                }
            )
            continue

        if structural_key is not None and structural_key[0] == "environment":
            block_identity = (current_service, current_service_occurrence)
            current_environment_block = environment_block_counts.get(block_identity, 0) + 1
            environment_block_counts[block_identity] = current_environment_block
            environment_block_keys[(current_service, current_service_occurrence, current_environment_block)] = set()
            inline_tail = structural_key[2].strip()
            env_file_indent = None
            current_env_file_block = None
            environment_entry_indent = None
            if not inline_tail or inline_tail.startswith("#"):
                environment_indent = indent
                continue
            blockers.append(
                {
                    "code": "unsupported_inline_compose_environment",
                    "source": f"{COMPOSE_SOURCE}:{current_service}",
                    "line": line_number,
                }
            )
            environment_indent = None
            continue

        if structural_key is None or structural_key[0] != "env_file":
            continue
        block_identity = (current_service, current_service_occurrence)
        current_env_file_block = env_file_block_counts.get(block_identity, 0) + 1
        env_file_block_counts[block_identity] = current_env_file_block
        env_file_block_sources[(current_service, current_service_occurrence, current_env_file_block)] = []
        inline_tail = structural_key[2].strip()
        environment_indent = None
        current_environment_block = None
        environment_entry_indent = None
        if not inline_tail or inline_tail.startswith("#"):
            env_file_indent = indent
            continue
        blockers.append(
            {
                "code": "unsupported_inline_compose_env_file",
                "source": f"{COMPOSE_SOURCE}:{current_service}",
                "line": line_number,
            }
        )
        env_file_indent = None
    if services_section_count == 0:
        blockers.append({"code": "missing_compose_services_section", "source": COMPOSE_SOURCE})
    elif services_section_count > 1:
        blockers.append(
            {
                "code": "duplicate_top_level_services",
                "source": COMPOSE_SOURCE,
                "count": services_section_count,
            }
        )
    if services_section_count > 0 and not service_occurrences:
        blockers.append({"code": "missing_compose_service_declaration", "source": COMPOSE_SOURCE})
    environment_blocks = tuple(
        ComposeEnvironmentBlock(
            service=service,
            service_occurrence=service_occurrence,
            block_occurrence=block_occurrence,
            keys=frozenset(keys),
        )
        for (service, service_occurrence, block_occurrence), keys in sorted(environment_block_keys.items())
    )
    env_file_blocks = tuple(
        ComposeEnvFileBlock(
            service=service,
            service_occurrence=service_occurrence,
            block_occurrence=block_occurrence,
            resolved_sources=tuple(resolved_sources),
        )
        for (service, service_occurrence, block_occurrence), resolved_sources in sorted(
            env_file_block_sources.items()
        )
    )
    return ComposeParseResult(
        declarations=tuple(declarations),
        blockers=tuple(blockers),
        services_section_count=services_section_count,
        service_occurrences=tuple(service_occurrences),
        environment_blocks=environment_blocks,
        env_file_blocks=env_file_blocks,
    )


def _owner_for_key(key: str) -> str | None:
    if key in COMPOSE_REQUIRED_VALUES:
        return COMPOSE_SOURCE
    if key in MANAGED_EXACT_KEYS or key.startswith(MANAGED_PREFIXES):
        return MANAGED_SOURCE
    if key.startswith(POSTGRES_PREFIXES):
        return POSTGRES_SOURCE
    if key in SECRET_EXACT_KEYS or (key.startswith("JIEJING_") and key.endswith(SECRET_CREDENTIAL_SUFFIXES)):
        return SECRET_SOURCE
    return None


def _source_role(source: str) -> str:
    return COMPOSE_SOURCE if source.startswith(f"{COMPOSE_SOURCE}:") else source


def _comparison(declarations: Sequence[Declaration]) -> str:
    return "equal" if len({declaration.private_value for declaration in declarations}) == 1 else "conflict"


def _build_key_analyses(declarations: Sequence[Declaration]) -> tuple[KeyAnalysis, ...]:
    declarations_by_key: dict[str, list[Declaration]] = {}
    for declaration in declarations:
        declarations_by_key.setdefault(declaration.key, []).append(declaration)

    analyses: list[KeyAnalysis] = []
    for key, key_declarations_list in sorted(declarations_by_key.items()):
        key_declarations = tuple(key_declarations_list)
        declarations_by_source: dict[str, list[Declaration]] = {}
        for declaration in key_declarations:
            declarations_by_source.setdefault(declaration.source, []).append(declaration)
        source_groups = tuple(
            SourceDeclarationGroup(
                source=source,
                declarations=tuple(source_declarations),
                comparison=_comparison(source_declarations),
            )
            for source, source_declarations in sorted(declarations_by_source.items())
        )
        source_roles = tuple(sorted({_source_role(declaration.source) for declaration in key_declarations}))
        analyses.append(
            KeyAnalysis(
                key=key,
                owner=_owner_for_key(key),
                declarations=key_declarations,
                source_groups=source_groups,
                source_roles=source_roles,
                comparison=_comparison(key_declarations),
                unauthorized_duplicate=(
                    len(source_roles) > 1 or any(len(group.declarations) > 1 for group in source_groups)
                ),
            )
        )
    return tuple(analyses)


def analyze_runtime_env_ownership(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
) -> GuardAnalysis:
    declarations: list[Declaration] = []
    blockers: list[dict[str, object]] = []
    for parser, path, source in (
        (_parse_env_file, managed_env_path, MANAGED_SOURCE),
        (_parse_env_file, secret_env_path, SECRET_SOURCE),
        (_parse_env_file, postgres_env_path, POSTGRES_SOURCE),
    ):
        parsed, parse_blockers = parser(path, source)
        declarations.extend(parsed)
        blockers.extend(parse_blockers)
    compose_result = _parse_compose(compose_path)
    declarations.extend(compose_result.declarations)
    blockers.extend(compose_result.blockers)

    service_counts: dict[str, int] = {}
    for service_name, _service_occurrence in compose_result.service_occurrences:
        service_counts[service_name] = service_counts.get(service_name, 0) + 1
    for service_name, count in sorted(service_counts.items()):
        if count <= 1:
            continue
        blockers.append(
            {
                "code": "duplicate_compose_service",
                "source": COMPOSE_SOURCE,
                "service": service_name,
                "count": count,
            }
        )
    for required_service in sorted(RUNTIME_SERVICE_NAMES):
        if service_counts.get(required_service, 0) == 0:
            blockers.append(
                {
                    "code": "missing_required_runtime_service",
                    "source": COMPOSE_SOURCE,
                    "service": required_service,
                }
            )

    environment_blocks_by_service_occurrence: dict[tuple[str, int], list[ComposeEnvironmentBlock]] = {}
    for environment_block in compose_result.environment_blocks:
        environment_blocks_by_service_occurrence.setdefault(
            (environment_block.service, environment_block.service_occurrence), []
        ).append(environment_block)
    for service_name, service_occurrence in compose_result.service_occurrences:
        environment_blocks = environment_blocks_by_service_occurrence.get((service_name, service_occurrence), [])
        if len(environment_blocks) > 1:
            blockers.append(
                {
                    "code": "duplicate_compose_environment_block",
                    "source": f"{COMPOSE_SOURCE}:{service_name}",
                    "service": service_name,
                    "service_occurrence": service_occurrence,
                    "count": len(environment_blocks),
                }
            )
        if service_name not in RUNTIME_SERVICE_NAMES:
            continue
        if not environment_blocks:
            blockers.append(
                {
                    "code": "missing_runtime_environment",
                    "source": f"{COMPOSE_SOURCE}:{service_name}",
                    "service": service_name,
                    "service_occurrence": service_occurrence,
                }
            )
            environment_blocks = [
                ComposeEnvironmentBlock(
                    service=service_name,
                    service_occurrence=service_occurrence,
                    block_occurrence=0,
                    keys=frozenset(),
                )
            ]
        for environment_block in environment_blocks:
            for required_key in sorted(COMPOSE_SAFETY_VALUES):
                if required_key in environment_block.keys:
                    continue
                blockers.append(
                    {
                        "code": "missing_required_compose_clamp",
                        "key": required_key,
                        "source": f"{COMPOSE_SOURCE}:{service_name}",
                        "service": service_name,
                        "service_occurrence": service_occurrence,
                        "environment_block_occurrence": environment_block.block_occurrence,
                    }
                )
            if "JIEJING_BILLING_PROVIDER" not in environment_block.keys:
                blockers.append(
                    {
                        "code": "missing_required_billing_provider_pin",
                        "key": "JIEJING_BILLING_PROVIDER",
                        "source": f"{COMPOSE_SOURCE}:{service_name}",
                        "service": service_name,
                        "service_occurrence": service_occurrence,
                        "environment_block_occurrence": environment_block.block_occurrence,
                    }
                )

    env_file_blocks_by_service_occurrence: dict[tuple[str, int], list[ComposeEnvFileBlock]] = {}
    for env_file_block in compose_result.env_file_blocks:
        env_file_blocks_by_service_occurrence.setdefault(
            (env_file_block.service, env_file_block.service_occurrence), []
        ).append(env_file_block)
    expected_env_file_sources = (
        ("managed", _normalized_path_identity(managed_env_path)),
        ("secret", _normalized_path_identity(secret_env_path)),
        ("postgres", _normalized_path_identity(postgres_env_path)),
    )
    expected_env_file_identities = tuple(identity for _role, identity in expected_env_file_sources)
    for service_name, service_occurrence in compose_result.service_occurrences:
        env_file_blocks = env_file_blocks_by_service_occurrence.get((service_name, service_occurrence), [])
        if len(env_file_blocks) > 1:
            blockers.append(
                {
                    "code": "duplicate_compose_env_file_block",
                    "source": f"{COMPOSE_SOURCE}:{service_name}",
                    "service": service_name,
                    "service_occurrence": service_occurrence,
                    "count": len(env_file_blocks),
                }
            )
        if service_name not in RUNTIME_SERVICE_NAMES:
            continue
        if not env_file_blocks:
            blockers.append(
                {
                    "code": "missing_required_compose_env_file",
                    "source": f"{COMPOSE_SOURCE}:{service_name}",
                    "service": service_name,
                    "service_occurrence": service_occurrence,
                }
            )
            continue
        for env_file_block in env_file_blocks:
            source_counts = {
                role: env_file_block.resolved_sources.count(identity)
                for role, identity in expected_env_file_sources
            }
            for role, count in source_counts.items():
                if count == 0:
                    blockers.append(
                        {
                            "code": "missing_required_compose_env_file_source",
                            "source": f"{COMPOSE_SOURCE}:{service_name}",
                            "service": service_name,
                            "service_occurrence": service_occurrence,
                            "env_file_block_occurrence": env_file_block.block_occurrence,
                            "required_source_role": role,
                        }
                    )
                elif count > 1:
                    blockers.append(
                        {
                            "code": "duplicate_compose_env_file_source",
                            "source": f"{COMPOSE_SOURCE}:{service_name}",
                            "service": service_name,
                            "service_occurrence": service_occurrence,
                            "env_file_block_occurrence": env_file_block.block_occurrence,
                            "required_source_role": role,
                            "count": count,
                        }
                    )
            unexpected_count = sum(
                source not in expected_env_file_identities
                for source in env_file_block.resolved_sources
            )
            if unexpected_count:
                blockers.append(
                    {
                        "code": "unexpected_compose_env_file_source",
                        "source": f"{COMPOSE_SOURCE}:{service_name}",
                        "service": service_name,
                        "service_occurrence": service_occurrence,
                        "env_file_block_occurrence": env_file_block.block_occurrence,
                        "count": unexpected_count,
                    }
                )
            if all(count == 1 for count in source_counts.values()) and not unexpected_count and (
                env_file_block.resolved_sources != expected_env_file_identities
            ):
                blockers.append(
                    {
                        "code": "reordered_compose_env_file_sources",
                        "source": f"{COMPOSE_SOURCE}:{service_name}",
                        "service": service_name,
                        "service_occurrence": service_occurrence,
                        "env_file_block_occurrence": env_file_block.block_occurrence,
                    }
                )

    key_analyses = _build_key_analyses(declarations)
    unauthorized_duplicate_keys = frozenset(
        key_analysis.key for key_analysis in key_analyses if key_analysis.unauthorized_duplicate
    )
    for key_analysis in key_analyses:
        for source_group in key_analysis.source_groups:
            if len(source_group.declarations) <= 1:
                continue
            blockers.append(
                {
                    "code": "same_source_duplicate",
                    "key": key_analysis.key,
                    "source": source_group.source,
                    "lines": [declaration.line_number for declaration in source_group.declarations],
                    "comparison": source_group.comparison,
                }
            )
        if len(key_analysis.source_roles) > 1:
            blockers.append(
                {
                    "code": "cross_source_duplicate",
                    "key": key_analysis.key,
                    "sources": list(key_analysis.source_roles),
                    "comparison": key_analysis.comparison,
                }
            )

    warnings: list[dict[str, object]] = []
    analyzed_declarations: list[AnalyzedDeclaration] = []
    key_analysis_by_key = {key_analysis.key: key_analysis for key_analysis in key_analyses}
    for declaration in declarations:
        owner = key_analysis_by_key[declaration.key].owner
        source_role = _source_role(declaration.source)
        classification = "owned"
        allowed_staging_values = STAGING_VALUE_CONSTRAINTS.get(declaration.key)
        if allowed_staging_values is not None and declaration.private_value.strip().casefold() not in allowed_staging_values:
            blockers.append(
                {
                    "code": "forbidden_staging_value",
                    "key": declaration.key,
                    "source": declaration.source,
                }
            )
        if source_role == COMPOSE_SOURCE and declaration.key not in COMPOSE_REQUIRED_VALUES:
            if owner is None:
                classification = "compose_static_warning"
                warnings.append(
                    {
                        "code": "compose_static_key",
                        "key": declaration.key,
                        "source": declaration.source,
                    }
                )
            else:
                classification = "wrong_source"
                blockers.append(
                    {
                        "code": "wrong_source",
                        "key": declaration.key,
                        "source": declaration.source,
                        "owner": owner,
                    }
                )
        elif owner is None:
            if declaration.key in unauthorized_duplicate_keys:
                classification = "unknown_duplicate"
            else:
                classification = "unknown_unique"
                warnings.append(
                    {
                        "code": "unknown_unique_key",
                        "key": declaration.key,
                        "source": declaration.source,
                    }
                )
        elif source_role != owner:
            classification = "wrong_source"
            blockers.append(
                {
                    "code": "wrong_source",
                    "key": declaration.key,
                    "source": declaration.source,
                    "owner": owner,
                }
            )
        elif owner == COMPOSE_SOURCE and declaration.private_value != COMPOSE_REQUIRED_VALUES[declaration.key]:
            blocker_code = (
                "unsafe_billing_provider"
                if declaration.key == "JIEJING_BILLING_PROVIDER"
                else "unsafe_compose_override"
            )
            classification = blocker_code
            blockers.append(
                {
                    "code": blocker_code,
                    "key": declaration.key,
                    "source": declaration.source,
                    "owner": owner,
                }
            )
        analyzed_declarations.append(
            AnalyzedDeclaration(
                declaration=declaration,
                owner=owner,
                classification=classification,
            )
        )

    return GuardAnalysis(
        declarations=tuple(declarations),
        keys=key_analyses,
        analyzed_declarations=tuple(analyzed_declarations),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        compose_services=tuple(sorted(service_counts)),
        unauthorized_duplicate_keys=unauthorized_duplicate_keys,
    )


COMPOSE_STRUCTURE_BLOCKER_CODES = frozenset(
    {
        "ambiguous_compose_environment_entry_indent",
        "duplicate_compose_env_file_block",
        "duplicate_compose_env_file_source",
        "duplicate_compose_environment_block",
        "duplicate_compose_service",
        "duplicate_top_level_services",
        "invalid_compose_environment_syntax",
        "invalid_compose_indentation",
        "invalid_compose_service_syntax",
        "missing_compose_service_declaration",
        "missing_compose_services_section",
        "missing_required_billing_provider_pin",
        "missing_required_compose_clamp",
        "missing_required_compose_env_file",
        "missing_required_compose_env_file_source",
        "missing_required_runtime_service",
        "missing_runtime_environment",
        "nested_reserved_compose_key",
        "non_literal_compose_structural_key",
        "non_scalar_compose_environment_value",
        "non_top_level_compose_services",
        "orphan_compose_service_property",
        "reordered_compose_env_file_sources",
        "unsupported_compose_env_file_entry",
        "unsupported_explicit_compose_mapping_syntax",
        "unsupported_inline_compose_env_file",
        "unsupported_inline_compose_environment",
        "unsupported_inline_compose_services",
        "unexpected_compose_env_file_source",
        "unsafe_compose_override",
        "unsafe_billing_provider",
    }
)


def _is_compose_contract_blocker(blocker: dict[str, object]) -> bool:
    code = str(blocker.get("code") or "")
    if code in COMPOSE_STRUCTURE_BLOCKER_CODES:
        return True
    source = str(blocker.get("source") or "")
    if source == COMPOSE_SOURCE or source.startswith(f"{COMPOSE_SOURCE}:"):
        return code in {
            "forbidden_staging_value",
            "same_source_duplicate",
            "source_missing",
            "source_symlink",
            "source_unreadable",
            "wrong_source",
        }
    sources = blocker.get("sources")
    return code == "cross_source_duplicate" and isinstance(sources, list) and COMPOSE_SOURCE in sources


def _project_public_report(analysis: GuardAnalysis) -> dict[str, object]:
    blockers = analysis.blockers
    warnings = analysis.warnings
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "check",
        "ok": not blockers,
        "secret_exposed": False,
        "summary": {
            "declaration_count": len(analysis.declarations),
            "key_count": len(analysis.keys),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "unauthorized_duplicate_count": len(analysis.unauthorized_duplicate_keys),
            "wrong_source_count": sum(blocker.get("code") == "wrong_source" for blocker in blockers),
            "unsafe_compose_override_count": sum(
                blocker.get("code") == "unsafe_compose_override" for blocker in blockers
            ),
            "compose_contract_violation_count": sum(
                _is_compose_contract_blocker(blocker) for blocker in blockers
            ),
            # Backward-compatible name: historically this counted the complete
            # Compose contract, including structural failures, not only values.
            "illegal_compose_override_count": sum(_is_compose_contract_blocker(blocker) for blocker in blockers),
            "forbidden_staging_value_count": sum(
                blocker.get("code") == "forbidden_staging_value" for blocker in blockers
            ),
        },
        "declarations": [
            {
                "key": analyzed.declaration.key,
                "source": analyzed.declaration.source,
                "owner": analyzed.owner,
                "classification": analyzed.classification,
            }
            for analyzed in analysis.analyzed_declarations
        ],
        "blockers": list(blockers),
        "warnings": list(warnings),
    }


def check_runtime_env_ownership(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
) -> dict[str, object]:
    return _project_public_report(
        analyze_runtime_env_ownership(
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="Check runtime env ownership without changing files.")
    check_parser.add_argument("--compose", type=Path, required=True)
    check_parser.add_argument("--managed-env", type=Path, required=True)
    check_parser.add_argument("--secret-env", type=Path, required=True)
    check_parser.add_argument("--postgres-env", type=Path, required=True)
    check_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command != "check":
        return 2
    report = check_runtime_env_ownership(
        compose_path=args.compose,
        managed_env_path=args.managed_env,
        secret_env_path=args.secret_env,
        postgres_env_path=args.postgres_env,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        summary = report["summary"]
        print(
            f"{status} jiejing_runtime_env_overlap_guard "
            f"blockers={summary['blocker_count']} warnings={summary['warning_count']} "
            "secret_exposed=false"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
