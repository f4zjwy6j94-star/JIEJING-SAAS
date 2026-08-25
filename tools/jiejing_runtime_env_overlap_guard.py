#!/usr/bin/env python3
"""Fail-closed ownership checks for Jiejing staging runtime env files.

The public report is deliberately value-free.  Values are read only so the
checker can validate exact Compose safety clamps; they are never copied into a
report, exception, or diagnostic message.

Compose ``env_file`` references are resolved relative to the Compose file and
must identify the exact runtime files supplied by the three runtime-identity
arguments.  Candidate/pre-copy checks may separately supply public template
files as the data sources, without reading the private runtime files.  A
same-basename file is intentionally not accepted as a runtime identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence


SCHEMA_VERSION = "jiejing_runtime_env_overlap_guard_v1"
RESOLUTION_MANIFEST_SCHEMA_VERSION = "jiejing_runtime_env_resolution_manifest_v1"
MIGRATION_APPLY_CONFIRMATION = "APPLY_JIEJING_RUNTIME_ENV_MIGRATION"
RESOLUTION_APPLY_CONFIRMATION = "APPLY_JIEJING_RUNTIME_ENV_RESOLUTION"
RETIRE_EQUAL_COMPOSE_DONOR_ACTION = "retire_equal_compose_donor_keep_authoritative"
RETIRE_EQUAL_COMPOSE_DONOR_KEYS = frozenset(
    {
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED",
    }
)
MANAGED_SOURCE = "tencent-managed.env"
SECRET_SOURCE = "jiejing-saas.staging-oauth.env"
POSTGRES_SOURCE = "postgres-localqueue.env"
COMPOSE_SOURCE = "compose"
COMPOSE_OVERRIDE_SOURCE = "compose-override"
DONOR_COMPOSE_SOURCE = "donor-compose"
RESOLUTION_MANIFEST_SOURCE = "resolution-manifest"

KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMPOSE_MAPPING_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*?))?\s*$")

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
    "JIEJING_BROWSER_SMOKE_PASSED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_DEFAULT_PLAN_KEY",
    "JIEJING_DEPLOY_CHANNEL_READY",
    "JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED",
    "JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED",
    "JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256",
    "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED",
    "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED",
    "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED",
    "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED",
    "JIEJING_PRODUCTION_ROLLBACK_POINT_ID",
    "JIEJING_SECRET_SCAN_PASSED",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_LIVE_PROBE_PASSED",
    "TENCENTCLOUD_SECRET_ID",
    "TENCENTCLOUD_SECRET_KEY",
    "TENCENTCLOUD_TOKEN",
    "VAULT_ADDR",
}
POSTGRES_EXACT_KEYS = {
    "JIEJING_POSTGRES_LIVE_PROBE_PASSED",
}
COMPOSE_SAFETY_VALUES = {
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
    "JIEJING_EBAY_WRITE_LIVE": "false",
    "JIEJING_EBAY_DRAFT_SAVE_LIVE": "false",
    "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": "disabled_public_staging",
}
COMPOSE_BILLING_PROVIDER_VALUE = "stripe_test_mock"
COMPOSE_REQUIRED_VALUES = {
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
    "JIEJING_EBAY_WRITE_LIVE": "false",
    "JIEJING_BILLING_PROVIDER": COMPOSE_BILLING_PROVIDER_VALUE,
}
COMPOSE_STATIC_KEYS = frozenset(
    {
        "JIEJING_ALLOW_HERMES_ADAPTERS",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_CORS_ORIGIN",
        "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_SAAS_ENV",
    }
)
COMPOSE_OWNED_KEYS = frozenset(COMPOSE_SAFETY_VALUES) | frozenset(COMPOSE_REQUIRED_VALUES) | COMPOSE_STATIC_KEYS
PUBLIC_SOURCE_ROLES = frozenset({"managed", "secret", "postgres", "compose"})
ROLE_TO_SOURCE = {
    "managed": MANAGED_SOURCE,
    "secret": SECRET_SOURCE,
    "postgres": POSTGRES_SOURCE,
    "compose": COMPOSE_SOURCE,
}
SOURCE_TO_ROLE = {source: role for role, source in ROLE_TO_SOURCE.items()}
RUNTIME_SERVICE_NAMES = frozenset({"jiejing-saas", "jiejing-worker"})
FALSE_OR_DISABLED_VALUES = frozenset({"false", "0", "no", "off", "disabled"})
STAGING_VALUE_CONSTRAINTS: dict[str, frozenset[str]] = {
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES": FALSE_OR_DISABLED_VALUES,
    "JIEJING_EBAY_WRITE_LIVE": FALSE_OR_DISABLED_VALUES,
    "JIEJING_EBAY_DRAFT_SAVE_LIVE": frozenset({"false", "true"}),
    "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE": frozenset({"false", "true"}),
    "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": frozenset(
        {
            "disabled_public_staging",
            "controlled_unpublished_draft_only",
            "controlled_existing_draft_publish",
        }
    ),
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
    private_raw_rhs: str | None = field(default=None, repr=False)
    private_value_style: str | None = field(default=None, repr=False)
    compose_environment_container: str | None = field(default=None, repr=False)
    compose_scalar_style: str | None = field(default=None, repr=False)


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
class MigrationAction:
    key: str
    source: str
    owner: str
    comparison: str
    bindings: tuple[RemovalBinding, ...] = field(repr=False)
    additions: tuple[AdditionBinding, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class RemovalBinding:
    line_number: int = field(repr=False)
    key: str = field(repr=False)
    line_digest: str = field(repr=False)


@dataclass(frozen=True)
class AdditionBinding:
    key: str = field(repr=False)
    private_value: str = field(repr=False)
    encoded_rhs: str = field(repr=False)


@dataclass(frozen=True)
class SourceSnapshot:
    source: str
    path: Path = field(repr=False)
    payload: bytes = field(repr=False)
    digest: str = field(repr=False)
    resolved_identity: str = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)
    metadata: tuple[int, int, int] = field(repr=False)


@dataclass(frozen=True)
class ParentDirectorySnapshot:
    lexical_identity: str = field(repr=False)
    resolved_identity: str = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)
    directory_type: int = field(repr=False)
    link_or_reparse: bool = field(repr=False)
    mode: int = field(repr=False)


@dataclass(frozen=True)
class MigrationLock:
    path: Path = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)


@dataclass(frozen=True)
class ArtifactRef:
    role: str
    path: Path = field(repr=False)


@dataclass(frozen=True)
class PreparedCandidate:
    path: Path = field(repr=False)
    planned_payload: bytes = field(repr=False)
    planned_digest: str = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)
    metadata: tuple[int, int, int] = field(repr=False)
    role: str


@dataclass(frozen=True)
class NamespaceMutationOutcome:
    path: Path = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)
    metadata: tuple[int, int, int] = field(repr=False)
    durable: bool
    content_verified: bool = True
    prepared_artifact_removed: bool = False


@dataclass(frozen=True)
class CommitRecord:
    source: str
    path: Path = field(repr=False)
    candidate_payload: bytes = field(repr=False)
    candidate_digest: str = field(repr=False)
    physical_identity: tuple[int, int] = field(repr=False)
    candidate_metadata: tuple[int, int, int] = field(repr=False)
    backup_path: Path = field(repr=False)
    candidate_artifact_path: Path = field(repr=False)
    mode: int = field(repr=False)


@dataclass(frozen=True)
class RecoveryOutcome:
    installed: bool
    durable: bool
    artifacts: tuple[ArtifactRef, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class RollbackOutcome:
    blockers: tuple[dict[str, object], ...]
    artifacts: tuple[ArtifactRef, ...] = field(default=(), repr=False)


class PreparedArtifactError(OSError):
    def __init__(self, artifact: ArtifactRef) -> None:
        super().__init__("prepared artifact failed")
        self.artifact = artifact


@dataclass(frozen=True)
class MigrationPlan:
    analysis: GuardAnalysis = field(repr=False)
    actions: tuple[MigrationAction, ...]
    blockers: tuple[dict[str, object], ...]
    snapshots: tuple[SourceSnapshot, ...] = field(default=(), repr=False)
    required_runtime_services: frozenset[str] = field(
        default=RUNTIME_SERVICE_NAMES,
        repr=False,
    )
    compose_override_paths: tuple[Path, ...] = field(default=(), repr=False)
    pre_apply_validator: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    post_apply_validator: Callable[[], None] | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ResolutionDecision:
    key: str
    authoritative_role: str
    donor_role: str | None = None
    resolution_action: str | None = None


@dataclass(frozen=True)
class ResolutionAction:
    action: str
    key: str
    source_role: str
    target_role: str
    count: int
    comparison: str


@dataclass(frozen=True)
class ResolutionExecutionPlan:
    """Private snapshot-bound form of the public resolution plan."""

    report: Mapping[str, object] = field(repr=False)
    analysis: GuardAnalysis = field(repr=False)
    donor_analysis: GuardAnalysis | None = field(default=None, repr=False)
    actions: tuple[ResolutionAction, ...] = ()
    blockers: tuple[dict[str, object], ...] = field(default=(), repr=False)
    snapshots: tuple[SourceSnapshot, ...] = field(default=(), repr=False)
    required_runtime_services: frozenset[str] = field(
        default=RUNTIME_SERVICE_NAMES,
        repr=False,
    )
    compose_override_paths: tuple[Path, ...] = field(default=(), repr=False)
    compose_runtime_path: Path | None = field(default=None, repr=False)
    plan_identity: str = field(default="", repr=False)


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


def _decode_yaml_double_quoted_scalar(scalar: str) -> str | None:
    """Decode the strict YAML double-quoted subset used by Compose scalars."""

    if len(scalar) < 2 or scalar[0] != '"' or scalar[-1] != '"':
        return None
    simple_escapes = {
        "0": "\x00",
        "a": "\x07",
        "b": "\x08",
        "t": "\t",
        "n": "\n",
        "v": "\x0b",
        "f": "\x0c",
        "r": "\r",
        "e": "\x1b",
        " ": " ",
        '"': '"',
        "/": "/",
        "\\": "\\",
    }
    decoded: list[str] = []
    cursor = 1
    while cursor < len(scalar) - 1:
        character = scalar[cursor]
        if character == '"' or ord(character) < 0x20 or ord(character) == 0x7F:
            return None
        if character != "\\":
            decoded.append(character)
            cursor += 1
            continue
        cursor += 1
        if cursor >= len(scalar) - 1:
            return None
        escape = scalar[cursor]
        if escape in simple_escapes:
            decoded.append(simple_escapes[escape])
            cursor += 1
            continue
        hex_width = {"x": 2, "u": 4, "U": 8}.get(escape)
        if hex_width is None:
            return None
        hex_start = cursor + 1
        hex_end = hex_start + hex_width
        digits = scalar[hex_start:hex_end]
        if len(digits) != hex_width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
            return None
        try:
            decoded.append(chr(int(digits, 16)))
        except (OverflowError, ValueError):
            return None
        cursor = hex_end
    return "".join(decoded)


def _decode_yaml_scalar(raw: str) -> tuple[bool, str]:
    """Return an unambiguous scalar and whether its YAML spelling is supported."""

    scalar = _strip_yaml_comment(raw)
    if not scalar:
        return False, ""
    if scalar[0] == "'":
        if len(scalar) < 2 or scalar[-1] != "'":
            return False, ""
        inner = scalar[1:-1]
        if re.fullmatch(r"(?:''|[^'])*", inner) is None:
            return False, ""
        return True, inner.replace("''", "'")
    if scalar[0] == '"':
        decoded = _decode_yaml_double_quoted_scalar(scalar)
        return (decoded is not None, decoded or "")
    return True, scalar


def _strip_yaml_scalar(raw: str) -> str:
    supported, decoded = _decode_yaml_scalar(raw)
    return decoded if supported else _strip_yaml_comment(raw)


def _yaml_scalar_value_style(raw: str) -> str:
    scalar = _strip_yaml_comment(raw)
    if scalar.startswith("'"):
        return "single_quoted"
    if scalar.startswith('"'):
        return "double_quoted"
    return "unquoted"


def _is_unambiguous_compose_environment_scalar(raw: str) -> bool:
    scalar = _strip_yaml_comment(raw)
    if not scalar:
        return False
    if scalar[0] in {'"', "'"}:
        supported, _decoded = _decode_yaml_scalar(raw)
        return supported
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


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_flag and attributes & reparse_flag)
    except (OSError, RuntimeError):
        return False


def _source_parent_link_blocker(path: Path, source: str) -> dict[str, object] | None:
    absolute_path = Path(os.path.abspath(os.fspath(path)))
    for parent in absolute_path.parents:
        if parent == parent.parent:
            continue
        if _path_is_link_or_reparse(parent):
            return {"code": "source_parent_link", "source": source}
    return None


def _capture_source_parent_chain(
    path: Path,
    source: str,
) -> tuple[tuple[ParentDirectorySnapshot, ...], dict[str, object] | None]:
    absolute_path = Path(os.path.abspath(os.fspath(path)))
    parent_chain: list[Path] = []
    parent = absolute_path.parent
    while True:
        parent_chain.append(parent)
        if parent == parent.parent:
            break
        parent = parent.parent
    snapshots: list[ParentDirectorySnapshot] = []
    try:
        for parent in reversed(parent_chain):
            if _path_is_link_or_reparse(parent):
                return (), {"code": "source_parent_link", "source": source}
            checked = os.stat(parent, follow_symlinks=False)
            checked_attributes = getattr(checked, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if stat.S_ISLNK(checked.st_mode) or bool(
                reparse_flag and checked_attributes & reparse_flag
            ):
                return (), {"code": "source_parent_link", "source": source}
            resolved = parent.resolve(strict=True)
            followed = os.stat(parent, follow_symlinks=True)
            checked_identity = (int(checked.st_dev), int(checked.st_ino))
            followed_identity = (int(followed.st_dev), int(followed.st_ino))
            if checked_identity != followed_identity or not stat.S_ISDIR(followed.st_mode):
                return (), {
                    "code": "source_parent_changed_during_snapshot",
                    "source": source,
                }
            snapshots.append(
                ParentDirectorySnapshot(
                    lexical_identity=_normalized_path_identity(parent),
                    resolved_identity=os.path.normcase(os.fspath(resolved)),
                    physical_identity=followed_identity,
                    directory_type=stat.S_IFMT(followed.st_mode),
                    link_or_reparse=False,
                    mode=stat.S_IMODE(followed.st_mode),
                )
            )
    except (OSError, RuntimeError):
        return (), {"code": "source_parent_unreadable", "source": source}
    return tuple(snapshots), None


def _capture_source_path_binding(
    path: Path,
    source: str,
) -> tuple[tuple[str, tuple[int, int], tuple[int, int, int]] | None, dict[str, object] | None]:
    try:
        if _path_is_link_or_reparse(path):
            return None, {"code": "source_changed_during_snapshot", "source": source}
        checked = os.stat(path, follow_symlinks=False)
        checked_attributes = getattr(checked, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(checked.st_mode) or bool(
            reparse_flag and checked_attributes & reparse_flag
        ):
            return None, {"code": "source_changed_during_snapshot", "source": source}
        resolved = path.resolve(strict=True)
        followed = os.stat(path, follow_symlinks=True)
    except (OSError, RuntimeError):
        return None, {"code": "source_changed_during_snapshot", "source": source}
    checked_identity = (int(checked.st_dev), int(checked.st_ino))
    followed_identity = (int(followed.st_dev), int(followed.st_ino))
    checked_metadata = (
        int(checked.st_size),
        int(checked.st_mtime_ns),
        stat.S_IMODE(checked.st_mode),
    )
    followed_metadata = (
        int(followed.st_size),
        int(followed.st_mtime_ns),
        stat.S_IMODE(followed.st_mode),
    )
    if checked_identity != followed_identity or checked_metadata != followed_metadata:
        return None, {"code": "source_changed_during_snapshot", "source": source}
    return (
        (
            os.path.normcase(os.fspath(resolved)),
            followed_identity,
            followed_metadata,
        ),
        None,
    )


def _capture_source_snapshot(path: Path, source: str) -> tuple[SourceSnapshot | None, dict[str, object] | None]:
    parent_chain_before, parent_chain_blocker = _capture_source_parent_chain(path, source)
    if parent_chain_blocker is not None:
        return None, parent_chain_blocker
    parent_blocker = _source_parent_link_blocker(path, source)
    if parent_blocker is not None:
        return None, parent_blocker
    if _path_is_link_or_reparse(path):
        return None, {"code": "source_symlink", "source": source}
    try:
        checked = os.stat(path, follow_symlinks=False)
        checked_attributes = getattr(checked, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(checked.st_mode) or bool(
            reparse_flag and checked_attributes & reparse_flag
        ):
            return None, {"code": "source_symlink", "source": source}
        resolved = path.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(os.fspath(path), flags)
        try:
            before = os.fstat(descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                payload = stream.read()
            after = os.stat(path, follow_symlinks=False)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileNotFoundError:
        return None, {"code": "source_missing", "source": source}
    except (OSError, RuntimeError):
        return None, {"code": "source_unreadable", "source": source}
    checked_identity = (int(checked.st_dev), int(checked.st_ino))
    before_identity = (int(before.st_dev), int(before.st_ino))
    after_identity = (int(after.st_dev), int(after.st_ino))
    checked_metadata = (int(checked.st_size), int(checked.st_mtime_ns), stat.S_IMODE(checked.st_mode))
    before_metadata = (int(before.st_size), int(before.st_mtime_ns), stat.S_IMODE(before.st_mode))
    after_metadata = (int(after.st_size), int(after.st_mtime_ns), stat.S_IMODE(after.st_mode))
    if (
        checked_identity != before_identity
        or before_identity != after_identity
        or checked_metadata != before_metadata
        or before_metadata != after_metadata
        or int(before.st_size) != len(payload)
    ):
        return None, {"code": "source_changed_during_snapshot", "source": source}
    parent_chain_after, parent_chain_blocker = _capture_source_parent_chain(path, source)
    if parent_chain_blocker is not None:
        return None, parent_chain_blocker
    if parent_chain_before != parent_chain_after:
        return None, {"code": "source_parent_changed_during_snapshot", "source": source}
    opened_binding = (
        os.path.normcase(os.fspath(resolved)),
        after_identity,
        after_metadata,
    )
    final_binding, final_binding_blocker = _capture_source_path_binding(path, source)
    if final_binding_blocker is not None:
        return None, final_binding_blocker
    if final_binding != opened_binding:
        return None, {"code": "source_changed_during_snapshot", "source": source}
    parent_chain_closing, parent_chain_blocker = _capture_source_parent_chain(path, source)
    if parent_chain_blocker is not None:
        return None, parent_chain_blocker
    if parent_chain_before != parent_chain_closing:
        return None, {"code": "source_parent_changed_during_snapshot", "source": source}
    closing_binding, closing_binding_blocker = _capture_source_path_binding(path, source)
    if closing_binding_blocker is not None:
        return None, closing_binding_blocker
    if closing_binding != opened_binding:
        return None, {"code": "source_changed_during_snapshot", "source": source}
    return (
        SourceSnapshot(
            source=source,
            path=path,
            payload=payload,
            digest=hashlib.sha256(payload).hexdigest(),
            resolved_identity=os.path.normcase(os.fspath(resolved)),
            physical_identity=after_identity,
            metadata=after_metadata,
        ),
        None,
    )


def _capture_source_snapshots(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
) -> tuple[dict[str, SourceSnapshot], list[dict[str, object]]]:
    return _capture_bound_source_snapshots(
        (
            (COMPOSE_SOURCE, compose_path),
            (MANAGED_SOURCE, managed_env_path),
            (SECRET_SOURCE, secret_env_path),
            (POSTGRES_SOURCE, postgres_env_path),
        ),
        alias_blocker_code="migration_source_path_alias",
    )


def _capture_bound_source_snapshots(
    source_paths: Sequence[tuple[str, Path]],
    *,
    alias_blocker_code: str,
) -> tuple[dict[str, SourceSnapshot], list[dict[str, object]]]:
    snapshots: dict[str, SourceSnapshot] = {}
    blockers: list[dict[str, object]] = []
    for source, path in source_paths:
        snapshot, blocker = _capture_source_snapshot(path, source)
        if blocker is not None:
            blockers.append(blocker)
        elif snapshot is not None:
            snapshots[source] = snapshot

    snapshot_items = list(snapshots.items())
    for index, (left_source, left) in enumerate(snapshot_items):
        for right_source, right in snapshot_items[index + 1 :]:
            same_physical_file = (
                left.resolved_identity == right.resolved_identity
                or left.physical_identity == right.physical_identity
            )
            if not same_physical_file:
                try:
                    same_physical_file = os.path.samefile(left.path, right.path)
                except (OSError, RuntimeError):
                    same_physical_file = False
            if same_physical_file:
                blockers.append(
                    {
                        "code": alias_blocker_code,
                        "sources": sorted((left_source, right_source)),
                    }
                )
    return snapshots, blockers


def _normalize_compose_env_file_source(raw: str, *, compose_parent: Path) -> str | None:
    scalar = _strip_yaml_scalar(raw)
    if not scalar or any(marker in scalar for marker in ("$", "%", "~", "\x00")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", scalar) and not re.match(r"^[A-Za-z]:[\\/]", scalar):
        return None
    return _normalized_path_identity(Path(scalar), relative_to=compose_parent)


def _decode_runtime_env_file_rhs(raw_rhs: str) -> str:
    """Decode the explicit Compose ``env_file`` value subset used by this guard.

    Single-quoted values are literal and only ``\\'`` decodes to a quote; this
    keeps ``#``, surrounding spaces, dollar interpolation markers, double
    quotes, and every other backslash literal.  Double-quoted values accept the
    documented newline/tab/return, quote, and backslash escapes.  Unquoted
    values trim surrounding horizontal whitespace and recognize a whitespace-
    preceded inline comment.  Unsupported quote/trailer/escape forms are never
    guessed.
    """

    text = raw_rhs.lstrip(" \t")
    if not text:
        return ""

    if text[0] == "'":
        decoded: list[str] = []
        cursor = 1
        while cursor < len(text):
            character = text[cursor]
            if character == "\\" and cursor + 1 < len(text) and text[cursor + 1] == "'":
                decoded.append("'")
                cursor += 2
                continue
            if character == "'":
                remainder = text[cursor + 1 :]
                if remainder and not remainder.startswith((" ", "\t")):
                    raise ValueError("unsupported env_file single-quote trailer")
                trailer = remainder.lstrip(" \t")
                if trailer and not trailer.startswith("#"):
                    raise ValueError("unsupported env_file single-quote trailer")
                return "".join(decoded)
            decoded.append(character)
            cursor += 1
        raise ValueError("unterminated env_file single quote")

    if text[0] == '"':
        escape_map = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        decoded = []
        cursor = 1
        while cursor < len(text):
            character = text[cursor]
            if character == '"':
                remainder = text[cursor + 1 :]
                if remainder and not remainder.startswith((" ", "\t")):
                    raise ValueError("unsupported env_file double-quote trailer")
                trailer = remainder.lstrip(" \t")
                if trailer and not trailer.startswith("#"):
                    raise ValueError("unsupported env_file double-quote trailer")
                return "".join(decoded)
            if character != "\\":
                decoded.append(character)
                cursor += 1
                continue
            cursor += 1
            if cursor >= len(text) or text[cursor] not in escape_map:
                raise ValueError("unsupported env_file double-quote escape")
            decoded.append(escape_map[text[cursor]])
            cursor += 1
        raise ValueError("unterminated env_file double quote")

    unquoted = text.rstrip(" \t")
    for index, character in enumerate(unquoted):
        if character == "#" and index > 0 and unquoted[index - 1].isspace():
            return unquoted[:index].rstrip(" \t")
    return unquoted


def _runtime_env_value_is_representable(value: str) -> bool:
    return not any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    )


def _runtime_env_file_rhs_style(raw_rhs: str) -> str:
    text = raw_rhs.lstrip(" \t")
    if text.startswith("'"):
        return "single_quoted"
    if text.startswith('"'):
        return "double_quoted"
    return "unquoted"


def _encode_runtime_env_file_literal(value: str) -> str:
    """Encode a reversible, non-interpolating Compose env_file scalar."""

    if not _runtime_env_value_is_representable(value):
        raise ValueError("env_file value contains an unsafe control character")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("env_file value is not UTF-8 encodable") from error
    encoded = "'" + value.replace("'", "\\'") + "'"
    if _decode_runtime_env_file_rhs(encoded) != value:
        raise ValueError("env_file literal round trip failed")
    return encoded


def _parse_env_payload(payload: bytes, source: str) -> tuple[list[Declaration], list[dict[str, object]]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError:
        return [], [{"code": "source_unreadable", "source": source}]

    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        if character == "\n":
            cursor += 1
            continue
        if character == "\r":
            if cursor + 1 >= len(text) or text[cursor + 1] != "\n":
                return [], [{"code": "invalid_env_syntax", "source": source}]
            cursor += 2
            continue
        if unicodedata.category(character) in {"Cc", "Zl", "Zp"}:
            return [], [{"code": "invalid_env_syntax", "source": source}]
        cursor += 1
    lines = text.splitlines()

    blockers: list[dict[str, object]] = []
    declarations: list[Declaration] = []
    for line_number, line in enumerate(lines, start=1):
        if line_number == 1 and line.startswith("\ufeff"):
            line = line[1:]
        structural = line.strip()
        if not structural or structural.startswith("#"):
            continue
        assignment = line.lstrip(" \t")
        if "=" not in assignment:
            blockers.append({"code": "invalid_env_syntax", "source": source, "line": line_number})
            continue
        raw_key, raw_rhs = assignment.split("=", 1)
        key = raw_key.strip(" \t")
        if not KEY_PATTERN.fullmatch(key):
            blockers.append({"code": "invalid_env_key", "source": source, "line": line_number})
            continue
        try:
            private_value = _decode_runtime_env_file_rhs(raw_rhs)
        except ValueError:
            blockers.append({"code": "invalid_env_syntax", "source": source, "line": line_number})
            continue
        declarations.append(
            Declaration(
                key=key,
                source=source,
                line_number=line_number,
                private_value=private_value,
                private_raw_rhs=raw_rhs,
                private_value_style=_runtime_env_file_rhs_style(raw_rhs),
            )
        )
    return declarations, blockers


def _parse_env_file(path: Path, source: str) -> tuple[list[Declaration], list[dict[str, object]]]:
    path_blocker = _input_path_blocker(path, source)
    if path_blocker is not None:
        return [], [path_blocker]
    if not path.is_file():
        return [], [{"code": "source_missing", "source": source}]
    try:
        payload = path.read_bytes()
    except OSError:
        return [], [{"code": "source_unreadable", "source": source}]
    return _parse_env_payload(payload, source)


def _parse_compose(
    path: Path,
    *,
    payload: bytes | None = None,
    runtime_path: Path | None = None,
) -> ComposeParseResult:
    if payload is None:
        path_blocker = _input_path_blocker(path, COMPOSE_SOURCE)
        if path_blocker is not None:
            return ComposeParseResult((), (path_blocker,), 0, (), (), ())
        if not path.is_file():
            return ComposeParseResult((), ({"code": "source_missing", "source": COMPOSE_SOURCE},), 0, (), (), ())
    try:
        lines = (
            path.read_text(encoding="utf-8").splitlines()
            if payload is None
            else payload.decode("utf-8").splitlines()
        )
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
            mapping_match = COMPOSE_MAPPING_PATTERN.fullmatch(stripped)
            if mapping_match is not None:
                key, raw_private_value = mapping_match.groups()
                if not _is_unambiguous_compose_environment_scalar(raw_private_value or ""):
                    blockers.append(
                        {
                            "code": "non_scalar_compose_environment_value",
                            "key": key,
                            "source": f"{COMPOSE_SOURCE}:{current_service}",
                            "line": line_number,
                        }
                    )
                    continue
                private_value = _strip_yaml_scalar(raw_private_value or "")
                compose_container = "mapping"
                compose_scalar_style = _yaml_scalar_value_style(raw_private_value or "")
            else:
                raw_list_match = re.fullmatch(r"-\s*(.+)", stripped)
                supported_list_item = False
                decoded_list_item = ""
                raw_list_item = ""
                if raw_list_match is not None:
                    raw_list_item = raw_list_match.group(1)
                    supported_list_item, decoded_list_item = _decode_yaml_scalar(raw_list_item)
                if (
                    not supported_list_item
                    or "=" not in decoded_list_item
                ):
                    blockers.append(
                        {
                            "code": "invalid_compose_environment_syntax",
                            "source": f"{COMPOSE_SOURCE}:{current_service}",
                            "line": line_number,
                        }
                    )
                    continue
                key, private_value = decoded_list_item.split("=", 1)
                if KEY_PATTERN.fullmatch(key) is None:
                    blockers.append(
                        {
                            "code": "invalid_compose_environment_syntax",
                            "source": f"{COMPOSE_SOURCE}:{current_service}",
                            "line": line_number,
                        }
                    )
                    continue
                compose_container = "list"
                compose_scalar_style = _yaml_scalar_value_style(raw_list_item)
            if not key:
                blockers.append(
                    {
                        "code": "invalid_compose_environment_syntax",
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
                    private_value=private_value,
                    service_occurrence=current_service_occurrence,
                    environment_block_occurrence=current_environment_block,
                    compose_environment_container=compose_container,
                    compose_scalar_style=compose_scalar_style,
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
                _normalize_compose_env_file_source(
                    env_file_entry.group(1),
                    compose_parent=(runtime_path if runtime_path is not None else path).parent,
                )
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


def _resource_override_scalar_is_safe(key: str, raw: str, *, bucket: str) -> bool:
    scalar = _strip_yaml_comment(raw).strip()
    if not scalar or scalar.startswith(("[", "{", "|", ">", "&", "*", "!")):
        return False
    if scalar[0] in {'"', "'"}:
        if len(scalar) < 2 or scalar[-1] != scalar[0]:
            return False
        scalar = scalar[1:-1]
    elif '"' in scalar or "'" in scalar:
        return False

    if key == "cpus":
        if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,3})?", scalar) is None:
            return False
        value = float(scalar)
        return 0.001 <= value <= 64.0
    if key == "pids":
        return bucket == "limits" and bool(re.fullmatch(r"[1-9][0-9]{0,6}", scalar)) and int(scalar) <= 1_048_576
    if key == "memory":
        match = re.fullmatch(r"([1-9][0-9]*)([kmgt]i?b?|b)?", scalar, flags=re.IGNORECASE)
        if match is None:
            return False
        unit = (match.group(2) or "b").casefold()
        multipliers = {
            "b": 1,
            "k": 1_000,
            "kb": 1_000,
            "ki": 1_024,
            "kib": 1_024,
            "m": 1_000_000,
            "mb": 1_000_000,
            "mi": 1_048_576,
            "mib": 1_048_576,
            "g": 1_000_000_000,
            "gb": 1_000_000_000,
            "gi": 1_073_741_824,
            "gib": 1_073_741_824,
            "t": 1_000_000_000_000,
            "tb": 1_000_000_000_000,
            "ti": 1_099_511_627_776,
            "tib": 1_099_511_627_776,
        }
        byte_count = int(match.group(1)) * multipliers[unit]
        return 16_000_000 <= byte_count <= 1_099_511_627_776
    return False


def _parse_compose_override(path: Path, *, occurrence: int) -> list[dict[str, object]]:
    """Accept only a narrow, literal deploy.resources cost-saver overlay."""

    source = f"{COMPOSE_OVERRIDE_SOURCE}:{occurrence}"
    snapshot, snapshot_blocker = _capture_source_snapshot(path, source)
    if snapshot_blocker is not None:
        return [snapshot_blocker]
    if snapshot is None:
        return [{"code": "source_unreadable", "source": source}]
    try:
        lines = snapshot.payload.decode("utf-8").splitlines()
    except UnicodeError:
        return [{"code": "source_unreadable", "source": source}]

    blockers: list[dict[str, object]] = []
    meaningful: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        leading = line[: len(line) - len(line.lstrip())]
        stripped = _strip_yaml_comment(line)
        if "\t" in leading or re.search(r"(?:^|[\s:{\[,])(?:<<\s*:|[&*!][^\s]*)", stripped):
            blockers.append({"code": "ambiguous_compose_override", "source": source, "line": line_number})
            continue
        meaningful.append((line_number, len(leading), stripped))

    services_lines = [line_number for line_number, indent, text in meaningful if indent == 0 and text == "services:"]
    if len(services_lines) != 1:
        blockers.append(
            {
                "code": "invalid_compose_override_services",
                "source": source,
                "count": len(services_lines),
            }
        )

    current_service: str | None = None
    current_bucket: str | None = None
    current_deploy = False
    current_resources = False
    seen_services: set[str] = set()
    seen_paths: set[tuple[str, ...]] = set()
    resource_scalar_count = 0
    for line_number, indent, text in meaningful:
        if indent == 0:
            if text != "services:":
                blockers.append(
                    {
                        "code": "unsafe_compose_override",
                        "source": source,
                        "reason": "top_level_key_not_allowed",
                        "line": line_number,
                    }
                )
            continue

        mapping = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*", text)
        if mapping is None:
            blockers.append({"code": "ambiguous_compose_override", "source": source, "line": line_number})
            continue
        key, tail = mapping.groups()

        if indent == 2:
            current_service = key if key in RUNTIME_SERVICE_NAMES else None
            current_bucket = None
            current_deploy = False
            current_resources = False
            if key not in RUNTIME_SERVICE_NAMES or tail:
                blockers.append(
                    {
                        "code": "ambiguous_compose_override_service" if key in RUNTIME_SERVICE_NAMES else "unsafe_compose_override",
                        "source": source,
                        "reason": "runtime_service_declaration_required",
                        "line": line_number,
                    }
                )
                continue
            if key in seen_services:
                blockers.append({"code": "duplicate_compose_override_service", "source": source, "service": key})
            seen_services.add(key)
            continue

        if current_service is None:
            blockers.append({"code": "ambiguous_compose_override", "source": source, "line": line_number})
            continue

        if indent <= 4:
            current_deploy = False
            current_resources = False
            current_bucket = None
        elif indent <= 6:
            current_resources = False
            current_bucket = None
        elif indent <= 8:
            current_bucket = None

        expected: tuple[int, str, tuple[str, ...]] | None = None
        if indent == 4 and key == "deploy" and not tail:
            current_deploy = True
            expected = (4, key, (current_service, "deploy"))
        elif indent == 6 and current_deploy and key == "resources" and not tail:
            current_resources = True
            expected = (6, key, (current_service, "deploy", "resources"))
        elif indent == 8 and current_resources and key in {"limits", "reservations"} and not tail:
            current_bucket = key
            expected = (8, key, (current_service, "deploy", "resources", key))
        elif indent == 10 and current_bucket is not None and key in {"cpus", "memory", "pids"}:
            expected = (10, key, (current_service, "deploy", "resources", current_bucket, key))
            if _resource_override_scalar_is_safe(key, tail, bucket=current_bucket):
                resource_scalar_count += 1
            else:
                blockers.append(
                    {
                        "code": "unsafe_compose_override",
                        "source": source,
                        "service": current_service,
                        "reason": "invalid_resource_scalar",
                        "line": line_number,
                    }
                )
        else:
            blockers.append(
                {
                    "code": "unsafe_compose_override",
                    "source": source,
                    "service": current_service,
                    "reason": "resource_key_not_allowed",
                    "line": line_number,
                }
            )
            continue

        path_key = expected[2]
        if path_key in seen_paths:
            blockers.append(
                {
                    "code": "ambiguous_compose_override",
                    "source": source,
                    "service": current_service,
                    "reason": "duplicate_resource_key",
                    "line": line_number,
                }
            )
        seen_paths.add(path_key)

    if not seen_services:
        blockers.append({"code": "invalid_compose_override_services", "source": source, "count": 0})
    if resource_scalar_count == 0:
        blockers.append({"code": "invalid_compose_override_resources", "source": source, "count": 0})
    return blockers


def _owner_for_key(key: str) -> str | None:
    # Exact ownership is intentionally evaluated before broad domain prefixes.
    # This keeps evidence-driven exceptions stable as the prefix registry grows.
    if key in COMPOSE_OWNED_KEYS:
        return COMPOSE_SOURCE
    if key in MANAGED_EXACT_KEYS:
        return MANAGED_SOURCE
    if key in POSTGRES_EXACT_KEYS:
        return POSTGRES_SOURCE
    if key in SECRET_EXACT_KEYS:
        return SECRET_SOURCE
    if key.startswith(MANAGED_PREFIXES):
        return MANAGED_SOURCE
    if key.startswith(POSTGRES_PREFIXES):
        return POSTGRES_SOURCE
    if key.startswith("JIEJING_") and key.endswith(SECRET_CREDENTIAL_SUFFIXES):
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


def _normalize_required_runtime_services(
    required_runtime_services: Sequence[str] | None,
) -> frozenset[str]:
    if not required_runtime_services:
        return RUNTIME_SERVICE_NAMES
    normalized = frozenset(required_runtime_services)
    invalid = normalized - RUNTIME_SERVICE_NAMES
    if invalid:
        raise ValueError("required runtime service is not allowed")
    return normalized


def analyze_runtime_env_ownership(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    compose_runtime_path: Path | None = None,
    managed_runtime_path: Path | None = None,
    secret_runtime_path: Path | None = None,
    postgres_runtime_path: Path | None = None,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
    _source_snapshots: Mapping[str, SourceSnapshot] | None = None,
    _snapshot_blockers: Sequence[dict[str, object]] = (),
) -> GuardAnalysis:
    required_services = _normalize_required_runtime_services(required_runtime_services)
    declarations: list[Declaration] = []
    blockers: list[dict[str, object]] = list(_snapshot_blockers)
    for parser, path, source in (
        (_parse_env_file, managed_env_path, MANAGED_SOURCE),
        (_parse_env_file, secret_env_path, SECRET_SOURCE),
        (_parse_env_file, postgres_env_path, POSTGRES_SOURCE),
    ):
        if _source_snapshots is not None:
            snapshot = _source_snapshots.get(source)
            if snapshot is None:
                continue
            parsed, parse_blockers = _parse_env_payload(snapshot.payload, source)
        else:
            parsed, parse_blockers = parser(path, source)
        declarations.extend(parsed)
        blockers.extend(parse_blockers)
    compose_snapshot = _source_snapshots.get(COMPOSE_SOURCE) if _source_snapshots is not None else None
    compose_result = (
        ComposeParseResult((), (), 0, (), (), ())
        if _source_snapshots is not None and compose_snapshot is None
        else _parse_compose(
            compose_path,
            payload=compose_snapshot.payload if compose_snapshot is not None else None,
            runtime_path=compose_runtime_path,
        )
    )
    declarations.extend(compose_result.declarations)
    blockers.extend(compose_result.blockers)
    for occurrence, override_path in enumerate(compose_override_paths, start=1):
        blockers.extend(_parse_compose_override(override_path, occurrence=occurrence))

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
    for required_service in sorted(required_services):
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
        if service_name not in required_services:
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
        ("managed", _normalized_path_identity(managed_runtime_path or managed_env_path)),
        ("secret", _normalized_path_identity(secret_runtime_path or secret_env_path)),
        ("postgres", _normalized_path_identity(postgres_runtime_path or postgres_env_path)),
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
        if service_name not in required_services:
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

    def exact_runtime_compose_values(key: str) -> dict[str, str] | None:
        key_analysis = key_analysis_by_key.get(key)
        if key_analysis is None:
            return None
        values: dict[str, str] = {}
        for service_name in required_services:
            service_declarations = [
                declaration
                for declaration in key_analysis.declarations
                if declaration.source == f"{COMPOSE_SOURCE}:{service_name}"
            ]
            if len(service_declarations) != 1:
                return None
            values[service_name] = service_declarations[0].private_value.strip().casefold()
        return values

    draft_save_values = exact_runtime_compose_values("JIEJING_EBAY_DRAFT_SAVE_LIVE")
    controlled_publish_values = exact_runtime_compose_values("JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE")
    real_write_policy_values = exact_runtime_compose_values("JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY")
    if controlled_publish_values is None:
        controlled_publish_values = {service_name: "false" for service_name in required_services}
    if (
        draft_save_values is not None
        and controlled_publish_values is not None
        and real_write_policy_values is not None
    ):
        if len(set(draft_save_values.values())) != 1:
            blockers.append(
                {
                    "code": "inconsistent_runtime_ebay_draft_save_value",
                    "source": COMPOSE_SOURCE,
                }
            )
        for service_name in sorted(required_services):
            expected_policy = (
                "controlled_existing_draft_publish"
                if controlled_publish_values[service_name] == "true"
                else "controlled_unpublished_draft_only"
                if draft_save_values[service_name] == "true"
                else "disabled_public_staging"
            )
            if real_write_policy_values[service_name] != expected_policy:
                blockers.append(
                    {
                        "code": "inconsistent_ebay_draft_save_policy",
                        "key": "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY",
                        "source": f"{COMPOSE_SOURCE}:{service_name}",
                        "service": service_name,
                    }
                )
        if any(value == "true" for value in controlled_publish_values.values()) and any(
            draft_save_values[service_name] != "true" for service_name in required_services
        ):
            blockers.append(
                {
                    "code": "controlled_publish_requires_draft_save",
                    "key": "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE",
                    "source": COMPOSE_SOURCE,
                }
            )
        if any(value == "true" for value in draft_save_values.values()):
            for prerequisite_key in (
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
                "JIEJING_EBAY_READ_ONLY_LIVE",
            ):
                prerequisite_analysis = key_analysis_by_key.get(prerequisite_key)
                prerequisite_declarations = (
                    [
                        declaration
                        for declaration in prerequisite_analysis.declarations
                        if declaration.source == SECRET_SOURCE
                    ]
                    if prerequisite_analysis is not None
                    else []
                )
                if len(prerequisite_declarations) != 1 or (
                    prerequisite_declarations[0].private_value.strip().casefold() != "true"
                ):
                    blockers.append(
                        {
                            "code": "ebay_draft_save_prerequisite_not_enabled",
                            "key": prerequisite_key,
                            "source": SECRET_SOURCE,
                        }
                    )
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
        if source_role == COMPOSE_SOURCE and declaration.key not in COMPOSE_OWNED_KEYS:
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
        elif (
            owner == COMPOSE_SOURCE
            and declaration.key in COMPOSE_REQUIRED_VALUES
            and declaration.private_value != COMPOSE_REQUIRED_VALUES[declaration.key]
        ):
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
        "ambiguous_compose_override",
        "ambiguous_compose_override_service",
        "duplicate_compose_env_file_block",
        "duplicate_compose_env_file_source",
        "duplicate_compose_environment_block",
        "duplicate_compose_override_service",
        "duplicate_compose_service",
        "duplicate_top_level_services",
        "ebay_draft_save_prerequisite_not_enabled",
        "invalid_compose_environment_syntax",
        "invalid_compose_indentation",
        "invalid_compose_override_services",
        "invalid_compose_override_resources",
        "invalid_compose_service_syntax",
        "inconsistent_ebay_draft_save_policy",
        "inconsistent_runtime_ebay_draft_save_value",
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
    compose_runtime_path: Path | None = None,
    managed_runtime_path: Path | None = None,
    secret_runtime_path: Path | None = None,
    postgres_runtime_path: Path | None = None,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
) -> dict[str, object]:
    return _project_public_report(
        analyze_runtime_env_ownership(
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
            compose_runtime_path=compose_runtime_path,
            managed_runtime_path=managed_runtime_path,
            secret_runtime_path=secret_runtime_path,
            postgres_runtime_path=postgres_runtime_path,
            compose_override_paths=compose_override_paths,
            required_runtime_services=required_runtime_services,
        )
    )


RESOLUTION_RESOLVABLE_BLOCKER_CODES = frozenset({"cross_source_duplicate", "wrong_source"})


def _public_role_for_source(source: str) -> str | None:
    if source == DONOR_COMPOSE_SOURCE:
        return "compose"
    return SOURCE_TO_ROLE.get(_source_role(source))


def _load_resolution_decisions(
    manifest_path: Path,
    *,
    payload: bytes | None = None,
) -> tuple[dict[str, ResolutionDecision], list[dict[str, object]]]:
    blockers: list[dict[str, object]] = []
    try:
        if payload is None:
            if manifest_path.is_symlink() or not manifest_path.is_file():
                return {}, [{"code": "resolution_manifest_unavailable"}]
            manifest_payload = manifest_path.read_text(encoding="utf-8")
        else:
            manifest_payload = payload.decode("utf-8")
        parsed_payload = json.loads(manifest_payload)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, [{"code": "resolution_manifest_invalid"}]
    if not isinstance(parsed_payload, dict) or set(parsed_payload) != {"schema_version", "decisions"}:
        return {}, [{"code": "resolution_manifest_schema_invalid"}]
    if parsed_payload.get("schema_version") != RESOLUTION_MANIFEST_SCHEMA_VERSION:
        blockers.append({"code": "resolution_manifest_version_invalid"})
    raw_decisions = parsed_payload.get("decisions")
    if not isinstance(raw_decisions, list):
        blockers.append({"code": "resolution_manifest_decisions_invalid"})
        return {}, blockers

    decisions: dict[str, ResolutionDecision] = {}
    for index, raw_decision in enumerate(raw_decisions, start=1):
        if not isinstance(raw_decision, dict) or not set(raw_decision).issubset(
            {"key", "authoritative_role", "donor_role", "resolution_action"}
        ) or not {"key", "authoritative_role"}.issubset(raw_decision):
            blockers.append(
                {"code": "resolution_decision_schema_invalid", "count": index}
            )
            continue
        key = raw_decision.get("key")
        authoritative_role = raw_decision.get("authoritative_role")
        donor_role = raw_decision.get("donor_role")
        resolution_action_present = "resolution_action" in raw_decision
        resolution_action = raw_decision.get("resolution_action")
        if not isinstance(key, str) or KEY_PATTERN.fullmatch(key) is None:
            blockers.append(
                {"code": "resolution_decision_key_invalid", "count": index}
            )
            continue
        if (
            not isinstance(authoritative_role, str)
            or authoritative_role not in PUBLIC_SOURCE_ROLES
        ):
            blockers.append(
                {"code": "resolution_decision_authoritative_role_invalid", "key": key}
            )
            continue
        if donor_role is not None and (
            not isinstance(donor_role, str) or donor_role not in PUBLIC_SOURCE_ROLES
        ):
            blockers.append(
                {"code": "resolution_decision_donor_role_invalid", "key": key}
            )
            continue
        if donor_role == authoritative_role:
            blockers.append(
                {"code": "resolution_decision_roles_not_distinct", "key": key}
            )
            continue
        if resolution_action_present and resolution_action != RETIRE_EQUAL_COMPOSE_DONOR_ACTION:
            blockers.append(
                {"code": "resolution_decision_action_invalid", "key": key}
            )
            continue
        if resolution_action is not None and (
            authoritative_role != "secret" or donor_role != "compose"
        ):
            blockers.append(
                {
                    "code": "resolution_decision_action_roles_invalid",
                    "key": key,
                    "authoritative_role": authoritative_role,
                    "donor_role": donor_role,
                }
            )
            continue
        if (
            resolution_action == RETIRE_EQUAL_COMPOSE_DONOR_ACTION
            and key not in RETIRE_EQUAL_COMPOSE_DONOR_KEYS
        ):
            blockers.append(
                {"code": "resolution_decision_action_key_invalid", "key": key}
            )
            continue
        if key in decisions:
            blockers.append({"code": "resolution_decision_duplicate", "key": key})
            continue
        decisions[key] = ResolutionDecision(
            key=key,
            authoritative_role=authoritative_role,
            donor_role=donor_role,
            resolution_action=resolution_action,
        )
    return decisions, blockers


def _resolution_topology_by_role(
    key_analysis: KeyAnalysis,
) -> dict[str, tuple[Declaration, ...]]:
    by_role: dict[str, list[Declaration]] = {}
    for declaration in key_analysis.declarations:
        role = _public_role_for_source(declaration.source)
        if role is not None:
            by_role.setdefault(role, []).append(declaration)
    return {role: tuple(declarations) for role, declarations in by_role.items()}


def _owner_declaration_count_is_exact(
    *,
    owner_role: str,
    declarations: Sequence[Declaration],
    required_runtime_services: frozenset[str],
) -> bool:
    if owner_role != "compose":
        return len(declarations) == 1
    if len(declarations) != len(required_runtime_services):
        return False
    return {
        declaration.source.removeprefix(f"{COMPOSE_SOURCE}:")
        for declaration in declarations
    } == set(required_runtime_services)


def _resolution_blocker_public_projection(
    blocker: Mapping[str, object],
) -> dict[str, object]:
    projected: dict[str, object] = {"code": str(blocker.get("code") or "resolution_blocked")}
    key = blocker.get("key")
    if isinstance(key, str) and KEY_PATTERN.fullmatch(key):
        projected["key"] = key
    source = blocker.get("source")
    if isinstance(source, str):
        source_role = _public_role_for_source(source)
        if source_role is not None:
            projected["source_role"] = source_role
    owner = blocker.get("owner")
    if isinstance(owner, str):
        target_role = SOURCE_TO_ROLE.get(owner)
        if target_role is not None:
            projected["target_role"] = target_role
    for role_field in ("authoritative_role", "donor_role", "source_role", "target_role"):
        role = blocker.get(role_field)
        if role in PUBLIC_SOURCE_ROLES:
            projected[role_field] = role
    count = blocker.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        projected["count"] = count
    comparison = blocker.get("comparison")
    if comparison in {"equal", "conflict"}:
        projected["comparison"] = comparison
    return projected


def _forbidden_private_value_is_covered_by_safe_compose_keep(
    blocker: Mapping[str, object],
    *,
    analysis_by_key: Mapping[str, KeyAnalysis],
    decisions: Mapping[str, ResolutionDecision],
    actions: Sequence[ResolutionAction],
    required_runtime_services: frozenset[str],
) -> bool:
    if blocker.get("code") != "forbidden_staging_value":
        return False
    key = blocker.get("key")
    source = blocker.get("source")
    if not isinstance(key, str) or not isinstance(source, str):
        return False
    source_role = _public_role_for_source(source)
    if source_role not in {"managed", "secret", "postgres"}:
        return False
    decision = decisions.get(key)
    if (
        decision is None
        or decision.authoritative_role != "compose"
        or decision.donor_role is not None
    ):
        return False
    required_value = COMPOSE_REQUIRED_VALUES.get(key)
    key_analysis = analysis_by_key.get(key)
    if required_value is None or key_analysis is None or key_analysis.owner != COMPOSE_SOURCE:
        return False
    topology = _resolution_topology_by_role(key_analysis)
    compose_declarations = topology.get("compose", ())
    if not _owner_declaration_count_is_exact(
        owner_role="compose",
        declarations=compose_declarations,
        required_runtime_services=required_runtime_services,
    ):
        return False
    if any(declaration.private_value != required_value for declaration in compose_declarations):
        return False
    planned_removal_count = sum(
        action.count
        for action in actions
        if action.key == key
        and action.action == "keep_authoritative_remove_wrong_source"
        and action.source_role == source_role
        and action.target_role == "compose"
    )
    offending_private_count = sum(
        1
        for declaration in topology.get(source_role, ())
        if declaration.private_value.strip().casefold()
        not in STAGING_VALUE_CONSTRAINTS.get(key, frozenset())
    )
    return offending_private_count > 0 and planned_removal_count >= offending_private_count


def _build_runtime_env_resolution(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    decision_manifest_path: Path,
    compose_runtime_path: Path | None = None,
    donor_compose_path: Path | None = None,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
) -> ResolutionExecutionPlan:
    """Build the value-free report and its private snapshot-bound execution form.

    The manifest records operator decisions only.  It cannot authorize or
    invoke migration apply, and this function never writes any input file.
    """

    normalized_required_services = _normalize_required_runtime_services(required_runtime_services)
    resolution_source_paths: list[tuple[str, Path]] = [
        (COMPOSE_SOURCE, compose_path),
        (MANAGED_SOURCE, managed_env_path),
        (SECRET_SOURCE, secret_env_path),
        (POSTGRES_SOURCE, postgres_env_path),
        (RESOLUTION_MANIFEST_SOURCE, decision_manifest_path),
    ]
    if donor_compose_path is not None:
        resolution_source_paths.append((DONOR_COMPOSE_SOURCE, donor_compose_path))
    resolution_source_paths.extend(
        (f"{COMPOSE_OVERRIDE_SOURCE}:{occurrence}", override_path)
        for occurrence, override_path in enumerate(compose_override_paths, start=1)
    )
    source_snapshots, snapshot_blockers = _capture_bound_source_snapshots(
        tuple(resolution_source_paths),
        alias_blocker_code="resolution_source_path_alias",
    )
    desired_source_snapshots = {
        source: snapshot
        for source, snapshot in source_snapshots.items()
        if source in {COMPOSE_SOURCE, MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}
    }
    analysis = analyze_runtime_env_ownership(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
        compose_runtime_path=compose_runtime_path,
        compose_override_paths=compose_override_paths,
        required_runtime_services=tuple(normalized_required_services),
        _source_snapshots=desired_source_snapshots,
        _snapshot_blockers=snapshot_blockers,
    )
    manifest_snapshot = source_snapshots.get(RESOLUTION_MANIFEST_SOURCE)
    decisions, manifest_blockers = (
        _load_resolution_decisions(
            decision_manifest_path,
            payload=manifest_snapshot.payload,
        )
        if manifest_snapshot is not None
        else ({}, [])
    )
    blockers: list[dict[str, object]] = [
        dict(blocker)
        for blocker in analysis.blockers
        if blocker.get("code") not in RESOLUTION_RESOLVABLE_BLOCKER_CODES
    ]
    blockers.extend(manifest_blockers)
    actions: list[ResolutionAction] = []
    consumed_decisions: set[str] = set()
    analysis_by_key = {key_analysis.key: key_analysis for key_analysis in analysis.keys}

    compose_donor_decisions = {
        key: decision
        for key, decision in decisions.items()
        if decision.donor_role == "compose"
    }
    donor_declarations_by_key: dict[str, list[Declaration]] = {}
    donor_analysis: GuardAnalysis | None = None
    if donor_compose_path is None:
        if compose_donor_decisions:
            blockers.append({"code": "resolution_donor_compose_required", "source_role": "compose"})
    else:
        donor_snapshot = source_snapshots.get(DONOR_COMPOSE_SOURCE)
        donor_source_snapshots = {
            source: snapshot
            for source, snapshot in source_snapshots.items()
            if source in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}
        }
        if donor_snapshot is not None:
            donor_source_snapshots[COMPOSE_SOURCE] = donor_snapshot
        donor_analysis = analyze_runtime_env_ownership(
            compose_path=donor_compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
            compose_override_paths=(),
            required_runtime_services=tuple(normalized_required_services),
            _source_snapshots=donor_source_snapshots,
        )
        blockers.extend(
            dict(blocker)
            for blocker in donor_analysis.blockers
            if _is_compose_contract_blocker(dict(blocker))
            and blocker.get("code") not in {"cross_source_duplicate", "wrong_source"}
        )
        for declaration in donor_analysis.declarations:
            if _source_role(declaration.source) != COMPOSE_SOURCE:
                continue
            donor_declarations_by_key.setdefault(declaration.key, []).append(declaration)

    for key, decision in sorted(compose_donor_decisions.items()):
        consumed_decisions.add(key)
        owner_source = _owner_for_key(key)
        owner_role = SOURCE_TO_ROLE.get(owner_source or "")
        if owner_role is None:
            blockers.append({"code": "resolution_decision_unknown_key", "key": key})
            continue
        if decision.authoritative_role != owner_role:
            blockers.append(
                {
                    "code": "resolution_decision_owner_mismatch",
                    "key": key,
                    "authoritative_role": decision.authoritative_role,
                    "target_role": owner_role,
                }
            )
            continue
        if owner_role == "compose":
            blockers.append(
                {
                    "code": "resolution_donor_target_role_invalid",
                    "key": key,
                    "donor_role": "compose",
                    "target_role": owner_role,
                }
            )
            continue
        desired_key_analysis = analysis_by_key.get(key)
        desired_topology = (
            _resolution_topology_by_role(desired_key_analysis)
            if desired_key_analysis is not None
            else {}
        )
        if decision.resolution_action == RETIRE_EQUAL_COMPOSE_DONOR_ACTION:
            candidate_declarations = desired_topology.get("compose", ())
            if candidate_declarations:
                blockers.append(
                    {
                        "code": "resolution_retire_candidate_declaration_present",
                        "key": key,
                        "source_role": "compose",
                        "target_role": owner_role,
                        "count": len(candidate_declarations),
                    }
                )
                continue
            owner_declarations = desired_topology.get(owner_role, ())
            if not owner_declarations:
                blockers.append(
                    {
                        "code": "resolution_retire_authoritative_owner_missing",
                        "key": key,
                        "target_role": owner_role,
                        "count": 0,
                    }
                )
                continue
            if set(desired_topology) != {owner_role} or not _owner_declaration_count_is_exact(
                owner_role=owner_role,
                declarations=owner_declarations,
                required_runtime_services=normalized_required_services,
            ):
                blockers.append(
                    {
                        "code": "resolution_retire_desired_topology_invalid",
                        "key": key,
                        "target_role": owner_role,
                        "count": len(desired_key_analysis.declarations),
                    }
                )
                continue
        elif desired_key_analysis is not None and desired_key_analysis.declarations:
            blockers.append(
                {
                    "code": "resolution_donor_target_topology_not_empty",
                    "key": key,
                    "donor_role": "compose",
                    "target_role": owner_role,
                    "count": len(desired_key_analysis.declarations),
                }
            )
            continue
        donor_declarations = tuple(donor_declarations_by_key.get(key, ()))
        if not donor_declarations:
            blockers.append(
                {
                    "code": "resolution_compose_donor_missing",
                    "key": key,
                    "donor_role": "compose",
                    "target_role": owner_role,
                    "count": 0,
                }
            )
            continue
        donor_service_counts: dict[str, int] = {}
        for declaration in donor_declarations:
            service_name = declaration.source.removeprefix(f"{COMPOSE_SOURCE}:")
            donor_service_counts[service_name] = donor_service_counts.get(service_name, 0) + 1
        if set(donor_service_counts) != set(normalized_required_services) or any(
            count != 1 for count in donor_service_counts.values()
        ):
            blockers.append(
                {
                    "code": "resolution_compose_donor_service_topology_invalid",
                    "key": key,
                    "donor_role": "compose",
                    "target_role": owner_role,
                    "count": len(donor_declarations),
                }
            )
            continue
        donor_comparison = _comparison(donor_declarations)
        if donor_comparison != "equal":
            blockers.append(
                {
                    "code": "resolution_compose_donor_conflict",
                    "key": key,
                    "donor_role": "compose",
                    "target_role": owner_role,
                    "count": len(donor_declarations),
                    "comparison": donor_comparison,
                }
            )
            continue
        if decision.resolution_action == RETIRE_EQUAL_COMPOSE_DONOR_ACTION:
            owner_declarations = desired_topology[owner_role]
            owner_donor_comparison = _comparison((*donor_declarations, *owner_declarations))
            if owner_donor_comparison != "equal":
                blockers.append(
                    {
                        "code": "resolution_retire_owner_donor_conflict",
                        "key": key,
                        "donor_role": "compose",
                        "target_role": owner_role,
                        "count": len(donor_declarations),
                        "comparison": owner_donor_comparison,
                    }
                )
                continue
            actions.append(
                ResolutionAction(
                    action=RETIRE_EQUAL_COMPOSE_DONOR_ACTION,
                    key=key,
                    source_role="compose",
                    target_role=owner_role,
                    count=len(donor_declarations),
                    comparison="equal",
                )
            )
            continue
        actions.append(
            ResolutionAction(
                action="move_equal_donors_to_authoritative",
                key=key,
                source_role="compose",
                target_role=owner_role,
                count=len(donor_declarations),
                comparison="equal",
            )
        )

    for key_analysis in analysis.keys:
        decision = decisions.get(key_analysis.key)
        if decision is not None and decision.donor_role == "compose":
            continue
        owner_source = key_analysis.owner
        topology = _resolution_topology_by_role(key_analysis)
        if owner_source is None:
            if decision is not None:
                consumed_decisions.add(key_analysis.key)
                blockers.append(
                    {"code": "resolution_decision_unknown_key", "key": key_analysis.key}
                )
            if key_analysis.unauthorized_duplicate:
                blockers.append(
                    {
                        "code": "resolution_unregistered_duplicate",
                        "key": key_analysis.key,
                        "comparison": key_analysis.comparison,
                    }
                )
            continue

        owner_role = SOURCE_TO_ROLE[owner_source]
        owner_declarations = topology.get(owner_role, ())
        wrong_topology = {
            role: declarations
            for role, declarations in topology.items()
            if role != owner_role
        }
        if decision is not None:
            consumed_decisions.add(key_analysis.key)
            if decision.authoritative_role != owner_role:
                blockers.append(
                    {
                        "code": "resolution_decision_owner_mismatch",
                        "key": key_analysis.key,
                        "authoritative_role": decision.authoritative_role,
                        "target_role": owner_role,
                    }
                )
                continue

        if wrong_topology and not owner_declarations:
            if decision is None:
                blockers.append(
                    {
                        "code": "resolution_move_decision_required",
                        "key": key_analysis.key,
                        "target_role": owner_role,
                    }
                )
                continue
            if owner_role == "compose":
                blockers.append(
                    {
                        "code": "resolution_compose_mutation_forbidden",
                        "key": key_analysis.key,
                        "target_role": owner_role,
                    }
                )
                continue
            if decision.donor_role is None:
                blockers.append(
                    {
                        "code": "resolution_missing_owner_requires_donor",
                        "key": key_analysis.key,
                        "target_role": owner_role,
                    }
                )
                continue
            donor_declarations = wrong_topology.get(decision.donor_role, ())
            if (
                decision.donor_role == "compose"
                or len(donor_declarations) != 1
                or len(key_analysis.declarations) != 1
            ):
                blockers.append(
                    {
                        "code": "resolution_donor_not_unique",
                        "key": key_analysis.key,
                        "donor_role": decision.donor_role,
                        "target_role": owner_role,
                        "count": len(donor_declarations),
                    }
                )
                continue
            actions.append(
                ResolutionAction(
                    action="move_unique_to_authoritative",
                    key=key_analysis.key,
                    source_role=decision.donor_role,
                    target_role=owner_role,
                    count=1,
                    comparison="conflict",
                )
            )
            continue

        if wrong_topology and owner_declarations:
            if not _owner_declaration_count_is_exact(
                owner_role=owner_role,
                declarations=owner_declarations,
                required_runtime_services=normalized_required_services,
            ):
                blockers.append(
                    {
                        "code": "resolution_owner_declaration_count_invalid",
                        "key": key_analysis.key,
                        "target_role": owner_role,
                        "count": len(owner_declarations),
                    }
                )
                continue
            invalid_wrong_role = next(
                (
                    role
                    for role, declarations in sorted(wrong_topology.items())
                    if role == "compose" or len(declarations) != 1
                ),
                None,
            )
            if invalid_wrong_role is not None:
                blockers.append(
                    {
                        "code": (
                            "resolution_compose_mutation_forbidden"
                            if invalid_wrong_role == "compose"
                            else "resolution_source_declaration_count_invalid"
                        ),
                        "key": key_analysis.key,
                        "source_role": invalid_wrong_role,
                        "target_role": owner_role,
                        "count": len(wrong_topology[invalid_wrong_role]),
                    }
                )
                continue
            if key_analysis.comparison == "equal":
                if decision is not None:
                    blockers.append(
                        {"code": "resolution_decision_stale", "key": key_analysis.key}
                    )
                    continue
                action_kind = "remove_equal_duplicate"
            else:
                if decision is None:
                    blockers.append(
                        {
                            "code": "resolution_conflict_decision_required",
                            "key": key_analysis.key,
                            "target_role": owner_role,
                            "comparison": "conflict",
                        }
                    )
                    continue
                if decision.donor_role is not None:
                    blockers.append(
                        {
                            "code": "resolution_keep_owner_donor_forbidden",
                            "key": key_analysis.key,
                            "donor_role": decision.donor_role,
                            "target_role": owner_role,
                        }
                    )
                    continue
                action_kind = "keep_authoritative_remove_wrong_source"
            for source_role, declarations in sorted(wrong_topology.items()):
                actions.append(
                    ResolutionAction(
                        action=action_kind,
                        key=key_analysis.key,
                        source_role=source_role,
                        target_role=owner_role,
                        count=len(declarations),
                        comparison=key_analysis.comparison,
                    )
                )
            continue

        if decision is not None:
            blockers.append({"code": "resolution_decision_stale", "key": key_analysis.key})

    for key in sorted(set(decisions) - consumed_decisions):
        blockers.append({"code": "resolution_decision_stale", "key": key})

    blockers = [
        blocker
        for blocker in blockers
        if not _forbidden_private_value_is_covered_by_safe_compose_keep(
            blocker,
            analysis_by_key=analysis_by_key,
            decisions=decisions,
            actions=actions,
            required_runtime_services=normalized_required_services,
        )
    ]
    public_blockers = [
        _resolution_blocker_public_projection(blocker)
        for blocker in blockers
    ]
    ordered_actions = sorted(
        actions,
        key=lambda action: (action.key, action.source_role, action.target_role, action.action),
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "operation": "resolution-plan",
        "mode": "dry_run",
        "ok": not public_blockers,
        "applied": False,
        "secret_exposed": False,
        "summary": {
            "action_count": len(ordered_actions),
            "blocker_count": len(public_blockers),
            "warning_count": len(analysis.warnings),
            "decision_count": len(decisions),
        },
        "actions": [
            {
                "action": action.action,
                "key": action.key,
                "source_role": action.source_role,
                "target_role": action.target_role,
                "count": action.count,
                "comparison": action.comparison,
            }
            for action in ordered_actions
        ],
        "blockers": public_blockers,
    }
    identity_payload = {
        "snapshots": [
            {
                "source": snapshot.source,
                "digest": snapshot.digest,
                "resolved_identity": snapshot.resolved_identity,
                "physical_identity": snapshot.physical_identity,
                "metadata": snapshot.metadata,
            }
            for snapshot in sorted(source_snapshots.values(), key=lambda item: item.source)
        ],
        "actions": [
            {
                "action": action.action,
                "key": action.key,
                "source_role": action.source_role,
                "target_role": action.target_role,
                "count": action.count,
                "comparison": action.comparison,
            }
            for action in ordered_actions
        ],
        "required_runtime_services": sorted(normalized_required_services),
        "compose_runtime_identity": (
            _normalized_path_identity(compose_runtime_path)
            if compose_runtime_path is not None
            else None
        ),
        "compose_override_identities": [
            _normalized_path_identity(path) for path in compose_override_paths
        ],
    }
    plan_identity = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ResolutionExecutionPlan(
        report=report,
        analysis=analysis,
        donor_analysis=donor_analysis,
        actions=tuple(ordered_actions),
        blockers=tuple(blockers),
        snapshots=tuple(source_snapshots.values()),
        required_runtime_services=normalized_required_services,
        compose_override_paths=tuple(compose_override_paths),
        compose_runtime_path=compose_runtime_path,
        plan_identity=plan_identity,
    )


def plan_runtime_env_resolution(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    decision_manifest_path: Path,
    compose_runtime_path: Path | None = None,
    donor_compose_path: Path | None = None,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
) -> dict[str, object]:
    """Prepare a value-free, non-mutating resolution plan."""

    return dict(
        _build_runtime_env_resolution(
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
            decision_manifest_path=decision_manifest_path,
            compose_runtime_path=compose_runtime_path,
            donor_compose_path=donor_compose_path,
            compose_override_paths=compose_override_paths,
            required_runtime_services=required_runtime_services,
        ).report
    )


def _resolution_apply_public_projection(
    plan_report: Mapping[str, object],
    *,
    mode: str,
    applied: bool,
    backup_count: int = 0,
    artifact_counts: Mapping[str, int] | None = None,
    additional_blockers: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    """Project a resolution apply result without keys or private input identity."""

    action_counts: dict[tuple[str, str, str], int] = {}
    for raw_action in plan_report.get("actions", ()):
        if not isinstance(raw_action, dict):
            continue
        action = str(raw_action.get("action") or "unknown")
        source_role = str(raw_action.get("source_role") or "unknown")
        target_role = str(raw_action.get("target_role") or "unknown")
        action_counts[(action, source_role, target_role)] = (
            action_counts.get((action, source_role, target_role), 0) + 1
        )
    blockers = []
    for blocker in (*plan_report.get("blockers", ()), *additional_blockers):
        if not isinstance(blocker, dict):
            continue
        projected = {
            field: blocker[field]
            for field in (
                "code",
                "source_role",
                "target_role",
                "authoritative_role",
                "donor_role",
                "count",
                "comparison",
            )
            if field in blocker
        }
        source = blocker.get("source")
        source_role = _public_role_for_source(str(source)) if source is not None else None
        if source_role is not None:
            projected["source_role"] = source_role
        blockers.append(projected)
    plan_summary = plan_report.get("summary", {})
    if not isinstance(plan_summary, dict):
        plan_summary = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "resolution-apply",
        "mode": mode,
        "ok": not blockers,
        "applied": applied,
        "secret_exposed": False,
        "summary": {
            "action_count": int(plan_summary.get("action_count") or 0),
            "action_summary_count": len(action_counts),
            "blocker_count": len(blockers),
            "warning_count": int(plan_summary.get("warning_count") or 0),
            "decision_count": int(plan_summary.get("decision_count") or 0),
            "backup_count": backup_count,
            "artifact_counts": dict(sorted((artifact_counts or {}).items())),
        },
        "actions": [
            {
                "action": action,
                "source_role": source_role,
                "target_role": target_role,
                "count": count,
            }
            for (action, source_role, target_role), count in sorted(action_counts.items())
        ],
        "blockers": blockers,
    }


def _resolution_migration_plan(
    plan: ResolutionExecutionPlan,
) -> MigrationPlan:
    """Bind resolution actions to opaque private mutations on captured snapshots."""

    snapshots_by_source = {snapshot.source: snapshot for snapshot in plan.snapshots}
    key_analyses = {key_analysis.key: key_analysis for key_analysis in plan.analysis.keys}
    migration_actions: list[MigrationAction] = []
    for action in plan.actions:
        compose_donor_declarations: tuple[Declaration, ...] = ()
        if action.source_role == "compose":
            compose_donor_declarations = tuple(
                declaration
                for declaration in (
                    plan.donor_analysis.declarations if plan.donor_analysis is not None else ()
                )
                if _source_role(declaration.source) == COMPOSE_SOURCE
                and declaration.key == action.key
            )
            donor_service_counts: dict[str, int] = {}
            for declaration in compose_donor_declarations:
                service_name = declaration.source.removeprefix(f"{COMPOSE_SOURCE}:")
                donor_service_counts[service_name] = donor_service_counts.get(service_name, 0) + 1
            if (
                len(compose_donor_declarations) != action.count
                or set(donor_service_counts) != set(plan.required_runtime_services)
                or any(count != 1 for count in donor_service_counts.values())
                or _comparison(compose_donor_declarations) != "equal"
            ):
                raise MigrationApplyError("resolution_apply_plan_stale", "migration")
            if any(
                declaration.compose_environment_container != "mapping"
                for declaration in compose_donor_declarations
            ):
                raise MigrationApplyError(
                    "resolution_apply_value_unrepresentable",
                    "migration",
                )
        if action.action == RETIRE_EQUAL_COMPOSE_DONOR_ACTION:
            if action.source_role != "compose":
                raise MigrationApplyError("resolution_apply_plan_stale", "migration")
            continue
        if action.action == "move_equal_donors_to_authoritative":
            target = ROLE_TO_SOURCE.get(action.target_role)
            if (
                action.source_role != "compose"
                or target not in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}
                or target not in snapshots_by_source
            ):
                raise MigrationApplyError("resolution_apply_plan_stale", "migration")
            donor_value = compose_donor_declarations[0].private_value
            if "$" in donor_value and any(
                declaration.compose_scalar_style != "single_quoted"
                for declaration in compose_donor_declarations
            ):
                raise MigrationApplyError(
                    "resolution_apply_value_unrepresentable",
                    "migration",
                )
            try:
                encoded_rhs = _encode_runtime_env_file_literal(donor_value)
            except ValueError as error:
                raise MigrationApplyError(
                    "resolution_apply_value_unrepresentable",
                    "migration",
                ) from error
            migration_actions.append(
                MigrationAction(
                    key=action.key,
                    source=target,
                    owner=action.target_role,
                    comparison=action.comparison,
                    bindings=(),
                    additions=(
                        AdditionBinding(
                            key=action.key,
                            private_value=donor_value,
                            encoded_rhs=encoded_rhs,
                        ),
                    ),
                )
            )
            continue
        if action.action not in {
            "remove_equal_duplicate",
            "keep_authoritative_remove_wrong_source",
            "move_unique_to_authoritative",
        }:
            raise MigrationApplyError("resolution_apply_action_unsupported", "migration")
        source = ROLE_TO_SOURCE.get(action.source_role)
        if source not in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}:
            raise MigrationApplyError("resolution_apply_source_forbidden", "migration")
        snapshot = snapshots_by_source.get(source)
        key_analysis = key_analyses.get(action.key)
        if snapshot is None or key_analysis is None:
            raise MigrationApplyError("resolution_apply_plan_stale", source)
        declarations = tuple(
            declaration
            for declaration in key_analysis.declarations
            if _source_role(declaration.source) == source
        )
        if len(declarations) != action.count:
            raise MigrationApplyError("resolution_apply_plan_stale", source)
        line_segments = snapshot.payload.splitlines(keepends=True)
        if any(
            declaration.line_number < 1 or declaration.line_number > len(line_segments)
            for declaration in declarations
        ):
            raise MigrationApplyError("resolution_apply_plan_stale", source)
        removal_bindings = tuple(
            RemovalBinding(
                line_number=declaration.line_number,
                key=declaration.key,
                line_digest=hashlib.sha256(
                    line_segments[declaration.line_number - 1]
                ).hexdigest(),
            )
            for declaration in declarations
        )
        removal_action = MigrationAction(
            key=action.key,
            source=source,
            owner=action.target_role,
            comparison=action.comparison,
            bindings=removal_bindings,
        )
        if action.action == "move_unique_to_authoritative":
            target = ROLE_TO_SOURCE.get(action.target_role)
            donor_declaration = declarations[0] if len(declarations) == 1 else None
            if (
                donor_declaration is None
                or target not in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}
                or target not in snapshots_by_source
                or donor_declaration.private_raw_rhs is None
            ):
                raise MigrationApplyError("resolution_apply_plan_stale", "migration")
            try:
                decoded_private_rhs = _decode_runtime_env_file_rhs(
                    donor_declaration.private_raw_rhs
                )
            except ValueError as error:
                raise MigrationApplyError(
                    "resolution_apply_value_unrepresentable",
                    "migration",
                ) from error
            if (
                decoded_private_rhs != donor_declaration.private_value
                or not _runtime_env_value_is_representable(decoded_private_rhs)
                or (
                    "$" in decoded_private_rhs
                    and donor_declaration.private_value_style != "single_quoted"
                )
            ):
                raise MigrationApplyError(
                    "resolution_apply_value_unrepresentable",
                    "migration",
                )
            addition_action = MigrationAction(
                key=action.key,
                source=target,
                owner=action.target_role,
                comparison=action.comparison,
                bindings=(),
                additions=(
                    AdditionBinding(
                        key=action.key,
                        private_value=donor_declaration.private_value,
                        encoded_rhs=donor_declaration.private_raw_rhs,
                    ),
                ),
            )
            migration_actions.extend((addition_action, removal_action))
        else:
            migration_actions.append(removal_action)
    compose_snapshot = snapshots_by_source.get(COMPOSE_SOURCE)
    managed_snapshot = snapshots_by_source.get(MANAGED_SOURCE)
    secret_snapshot = snapshots_by_source.get(SECRET_SOURCE)
    postgres_snapshot = snapshots_by_source.get(POSTGRES_SOURCE)
    manifest_snapshot = snapshots_by_source.get(RESOLUTION_MANIFEST_SOURCE)
    donor_snapshot = snapshots_by_source.get(DONOR_COMPOSE_SOURCE)
    if any(
        snapshot is None
        for snapshot in (
            compose_snapshot,
            managed_snapshot,
            secret_snapshot,
            postgres_snapshot,
            manifest_snapshot,
        )
    ):
        raise MigrationApplyError("resolution_apply_plan_stale", "migration")

    def pre_apply_validator() -> None:
        rebuilt = _build_runtime_env_resolution(
            compose_path=compose_snapshot.path,
            managed_env_path=managed_snapshot.path,
            secret_env_path=secret_snapshot.path,
            postgres_env_path=postgres_snapshot.path,
            decision_manifest_path=manifest_snapshot.path,
            compose_runtime_path=plan.compose_runtime_path,
            donor_compose_path=(donor_snapshot.path if donor_snapshot is not None else None),
            compose_override_paths=plan.compose_override_paths,
            required_runtime_services=tuple(plan.required_runtime_services),
        )
        if rebuilt.blockers or rebuilt.plan_identity != plan.plan_identity:
            raise MigrationApplyError("resolution_apply_plan_drift", "migration")

    def post_apply_validator() -> None:
        desired_snapshots, snapshot_blockers = _capture_source_snapshots(
            compose_path=compose_snapshot.path,
            managed_env_path=managed_snapshot.path,
            secret_env_path=secret_snapshot.path,
            postgres_env_path=postgres_snapshot.path,
        )
        validation = analyze_runtime_env_ownership(
            compose_path=compose_snapshot.path,
            managed_env_path=managed_snapshot.path,
            secret_env_path=secret_snapshot.path,
            postgres_env_path=postgres_snapshot.path,
            compose_runtime_path=plan.compose_runtime_path,
            compose_override_paths=plan.compose_override_paths,
            required_runtime_services=tuple(plan.required_runtime_services),
            _source_snapshots=desired_snapshots,
            _snapshot_blockers=snapshot_blockers,
        )
        if validation.blockers:
            raise MigrationApplyError("post_apply_validation_failed", "migration")

    return MigrationPlan(
        analysis=plan.analysis,
        actions=tuple(migration_actions),
        blockers=(),
        snapshots=plan.snapshots,
        required_runtime_services=plan.required_runtime_services,
        compose_override_paths=plan.compose_override_paths,
        pre_apply_validator=pre_apply_validator,
        post_apply_validator=post_apply_validator,
    )


def apply_runtime_env_resolution(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    decision_manifest_path: Path,
    compose_runtime_path: Path | None = None,
    donor_compose_path: Path | None = None,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
    confirm: str | None = None,
) -> dict[str, object]:
    """Dry-run unless the independent resolution confirmation is exact."""

    execution_plan = _build_runtime_env_resolution(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
        decision_manifest_path=decision_manifest_path,
        compose_runtime_path=compose_runtime_path,
        donor_compose_path=donor_compose_path,
        compose_override_paths=compose_override_paths,
        required_runtime_services=required_runtime_services,
    )
    plan_report = execution_plan.report
    if confirm is None:
        return _resolution_apply_public_projection(
            plan_report,
            mode="dry_run",
            applied=False,
        )
    if confirm != RESOLUTION_APPLY_CONFIRMATION:
        return _resolution_apply_public_projection(
            plan_report,
            mode="apply",
            applied=False,
            additional_blockers=({"code": "resolution_apply_confirmation_invalid"},),
        )
    if execution_plan.blockers:
        return _resolution_apply_public_projection(
            plan_report,
            mode="apply",
            applied=False,
        )
    try:
        migration_plan = _resolution_migration_plan(execution_plan)
        artifact_counts = _apply_migration_plan(
            migration_plan,
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
        )
    except MigrationApplyError as error:
        return _resolution_apply_public_projection(
            plan_report,
            mode="apply",
            applied=False,
            backup_count=error.backup_count,
            artifact_counts=error.artifact_counts,
            additional_blockers=error.blockers,
        )
    return _resolution_apply_public_projection(
        plan_report,
        mode="apply",
        applied=True,
        backup_count=sum(artifact_counts.values()),
        artifact_counts=artifact_counts,
    )


def plan_runtime_env_migration(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
) -> dict[str, object]:
    plan = _build_migration_plan(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
        compose_override_paths=compose_override_paths,
        required_runtime_services=required_runtime_services,
    )
    return _project_migration_report(plan, mode="dry_run", applied=False)


def _project_migration_report(
    plan: MigrationPlan,
    *,
    mode: str,
    applied: bool,
    backup_count: int = 0,
    artifact_counts: Mapping[str, int] | None = None,
    additional_blockers: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    analysis = plan.analysis
    blockers = (*plan.blockers, *additional_blockers)
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "migrate",
        "mode": mode,
        "ok": not blockers,
        "applied": applied,
        "secret_exposed": False,
        "summary": {
            "action_count": len(plan.actions),
            "changed_source_count": len({action.source for action in plan.actions}),
            "blocker_count": len(blockers),
            "warning_count": len(analysis.warnings),
            "backup_count": backup_count,
            "artifact_counts": dict(sorted((artifact_counts or {}).items())),
        },
        "actions": [
            {
                "action": "remove_from_wrong_source",
                "key": action.key,
                "source": action.source,
                "owner": action.owner,
                "count": len(action.bindings),
                "comparison": action.comparison,
            }
            for action in plan.actions
        ],
        "blockers": list(blockers),
        "warnings": list(analysis.warnings),
    }


def migrate_runtime_env_ownership(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
    apply: bool = False,
    confirm: str | None = None,
) -> dict[str, object]:
    plan = _build_migration_plan(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
        compose_override_paths=compose_override_paths,
        required_runtime_services=required_runtime_services,
    )
    if not apply:
        return _project_migration_report(plan, mode="dry_run", applied=False)
    if compose_override_paths:
        return _project_migration_report(
            plan,
            mode="apply",
            applied=False,
            additional_blockers=(
                {
                    "code": "apply_with_compose_override_not_supported",
                    "source": COMPOSE_OVERRIDE_SOURCE,
                },
            ),
        )
    if confirm != MIGRATION_APPLY_CONFIRMATION:
        return _project_migration_report(
            plan,
            mode="apply",
            applied=False,
            additional_blockers=(
                {
                    "code": "apply_confirmation_required",
                    "required_confirmation": MIGRATION_APPLY_CONFIRMATION,
                },
            ),
        )
    if plan.blockers:
        return _project_migration_report(plan, mode="apply", applied=False)
    try:
        artifact_counts = _apply_migration_plan(
            plan,
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
        )
    except MigrationApplyError as error:
        return _project_migration_report(
            plan,
            mode="apply",
            applied=False,
            backup_count=error.backup_count,
            artifact_counts=error.artifact_counts,
            additional_blockers=error.blockers,
        )
    return _project_migration_report(
        plan,
        mode="apply",
        applied=True,
        backup_count=sum(artifact_counts.values()),
        artifact_counts=artifact_counts,
    )


class MigrationApplyError(Exception):
    def __init__(
        self,
        code: str,
        source: str,
        *,
        artifacts: Sequence[ArtifactRef] = (),
        blockers: Sequence[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.source = source
        self.artifacts = tuple(artifacts)
        self.artifact_counts = _retained_artifact_counts(self.artifacts)
        self.backup_count = sum(self.artifact_counts.values())
        self.blockers = tuple(blockers or ({"code": code, "source": source},))


def _retained_artifact_counts(artifacts: Sequence[ArtifactRef]) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        marker = (artifact.role, os.fspath(artifact.path))
        if marker in seen:
            continue
        seen.add(marker)
        try:
            retained = artifact.path.exists() or artifact.path.is_symlink()
        except OSError:
            retained = False
        if retained:
            counts[artifact.role] = counts.get(artifact.role, 0) + 1
    return counts


def _safe_private_mode(snapshot: SourceSnapshot) -> int:
    return snapshot.metadata[2] & 0o600


def _env_key_from_line_segment(segment: bytes, line_number: int) -> str | None:
    try:
        line = segment.decode("utf-8")
    except UnicodeError:
        return None
    if line_number == 1 and line.startswith("\ufeff"):
        line = line[1:]
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    return key if KEY_PATTERN.fullmatch(key) else None


def _render_candidate(
    snapshot: SourceSnapshot,
    bindings: Sequence[RemovalBinding],
    additions: Sequence[AdditionBinding] = (),
) -> bytes:
    lines = snapshot.payload.splitlines(keepends=True)
    removal_lines: set[int] = set()
    for binding in bindings:
        if binding.line_number < 1 or binding.line_number > len(lines):
            raise MigrationApplyError("apply_plan_stale", snapshot.source)
        segment = lines[binding.line_number - 1]
        if (
            hashlib.sha256(segment).hexdigest() != binding.line_digest
            or _env_key_from_line_segment(segment, binding.line_number) != binding.key
            or binding.line_number in removal_lines
        ):
            raise MigrationApplyError("apply_plan_stale", snapshot.source)
        removal_lines.add(binding.line_number)
    candidate = b"".join(
        line for line_number, line in enumerate(lines, start=1) if line_number not in removal_lines
    )
    if not additions:
        return candidate
    existing_keys = {
        key
        for line_number, segment in enumerate(candidate.splitlines(keepends=True), start=1)
        if (key := _env_key_from_line_segment(segment, line_number)) is not None
    }
    addition_keys: set[str] = set()
    encoded_additions: list[bytes] = []
    for addition in additions:
        try:
            round_trip_value = _decode_runtime_env_file_rhs(addition.encoded_rhs)
        except ValueError as error:
            raise MigrationApplyError("apply_plan_stale", snapshot.source) from error
        if (
            not KEY_PATTERN.fullmatch(addition.key)
            or addition.key in existing_keys
            or addition.key in addition_keys
            or round_trip_value != addition.private_value
            or not _runtime_env_value_is_representable(round_trip_value)
        ):
            raise MigrationApplyError("apply_plan_stale", snapshot.source)
        addition_keys.add(addition.key)
        try:
            encoded_additions.append(
                f"{addition.key}={addition.encoded_rhs}\n".encode("utf-8")
            )
        except UnicodeError as error:
            raise MigrationApplyError("apply_plan_stale", snapshot.source) from error
    if candidate and not candidate.endswith((b"\n", b"\r")):
        candidate += b"\n"
    return candidate + b"".join(encoded_additions)


def _validate_rendered_private_candidate(
    snapshot: SourceSnapshot,
    candidate_payload: bytes,
    additions: Sequence[AdditionBinding],
) -> None:
    """Fail before backup/commit unless the complete candidate preserves additions."""

    declarations, blockers = _parse_env_payload(candidate_payload, snapshot.source)
    if blockers:
        raise MigrationApplyError("apply_candidate_preflight_failed", snapshot.source)
    for addition in additions:
        matching = tuple(
            declaration
            for declaration in declarations
            if declaration.key == addition.key
        )
        if len(matching) != 1 or matching[0].private_value != addition.private_value:
            raise MigrationApplyError("apply_candidate_preflight_failed", snapshot.source)


def _verify_source_snapshot(snapshot: SourceSnapshot, *, error_code: str) -> None:
    parent_blocker = _source_parent_link_blocker(snapshot.path, snapshot.source)
    if parent_blocker is not None or _path_is_link_or_reparse(snapshot.path):
        raise MigrationApplyError(error_code, snapshot.source)
    try:
        resolved = os.path.normcase(os.fspath(snapshot.path.resolve(strict=True)))
        before = os.stat(snapshot.path, follow_symlinks=False)
        payload = snapshot.path.read_bytes()
        after = os.stat(snapshot.path, follow_symlinks=False)
    except (OSError, RuntimeError) as error:
        raise MigrationApplyError(error_code, snapshot.source) from error
    physical_identity = (int(after.st_dev), int(after.st_ino))
    metadata = (int(after.st_size), int(after.st_mtime_ns), stat.S_IMODE(after.st_mode))
    before_metadata = (int(before.st_size), int(before.st_mtime_ns), stat.S_IMODE(before.st_mode))
    if (
        resolved != snapshot.resolved_identity
        or physical_identity != snapshot.physical_identity
        or (int(before.st_dev), int(before.st_ino)) != physical_identity
        or int(before.st_size) != len(payload)
        or before_metadata != metadata
        or metadata != snapshot.metadata
        or payload != snapshot.payload
        or hashlib.sha256(payload).hexdigest() != snapshot.digest
    ):
        raise MigrationApplyError(error_code, snapshot.source)


def _verify_source_snapshots(
    snapshots: Sequence[SourceSnapshot],
    *,
    excluded_sources: frozenset[str] = frozenset(),
    error_code: str,
) -> None:
    for snapshot in snapshots:
        if snapshot.source not in excluded_sources:
            _verify_source_snapshot(snapshot, error_code=error_code)


def _write_new_file(path: Path, payload: bytes, mode: int) -> None:
    descriptor = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            os.fspath(directory),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        os.fsync(descriptor)
    except OSError:
        # Windows does not expose a portable directory fsync handle. Files are
        # still fsynced before linkage; POSIX callers get the directory fsync.
        if os.name != "nt":
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unique_artifact_path(path: Path, kind: str) -> Path:
    for _attempt in range(32):
        candidate = path.with_name(
            f".{path.name}.jiejing-runtime-env-{kind}-{secrets.token_hex(16)}"
        )
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise OSError("artifact namespace unavailable")


def _prepare_payload_artifact(
    path: Path,
    payload: bytes,
    mode: int,
    kind: str,
) -> PreparedCandidate:
    artifact = _unique_artifact_path(path, kind)
    try:
        _write_new_file(artifact, payload, mode)
        _fsync_directory(path.parent)
        verified_payload, identity, metadata = _stable_read_artifact(artifact)
        digest = hashlib.sha256(payload).hexdigest()
        if verified_payload != payload or hashlib.sha256(verified_payload).hexdigest() != digest:
            raise OSError("prepared artifact changed")
    except (OSError, RuntimeError) as error:
        raise PreparedArtifactError(ArtifactRef(kind, artifact)) from error
    return PreparedCandidate(
        path=artifact,
        planned_payload=payload,
        planned_digest=digest,
        physical_identity=identity,
        metadata=metadata,
        role=kind,
    )


def _stable_read_artifact(path: Path) -> tuple[bytes, tuple[int, int], tuple[int, int, int]]:
    before = os.stat(path, follow_symlinks=False)
    payload = path.read_bytes()
    after = os.stat(path, follow_symlinks=False)
    verification_payload = path.read_bytes()
    final = os.stat(path, follow_symlinks=False)
    before_identity = (int(before.st_dev), int(before.st_ino))
    after_identity = (int(after.st_dev), int(after.st_ino))
    before_metadata = (int(before.st_size), int(before.st_mtime_ns), stat.S_IMODE(before.st_mode))
    after_metadata = (int(after.st_size), int(after.st_mtime_ns), stat.S_IMODE(after.st_mode))
    final_identity = (int(final.st_dev), int(final.st_ino))
    final_metadata = (int(final.st_size), int(final.st_mtime_ns), stat.S_IMODE(final.st_mode))
    if (
        before_identity != after_identity
        or after_identity != final_identity
        or before_metadata != after_metadata
        or after_metadata != final_metadata
        or int(after.st_size) != len(payload)
        or int(final.st_size) != len(verification_payload)
        or verification_payload != payload
    ):
        raise OSError("artifact changed during read")
    return payload, after_identity, after_metadata


def _prepared_candidate_matches(prepared: PreparedCandidate) -> bool:
    try:
        payload, identity, metadata = _stable_read_artifact(prepared.path)
    except (OSError, RuntimeError):
        return False
    return (
        identity == prepared.physical_identity
        and metadata == prepared.metadata
        and payload == prepared.planned_payload
        and hashlib.sha256(payload).hexdigest() == prepared.planned_digest
    )


def _install_artifact_no_clobber(
    prepared: PreparedCandidate,
    target: Path,
) -> NamespaceMutationOutcome:
    if not _prepared_candidate_matches(prepared):
        raise OSError("prepared artifact changed")
    os.link(prepared.path, target, follow_symlinks=False)

    content_verified = False
    identity = prepared.physical_identity
    metadata = prepared.metadata
    try:
        payload, identity, metadata = _stable_read_artifact(target)
        content_verified = (
            identity == prepared.physical_identity
            and metadata == prepared.metadata
            and payload == prepared.planned_payload
            and hashlib.sha256(payload).hexdigest() == prepared.planned_digest
        )
    except (OSError, RuntimeError):
        content_verified = False

    artifact_removed = False
    if content_verified:
        try:
            prepared.path.unlink()
            artifact_removed = True
        except OSError:
            artifact_removed = False

    durable = True
    try:
        _fsync_directory(target.parent)
    except OSError:
        durable = False
    return NamespaceMutationOutcome(
        path=target,
        physical_identity=identity,
        metadata=metadata,
        durable=durable,
        content_verified=content_verified,
        prepared_artifact_removed=artifact_removed,
    )


def _detach_target_no_clobber(target: Path, kind: str) -> NamespaceMutationOutcome:
    detached = _unique_artifact_path(target, kind)
    if detached.exists() or detached.is_symlink():
        raise FileExistsError
    target_stat = os.stat(target, follow_symlinks=False)
    identity = (int(target_stat.st_dev), int(target_stat.st_ino))
    metadata = (
        int(target_stat.st_size),
        int(target_stat.st_mtime_ns),
        stat.S_IMODE(target_stat.st_mode),
    )
    os.rename(target, detached)
    durable = True
    try:
        _fsync_directory(target.parent)
    except OSError:
        durable = False
    return NamespaceMutationOutcome(
        path=detached,
        physical_identity=identity,
        metadata=metadata,
        durable=durable,
    )


def _artifact_matches_snapshot(path: Path, snapshot: SourceSnapshot) -> bool:
    try:
        payload, identity, metadata = _stable_read_artifact(path)
    except (OSError, RuntimeError):
        return False
    return (
        identity == snapshot.physical_identity
        and metadata == snapshot.metadata
        and payload == snapshot.payload
        and hashlib.sha256(payload).hexdigest() == snapshot.digest
    )


def _artifact_matches_commit(path: Path, record: CommitRecord) -> bool:
    try:
        payload, identity, metadata = _stable_read_artifact(path)
    except (OSError, RuntimeError):
        return False
    return (
        identity == record.physical_identity
        and metadata == record.candidate_metadata
        and payload == record.candidate_payload
        and hashlib.sha256(payload).hexdigest() == record.candidate_digest
    )


def _restore_artifact_payload_if_absent(
    artifact: Path,
    target: Path,
    *,
    mode: int,
) -> RecoveryOutcome:
    prepared: PreparedCandidate | None = None
    try:
        payload, _identity, _metadata = _stable_read_artifact(artifact)
        prepared = _prepare_payload_artifact(target, payload, mode, "restore")
        outcome = _install_artifact_no_clobber(prepared, target)
        artifacts = (ArtifactRef(prepared.role, prepared.path),)
        return RecoveryOutcome(
            installed=outcome.content_verified,
            durable=outcome.durable,
            artifacts=artifacts,
        )
    except (OSError, RuntimeError) as error:
        artifacts = (
            (ArtifactRef(prepared.role, prepared.path),)
            if prepared is not None
            else (
                (error.artifact,)
                if isinstance(error, PreparedArtifactError)
                else ()
            )
        )
        return RecoveryOutcome(installed=False, durable=False, artifacts=artifacts)


def _guarded_commit_before_detach(_snapshot: SourceSnapshot) -> None:
    return None


def _guarded_commit_before_install(_snapshot: SourceSnapshot, _backup_path: Path) -> None:
    return None


def _guarded_commit_after_install(_record: CommitRecord) -> None:
    return None


def _guarded_apply_after_post_validation(_plan: MigrationPlan) -> None:
    """Test seam for the final readonly-snapshot validation window."""

    return None


def _guarded_rollback_before_detach(_record: CommitRecord) -> None:
    return None


def _guarded_rollback_before_restore(
    _record: CommitRecord,
    _candidate_hold: Path,
    _backup_path: Path,
) -> None:
    return None


def _record_artifacts(record: CommitRecord) -> tuple[ArtifactRef, ...]:
    return (
        ArtifactRef("backup", record.backup_path),
        ArtifactRef("candidate", record.candidate_artifact_path),
    )


def _target_matches_prepared(target: Path, prepared: PreparedCandidate) -> bool:
    try:
        payload, identity, metadata = _stable_read_artifact(target)
    except (OSError, RuntimeError):
        return False
    return (
        identity == prepared.physical_identity
        and metadata == prepared.metadata
        and payload == prepared.planned_payload
        and hashlib.sha256(payload).hexdigest() == prepared.planned_digest
    )


def _restore_original_after_forward_install(record: CommitRecord) -> RollbackOutcome:
    artifacts: list[ArtifactRef] = list(_record_artifacts(record))
    blockers: list[dict[str, object]] = []
    try:
        detached = _detach_target_no_clobber(record.path, "candidate-hold")
    except (OSError, RuntimeError):
        return RollbackOutcome(
            blockers=({"code": "apply_recovery_conflict", "source": record.source},),
            artifacts=tuple(artifacts),
        )
    artifacts.append(ArtifactRef("candidate_hold", detached.path))
    if not detached.durable:
        blockers.append({"code": "apply_durability_failed", "source": record.source})
    recovery = _restore_artifact_payload_if_absent(
        record.backup_path,
        record.path,
        mode=record.mode,
    )
    artifacts.extend(recovery.artifacts)
    if not recovery.installed:
        blockers.append({"code": "apply_recovery_conflict", "source": record.source})
    elif not recovery.durable:
        blockers.append({"code": "apply_durability_failed", "source": record.source})
    return RollbackOutcome(blockers=tuple(blockers), artifacts=tuple(artifacts))


def _commit_candidate(
    snapshot: SourceSnapshot,
    candidate_payload: bytes,
    candidate_digest: str,
    mode: int,
) -> CommitRecord:
    if hashlib.sha256(candidate_payload).hexdigest() != candidate_digest:
        raise MigrationApplyError("apply_plan_stale", snapshot.source)
    try:
        prepared = _prepare_payload_artifact(
            snapshot.path,
            candidate_payload,
            mode,
            "candidate",
        )
    except PreparedArtifactError as error:
        raise MigrationApplyError(
            "apply_candidate_prepare_failed",
            snapshot.source,
            artifacts=(error.artifact,),
        ) from error
    candidate_ref = ArtifactRef("candidate", prepared.path)
    _verify_source_snapshot(snapshot, error_code="apply_source_changed")
    _guarded_commit_before_detach(snapshot)
    try:
        detached = _detach_target_no_clobber(snapshot.path, "backup")
    except (OSError, RuntimeError) as error:
        raise MigrationApplyError(
            "apply_source_changed",
            snapshot.source,
            artifacts=(candidate_ref,),
        ) from error

    backup_path = detached.path
    base_artifacts = (candidate_ref, ArtifactRef("backup", backup_path))
    if not detached.durable:
        recovery = _restore_artifact_payload_if_absent(
            backup_path,
            snapshot.path,
            mode=mode,
        )
        blockers = [{"code": "apply_durability_failed", "source": snapshot.source}]
        if not recovery.installed:
            blockers.append({"code": "apply_recovery_conflict", "source": snapshot.source})
        elif not recovery.durable:
            blockers.append({"code": "apply_recovery_durability_failed", "source": snapshot.source})
        raise MigrationApplyError(
            "apply_durability_failed",
            snapshot.source,
            artifacts=(*base_artifacts, *recovery.artifacts),
            blockers=blockers,
        )

    if not _artifact_matches_snapshot(backup_path, snapshot):
        recovered = _restore_artifact_payload_if_absent(
            backup_path,
            snapshot.path,
            mode=mode,
        )
        blockers = [{"code": "apply_source_changed", "source": snapshot.source}]
        if not recovered.installed:
            blockers.append({"code": "apply_recovery_conflict", "source": snapshot.source})
        elif not recovered.durable:
            blockers.append({"code": "apply_recovery_durability_failed", "source": snapshot.source})
        raise MigrationApplyError(
            "apply_source_changed",
            snapshot.source,
            artifacts=(*base_artifacts, *recovered.artifacts),
            blockers=blockers,
        )

    _guarded_commit_before_install(snapshot, backup_path)
    try:
        install = _install_artifact_no_clobber(
            prepared,
            snapshot.path,
        )
    except (OSError, RuntimeError) as error:
        recovered = _restore_artifact_payload_if_absent(
            backup_path,
            snapshot.path,
            mode=mode,
        )
        code = (
            "apply_candidate_changed"
            if not _prepared_candidate_matches(prepared)
            else "apply_install_conflict"
        )
        blockers = [{"code": code, "source": snapshot.source}]
        if not recovered.installed:
            blockers.append({"code": "apply_recovery_conflict", "source": snapshot.source})
        elif not recovered.durable:
            blockers.append({"code": "apply_recovery_durability_failed", "source": snapshot.source})
        raise MigrationApplyError(
            code,
            snapshot.source,
            artifacts=(*base_artifacts, *recovered.artifacts),
            blockers=blockers,
        ) from error

    record = CommitRecord(
        source=snapshot.source,
        path=snapshot.path,
        candidate_payload=candidate_payload,
        candidate_digest=candidate_digest,
        physical_identity=prepared.physical_identity,
        candidate_metadata=prepared.metadata,
        backup_path=backup_path,
        candidate_artifact_path=prepared.path,
        mode=mode,
    )
    if not install.content_verified or not _commit_target_matches(record):
        rollback = _restore_original_after_forward_install(record)
        raise MigrationApplyError(
            "apply_candidate_changed",
            snapshot.source,
            artifacts=rollback.artifacts,
            blockers=(
                {"code": "apply_candidate_changed", "source": snapshot.source},
                *rollback.blockers,
            ),
        )
    if not install.durable:
        rollback = _restore_original_after_forward_install(record)
        raise MigrationApplyError(
            "apply_durability_failed",
            snapshot.source,
            artifacts=rollback.artifacts,
            blockers=(
                {"code": "apply_durability_failed", "source": snapshot.source},
                *rollback.blockers,
            ),
        )
    _guarded_commit_after_install(record)
    if not _artifact_matches_snapshot(backup_path, snapshot):
        rollback = _guarded_rollback_commit(record)
        blockers = [
            {"code": "apply_backup_source_changed", "source": snapshot.source},
            *rollback.blockers,
        ]
        raise MigrationApplyError(
            "apply_backup_source_changed",
            snapshot.source,
            artifacts=rollback.artifacts,
            blockers=blockers,
        )
    return record


def _commit_target_matches(record: CommitRecord) -> bool:
    if _source_parent_link_blocker(record.path, record.source) is not None:
        return False
    if _path_is_link_or_reparse(record.path):
        return False
    return _artifact_matches_commit(record.path, record)


def _promote_rollback_candidate_drift(
    record: CommitRecord,
    candidate_hold: Path,
    restored: PreparedCandidate,
) -> RollbackOutcome:
    artifacts: list[ArtifactRef] = [
        *_record_artifacts(record),
        ArtifactRef("candidate_hold", candidate_hold),
        ArtifactRef("rollback_restore", restored.path),
    ]
    blockers: list[dict[str, object]] = [
        {"code": "apply_rollback_source_changed", "source": record.source}
    ]
    try:
        external_payload, _identity, _metadata = _stable_read_artifact(candidate_hold)
    except (OSError, RuntimeError):
        blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        return RollbackOutcome(tuple(blockers), tuple(artifacts))

    if not _target_matches_prepared(record.path, restored):
        blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        return RollbackOutcome(tuple(blockers), tuple(artifacts))
    try:
        recovery = _detach_target_no_clobber(record.path, "rollback-recovery")
    except (OSError, RuntimeError):
        blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        return RollbackOutcome(tuple(blockers), tuple(artifacts))
    artifacts.append(ArtifactRef("rollback_recovery", recovery.path))
    if not recovery.durable:
        blockers.append({"code": "apply_rollback_durability_failed", "source": record.source})
    if not _target_matches_prepared(recovery.path, restored):
        recovered = _restore_artifact_payload_if_absent(
            recovery.path,
            record.path,
            mode=record.mode,
        )
        artifacts.extend(recovered.artifacts)
        blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        return RollbackOutcome(tuple(blockers), tuple(artifacts))

    promoted: PreparedCandidate | None = None
    try:
        promoted = _prepare_payload_artifact(
            record.path,
            external_payload,
            record.mode,
            "rollback-promotion",
        )
        artifacts.append(ArtifactRef("rollback_promotion", promoted.path))
        outcome = _install_artifact_no_clobber(promoted, record.path)
        if not outcome.content_verified or not outcome.durable:
            blockers.append({"code": "apply_rollback_conflict", "source": record.source})
    except (OSError, RuntimeError) as error:
        if isinstance(error, PreparedArtifactError):
            artifacts.append(error.artifact)
        blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        restored_original = _restore_artifact_payload_if_absent(
            recovery.path,
            record.path,
            mode=record.mode,
        )
        artifacts.extend(restored_original.artifacts)
    return RollbackOutcome(tuple(blockers), tuple(artifacts))


def _guarded_rollback_commit(record: CommitRecord) -> RollbackOutcome:
    artifacts: list[ArtifactRef] = list(_record_artifacts(record))
    # This preflight is diagnostic only. The authoritative validation happens
    # on the atomically detached candidate below.
    _commit_target_matches(record)
    _guarded_rollback_before_detach(record)
    try:
        detached = _detach_target_no_clobber(record.path, "candidate-hold")
    except (OSError, RuntimeError):
        return RollbackOutcome(
            blockers=({"code": "apply_rollback_source_changed", "source": record.source},),
            artifacts=tuple(artifacts),
        )

    candidate_hold = detached.path
    artifacts.append(ArtifactRef("candidate_hold", candidate_hold))
    if not detached.durable:
        recovery = _restore_artifact_payload_if_absent(
            candidate_hold,
            record.path,
            mode=record.mode,
        )
        artifacts.extend(recovery.artifacts)
        blockers = [{"code": "apply_rollback_durability_failed", "source": record.source}]
        if not recovery.installed:
            blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        return RollbackOutcome(tuple(blockers), tuple(artifacts))

    if not _artifact_matches_commit(candidate_hold, record):
        recovered = _restore_artifact_payload_if_absent(
            candidate_hold,
            record.path,
            mode=record.mode,
        )
        blockers = [{"code": "apply_rollback_source_changed", "source": record.source}]
        if not recovered.installed:
            blockers.append({"code": "apply_rollback_conflict", "source": record.source})
        elif not recovered.durable:
            blockers.append({"code": "apply_rollback_durability_failed", "source": record.source})
        artifacts.extend(recovered.artifacts)
        return RollbackOutcome(tuple(blockers), tuple(artifacts))

    _guarded_rollback_before_restore(record, candidate_hold, record.backup_path)
    restored: PreparedCandidate | None = None
    try:
        backup_payload, _identity, _metadata = _stable_read_artifact(record.backup_path)
        restored = _prepare_payload_artifact(
            record.path,
            backup_payload,
            record.mode,
            "rollback-restore",
        )
        artifacts.append(ArtifactRef("rollback_restore", restored.path))
        restore_outcome = _install_artifact_no_clobber(restored, record.path)
    except (OSError, RuntimeError) as error:
        if isinstance(error, PreparedArtifactError):
            artifacts.append(error.artifact)
        return RollbackOutcome(
            blockers=({"code": "apply_rollback_conflict", "source": record.source},),
            artifacts=tuple(artifacts),
        )
    if not restore_outcome.content_verified or not _target_matches_prepared(record.path, restored):
        return RollbackOutcome(
            blockers=({"code": "apply_rollback_conflict", "source": record.source},),
            artifacts=tuple(artifacts),
        )
    if not _artifact_matches_commit(candidate_hold, record):
        promoted = _promote_rollback_candidate_drift(record, candidate_hold, restored)
        if restore_outcome.durable:
            return promoted
        return RollbackOutcome(
            blockers=(
                {"code": "apply_rollback_durability_failed", "source": record.source},
                *promoted.blockers,
            ),
            artifacts=(*artifacts, *promoted.artifacts),
        )
    if not restore_outcome.durable:
        return RollbackOutcome(
            blockers=({"code": "apply_rollback_durability_failed", "source": record.source},),
            artifacts=tuple(artifacts),
        )
    return RollbackOutcome(blockers=(), artifacts=tuple(artifacts))


def _migration_lock_path(plan: MigrationPlan) -> Path:
    private_snapshots = {
        snapshot.source: snapshot
        for snapshot in plan.snapshots
        if snapshot.source in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}
    }
    anchor = private_snapshots.get(MANAGED_SOURCE)
    if anchor is None:
        raise MigrationApplyError("migration_lock_scope_unavailable", "migration")
    return anchor.path.parent / ".jiejing-runtime-env-migration.lock"


def _acquire_migration_lock(plan: MigrationPlan) -> MigrationLock:
    lock_path = _migration_lock_path(plan)
    if _source_parent_link_blocker(lock_path, "migration") is not None:
        raise MigrationApplyError("migration_lock_scope_unsafe", "migration")
    descriptor = -1
    try:
        descriptor = os.open(
            os.fspath(lock_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(b"jiejing-runtime-env-migration\n")
            stream.flush()
            os.fsync(stream.fileno())
        lock_path.chmod(0o600)
        lock_stat = os.stat(lock_path, follow_symlinks=False)
        return MigrationLock(
            path=lock_path,
            physical_identity=(int(lock_stat.st_dev), int(lock_stat.st_ino)),
        )
    except FileExistsError as error:
        raise MigrationApplyError("migration_lock_unavailable", "migration") from error
    except OSError as error:
        raise MigrationApplyError("migration_lock_failed", "migration") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _release_migration_lock(lock: MigrationLock) -> None:
    try:
        lock_stat = os.stat(lock.path, follow_symlinks=False)
        identity = (int(lock_stat.st_dev), int(lock_stat.st_ino))
        if identity == lock.physical_identity and not _path_is_link_or_reparse(lock.path):
            lock.path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _apply_migration_plan(
    plan: MigrationPlan,
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
) -> dict[str, int]:
    if not plan.actions and plan.pre_apply_validator is None and plan.post_apply_validator is None:
        return {}
    lock = _acquire_migration_lock(plan)
    try:
        return _apply_migration_plan_locked(
            plan,
            compose_path=compose_path,
            managed_env_path=managed_env_path,
            secret_env_path=secret_env_path,
            postgres_env_path=postgres_env_path,
        )
    finally:
        _release_migration_lock(lock)


def _apply_migration_plan_locked(
    plan: MigrationPlan,
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
) -> dict[str, int]:
    del compose_path, managed_env_path, secret_env_path, postgres_env_path
    snapshots_by_source = {snapshot.source: snapshot for snapshot in plan.snapshots}
    bindings_by_source: dict[str, list[RemovalBinding]] = {}
    additions_by_source: dict[str, list[AdditionBinding]] = {}
    for action in plan.actions:
        role = _source_role(action.source)
        if role not in {MANAGED_SOURCE, SECRET_SOURCE, POSTGRES_SOURCE}:
            raise MigrationApplyError("apply_unknown_source", "migration")
        if role not in snapshots_by_source:
            raise MigrationApplyError("apply_plan_stale", role)
        bindings_by_source.setdefault(role, []).extend(action.bindings)
        additions_by_source.setdefault(role, []).extend(action.additions)
    changed_sources = tuple(dict.fromkeys((*bindings_by_source, *additions_by_source)))
    if plan.pre_apply_validator is not None:
        plan.pre_apply_validator()
    _verify_source_snapshots(plan.snapshots, error_code="apply_plan_stale")
    if not changed_sources:
        if plan.post_apply_validator is not None:
            plan.post_apply_validator()
        _guarded_apply_after_post_validation(plan)
        _verify_source_snapshots(plan.snapshots, error_code="apply_source_changed")
        return {}

    changed_snapshots = [snapshots_by_source[source] for source in changed_sources]
    candidate_payloads = {
        snapshot.source: _render_candidate(
            snapshot,
            bindings_by_source.get(snapshot.source, ()),
            additions_by_source.get(snapshot.source, ()),
        )
        for snapshot in changed_snapshots
    }
    for snapshot in changed_snapshots:
        _validate_rendered_private_candidate(
            snapshot,
            candidate_payloads[snapshot.source],
            additions_by_source.get(snapshot.source, ()),
        )
    candidate_digests = {
        source: hashlib.sha256(payload).hexdigest()
        for source, payload in candidate_payloads.items()
    }
    modes = {snapshot.source: _safe_private_mode(snapshot) for snapshot in changed_snapshots}
    commits: list[CommitRecord] = []
    try:
        for snapshot in changed_snapshots:
            _verify_source_snapshots(
                plan.snapshots,
                excluded_sources=frozenset(commit.source for commit in commits),
                error_code="apply_source_changed",
            )
            commit = _commit_candidate(
                snapshot,
                candidate_payloads[snapshot.source],
                candidate_digests[snapshot.source],
                modes[snapshot.source],
            )
            commits.append(commit)
        _verify_source_snapshots(
            plan.snapshots,
            excluded_sources=frozenset(commit.source for commit in commits),
            error_code="apply_source_changed",
        )
        if plan.post_apply_validator is not None:
            plan.post_apply_validator()
        else:
            validation = _build_migration_plan(
                compose_path=snapshots_by_source[COMPOSE_SOURCE].path,
                managed_env_path=snapshots_by_source[MANAGED_SOURCE].path,
                secret_env_path=snapshots_by_source[SECRET_SOURCE].path,
                postgres_env_path=snapshots_by_source[POSTGRES_SOURCE].path,
                compose_override_paths=plan.compose_override_paths,
                required_runtime_services=tuple(plan.required_runtime_services),
            )
            if validation.blockers or validation.actions:
                raise MigrationApplyError("post_apply_validation_failed", "migration")
        for commit in commits:
            snapshot = snapshots_by_source[commit.source]
            if not _artifact_matches_snapshot(commit.backup_path, snapshot):
                raise MigrationApplyError(
                    "apply_backup_source_changed",
                    commit.source,
                )
            if not _commit_target_matches(commit):
                raise MigrationApplyError(
                    "apply_commit_source_changed",
                    commit.source,
                )
        artifact_counts = _retained_artifact_counts(
            tuple(artifact for commit in commits for artifact in _record_artifacts(commit))
        )
        _guarded_apply_after_post_validation(plan)
        _verify_source_snapshots(
            plan.snapshots,
            excluded_sources=frozenset(commit.source for commit in commits),
            error_code="apply_source_changed",
        )
    except Exception as error:
        rollback_blockers: list[dict[str, object]] = []
        retained_artifacts: list[ArtifactRef] = (
            list(error.artifacts) if isinstance(error, MigrationApplyError) else []
        )
        for commit in reversed(commits):
            try:
                rollback = _guarded_rollback_commit(commit)
                rollback_blockers.extend(rollback.blockers)
                retained_artifacts.extend(rollback.artifacts)
            except Exception:
                rollback_blockers.append(
                    {"code": "apply_rollback_failed", "source": commit.source}
                )
                retained_artifacts.extend(_record_artifacts(commit))
        original_blockers = (
            list(error.blockers)
            if isinstance(error, MigrationApplyError)
            else [{"code": "apply_atomic_replace_failed", "source": "migration"}]
        )
        combined_blockers = (*original_blockers, *rollback_blockers)
        first_blocker = combined_blockers[0]
        raise MigrationApplyError(
            str(first_blocker.get("code") or "apply_failed"),
            str(first_blocker.get("source") or "migration"),
            artifacts=retained_artifacts,
            blockers=combined_blockers,
        ) from error
    return artifact_counts


MIGRATION_RESOLVABLE_BLOCKER_CODES = frozenset(
    {"cross_source_duplicate", "same_source_duplicate", "wrong_source"}
)


def _build_migration_plan(
    *,
    compose_path: Path,
    managed_env_path: Path,
    secret_env_path: Path,
    postgres_env_path: Path,
    compose_override_paths: Sequence[Path] = (),
    required_runtime_services: Sequence[str] | None = None,
) -> MigrationPlan:
    normalized_required_services = _normalize_required_runtime_services(required_runtime_services)
    snapshots, snapshot_blockers = _capture_source_snapshots(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
    )
    analysis = analyze_runtime_env_ownership(
        compose_path=compose_path,
        managed_env_path=managed_env_path,
        secret_env_path=secret_env_path,
        postgres_env_path=postgres_env_path,
        compose_override_paths=compose_override_paths,
        required_runtime_services=tuple(normalized_required_services),
        _source_snapshots=snapshots,
        _snapshot_blockers=snapshot_blockers,
    )
    blockers = [
        blocker
        for blocker in analysis.blockers
        if blocker.get("code") not in MIGRATION_RESOLVABLE_BLOCKER_CODES
    ]
    actions: list[MigrationAction] = []
    for key_analysis in analysis.keys:
        wrong_declarations = tuple(
            declaration
            for declaration in key_analysis.declarations
            if key_analysis.owner is not None and _source_role(declaration.source) != key_analysis.owner
        )
        duplicate_in_one_source = any(len(group.declarations) > 1 for group in key_analysis.source_groups)
        if key_analysis.owner is None:
            if key_analysis.unauthorized_duplicate:
                blockers.append(
                    {
                        "code": "unknown_duplicate",
                        "key": key_analysis.key,
                        "sources": list(key_analysis.source_roles),
                        "comparison": key_analysis.comparison,
                    }
                )
            continue
        owner_declarations = tuple(
            declaration
            for declaration in key_analysis.declarations
            if _source_role(declaration.source) == key_analysis.owner
        )
        compose_wrong_declarations = tuple(
            declaration
            for declaration in wrong_declarations
            if _source_role(declaration.source) == COMPOSE_SOURCE
        )
        if compose_wrong_declarations:
            for declaration in compose_wrong_declarations:
                blockers.append(
                    {
                        "code": "compose_migration_deferred",
                        "key": key_analysis.key,
                        "source": declaration.source,
                        "owner": key_analysis.owner,
                    }
                )
            continue
        if not wrong_declarations:
            if duplicate_in_one_source:
                blockers.append(
                    {
                        "code": "authoritative_source_duplicate",
                        "key": key_analysis.key,
                        "owner": key_analysis.owner,
                        "comparison": key_analysis.comparison,
                    }
                )
            continue
        if not owner_declarations:
            blockers.append(
                {
                    "code": "authoritative_source_missing",
                    "key": key_analysis.key,
                    "owner": key_analysis.owner,
                }
            )
            continue
        owner_groups = tuple(
            group
            for group in key_analysis.source_groups
            if _source_role(group.source) == key_analysis.owner
        )
        if any(len(group.declarations) != 1 for group in owner_groups):
            blockers.append(
                {
                    "code": "authoritative_source_duplicate",
                    "key": key_analysis.key,
                    "owner": key_analysis.owner,
                    "comparison": key_analysis.comparison,
                }
            )
            continue
        if key_analysis.comparison != "equal":
            blockers.append(
                {
                    "code": "migration_value_conflict",
                    "key": key_analysis.key,
                    "owner": key_analysis.owner,
                    "comparison": "conflict",
                }
            )
            continue
        declarations_by_wrong_source: dict[str, list[Declaration]] = {}
        for declaration in wrong_declarations:
            declarations_by_wrong_source.setdefault(declaration.source, []).append(declaration)
        for source, declarations in sorted(declarations_by_wrong_source.items()):
            snapshot = snapshots.get(_source_role(source))
            if snapshot is None or _source_role(source) not in {
                MANAGED_SOURCE,
                SECRET_SOURCE,
                POSTGRES_SOURCE,
            }:
                blockers.append(
                    {
                        "code": "migration_action_source_forbidden",
                        "key": key_analysis.key,
                        "source": source,
                        "owner": key_analysis.owner,
                    }
                )
                continue
            line_segments = snapshot.payload.splitlines(keepends=True)
            if any(
                declaration.line_number < 1 or declaration.line_number > len(line_segments)
                for declaration in declarations
            ):
                blockers.append(
                    {
                        "code": "migration_snapshot_binding_failed",
                        "key": key_analysis.key,
                        "source": source,
                    }
                )
                continue
            actions.append(
                MigrationAction(
                    key=key_analysis.key,
                    source=source,
                    owner=key_analysis.owner,
                    comparison="equal",
                    bindings=tuple(
                        RemovalBinding(
                            line_number=declaration.line_number,
                            key=declaration.key,
                            line_digest=hashlib.sha256(
                                line_segments[declaration.line_number - 1]
                            ).hexdigest(),
                        )
                        for declaration in declarations
                    ),
                )
            )
    return MigrationPlan(
        analysis=analysis,
        actions=tuple(sorted(actions, key=lambda action: (action.key, action.source))),
        blockers=tuple(blockers),
        snapshots=tuple(snapshots.values()),
        required_runtime_services=normalized_required_services,
        compose_override_paths=tuple(compose_override_paths),
    )


def _add_source_path_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--managed-env", type=Path, required=True)
    parser.add_argument("--secret-env", type=Path, required=True)
    parser.add_argument("--postgres-env", type=Path, required=True)
    parser.add_argument(
        "--compose-override",
        type=Path,
        action="append",
        help="Read-only Compose override to validate. Repeat for multiple overrides.",
    )
    parser.add_argument(
        "--required-runtime-service",
        action="append",
        choices=sorted(RUNTIME_SERVICE_NAMES),
        help=(
            "Required runtime service. Repeat to select multiple services; "
            "defaults to both jiejing-saas and jiejing-worker."
        ),
    )
    parser.add_argument("--json", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="Check runtime env ownership without changing files.")
    _add_source_path_arguments(check_parser)
    check_parser.add_argument(
        "--compose-runtime-path",
        type=Path,
        help=(
            "Future installed Compose path used only to resolve relative env_file references; "
            "the candidate content is still read from --compose."
        ),
    )
    check_parser.add_argument("--managed-runtime-path", type=Path)
    check_parser.add_argument("--secret-runtime-path", type=Path)
    check_parser.add_argument("--postgres-runtime-path", type=Path)
    resolution_parser = subparsers.add_parser(
        "resolution-plan",
        help="Validate a value-free decision manifest and prepare a non-mutating plan.",
    )
    _add_source_path_arguments(resolution_parser)
    resolution_parser.add_argument(
        "--compose-runtime-path",
        type=Path,
        help=(
            "Future installed Compose path used only to resolve relative env_file references; "
            "the candidate content is still read from --compose."
        ),
    )
    resolution_parser.add_argument(
        "--donor-compose",
        type=Path,
        help=(
            "Read-only current Compose topology used only by explicit donor_role=compose "
            "resolution decisions."
        ),
    )
    resolution_parser.add_argument("--decision-manifest", type=Path, required=True)
    resolution_apply_parser = subparsers.add_parser(
        "resolution-apply",
        help="Apply a rebuilt zero-blocker resolution plan after exact confirmation.",
    )
    _add_source_path_arguments(resolution_apply_parser)
    resolution_apply_parser.add_argument(
        "--compose-runtime-path",
        type=Path,
        help=(
            "Future installed Compose path used only to resolve relative env_file references; "
            "the candidate content is still read from --compose."
        ),
    )
    resolution_apply_parser.add_argument("--donor-compose", type=Path)
    resolution_apply_parser.add_argument("--decision-manifest", type=Path, required=True)
    resolution_apply_parser.add_argument("--confirm")
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Plan runtime env ownership cleanup without changing files.",
    )
    _add_source_path_arguments(migrate_parser)
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.add_argument("--confirm")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    source_paths = {
        "compose_path": args.compose,
        "managed_env_path": args.managed_env,
        "secret_env_path": args.secret_env,
        "postgres_env_path": args.postgres_env,
        "compose_override_paths": tuple(args.compose_override or ()),
        "required_runtime_services": args.required_runtime_service,
    }
    if args.command == "check":
        report = check_runtime_env_ownership(
            **source_paths,
            compose_runtime_path=args.compose_runtime_path,
            managed_runtime_path=args.managed_runtime_path,
            secret_runtime_path=args.secret_runtime_path,
            postgres_runtime_path=args.postgres_runtime_path,
        )
    elif args.command == "resolution-plan":
        report = plan_runtime_env_resolution(
            **source_paths,
            decision_manifest_path=args.decision_manifest,
            compose_runtime_path=args.compose_runtime_path,
            donor_compose_path=args.donor_compose,
        )
    elif args.command == "resolution-apply":
        report = apply_runtime_env_resolution(
            **source_paths,
            decision_manifest_path=args.decision_manifest,
            compose_runtime_path=args.compose_runtime_path,
            donor_compose_path=args.donor_compose,
            confirm=args.confirm,
        )
    else:
        report = migrate_runtime_env_ownership(
            **source_paths,
            apply=args.apply,
            confirm=args.confirm,
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
