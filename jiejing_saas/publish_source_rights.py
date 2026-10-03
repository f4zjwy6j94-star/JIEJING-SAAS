"""Authoritative source and image-rights evidence for eBay write boundaries.

The browser may identify persisted evidence records and requested assets, but it
cannot award itself source, review, or commercial-rights status.  This module
resolves those claims from company/store/project-scoped repository records and
returns a canonical, server-owned evidence snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit


PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION = "2026-08-31-publish-source-rights-evidence-v1"
MERCHANT_FACT_SAVE_ATTESTATION_VERSION = "merchant_product_fact_save_attestation_v1"

__all__ = [
    "PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION",
    "PublishSourceRightsEvidenceError",
    "canonicalize_publish_asset_manifest",
    "resolve_publish_source_rights_evidence",
    "validate_publish_source_rights_evidence",
]


class PublishSourceRightsEvidenceError(ValueError):
    """Safe, structured denial raised when persisted evidence is insufficient."""

    def __init__(self, code: str, *blockers: str) -> None:
        self.code = str(code or "publish_evidence_not_ready")[:120]
        self.blockers = tuple(str(item)[:160] for item in blockers if str(item).strip())
        super().__init__(self.code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "blocked",
            "code": self.code,
            "blockers": list(self.blockers),
            "secret_exposed": False,
        }


class PublishEvidenceRepository(Protocol):
    def list_reports(
        self,
        *,
        company_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_media_asset_job(self, *, company_id: str, media_job_id: str) -> dict[str, Any] | None: ...

    def get_task(self, *, company_id: str, task_id: str) -> dict[str, Any] | None: ...


def build_merchant_fact_save_attestation(
    *, report_id: str, task_id: str, company_id: str, store_id: str, user_id: str,
    listing_project_identity: Mapping[str, Any], packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Mint only at the authenticated fact-save boundary, never from model output."""
    return {
        "contract_version": MERCHANT_FACT_SAVE_ATTESTATION_VERSION,
        "authority": "authenticated_product_fact_save",
        "report_id": report_id, "task_id": task_id, "company_id": company_id,
        "store_id": store_id, "user_id": user_id,
        "listing_project_identity": _normalize_project_identity(listing_project_identity),
        "packet_sha256": hashlib.sha256(json.dumps(
            packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest(),
    }


def valid_merchant_fact_save_attestation(report: Mapping[str, Any], task: Mapping[str, Any]) -> bool:
    """Cross-check server records; a copied report/model/client assertion is insufficient."""
    try:
        payload = report.get("report") or {}
        packet = payload.get("merchant_product_fact_packet") or {}
        proof = payload.get("merchant_save_attestation")
        task_input = task.get("input") or {}
        task_output = task.get("output") or {}
        task_id = str(task.get("task_id") or "")
        report_id = str(report.get("report_id") or "")
        if not (
            isinstance(proof, dict) and report.get("status") == "saved"
            and report.get("report_type") == "merchant.product_facts"
            and task_id.startswith("task_product_facts_")
            and report_id == "report_product_facts_" + task_id.removeprefix("task_product_facts_")
            and report.get("task_id") == task_id
            and task.get("task_type") == "merchant_product_facts" and task.get("status") == "completed"
            and task.get("runtime_run_id") is None and bool(task.get("user_id"))
            and task.get("company_id") == report.get("company_id")
            and task.get("store_id") == report.get("store_id")
            and task_output.get("report_id") == report_id
            and task_input.get("merchant_product_fact_packet") == packet
            and task_input.get("merchant_save_attestation") == proof
            and _normalize_project_identity(task_input.get("listing_project_identity"))
                == _normalize_project_identity(payload.get("listing_project_identity"))
        ):
            return False
        return proof == build_merchant_fact_save_attestation(
            report_id=report_id, task_id=task_id, company_id=task["company_id"],
            store_id=task["store_id"], user_id=task["user_id"],
            listing_project_identity=payload["listing_project_identity"], packet=packet,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def canonicalize_publish_asset_manifest(asset_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact URL form used by the authoritative evidence resolver.

    The API persists this server-owned form in the approved publish payload so
    later execution checks hash the same URLs that were reviewed. Browser URL
    spelling differences (host case, fragments, or an explicit default HTTPS
    port) must never create a false-ready or false-blocked write boundary.
    """

    assets = _normalize_requested_assets(asset_manifest)
    return {
        "assets": [
            {
                **({"asset_id": item["asset_id"]} if item.get("asset_id") else {}),
                "asset_type": item["asset_type"],
                "role": item["role"],
                "url": item["url"],
            }
            for item in assets
        ]
    }


def resolve_publish_source_rights_evidence(
    repository: PublishEvidenceRepository,
    *,
    company_id: str,
    store_id: str,
    listing_project_identity: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
    evidence_refs: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one complete, server-owned source/rights evidence snapshot.

    The returned fingerprint excludes ``resolved_at`` so repeated resolution of
    unchanged persisted evidence is stable at approval, preflight, and execute.
    """

    clean_company_id = _safe_identifier(company_id, field="company_id")
    clean_store_id = _safe_identifier(store_id, field="store_id")
    project = _normalize_project_identity(listing_project_identity)
    refs = evidence_refs if isinstance(evidence_refs, Mapping) else {}
    report_id = _safe_identifier(refs.get("product_fact_report_id"), field="product_fact_report_id")
    report = _get_company_report(repository, company_id=clean_company_id, report_id=report_id)
    save_task: dict[str, Any] = {}
    if (report.get("report") or {}).get("merchant_save_attestation"):
        # Lookup is company-scoped and never uses an incoming task or assertion.
        try:
            save_task = repository.get_task(company_id=clean_company_id, task_id=str(report.get("task_id") or "")) or {}
        except (AttributeError, KeyError, TypeError, ValueError):
            save_task = {}
    packet = _validated_product_fact_report(
        report,
        company_id=clean_company_id,
        store_id=clean_store_id,
        project=project,
        merchant_save_task=save_task,
    )

    assets = _normalize_requested_assets(asset_manifest)
    source_records = packet.get("source_records") if isinstance(packet.get("source_records"), list) else []
    media_job_id = _optional_identifier(refs.get("media_job_id"))
    approved_media_assets: dict[tuple[str, str], dict[str, str]] = {}
    if media_job_id:
        approved_media_assets = _validated_media_job_assets(
            repository,
            company_id=clean_company_id,
            store_id=clean_store_id,
            project=project,
            media_job_id=media_job_id,
        )
    covered_assets: list[dict[str, str]] = []
    media_covered_count = 0
    for asset in assets:
        media_match = approved_media_assets.get((asset["asset_id"], asset["url"]))
        if media_match is not None:
            covered_assets.append(media_match)
            media_covered_count += 1
            continue
        matching_record = next(
            (
                item
                for item in source_records
                if isinstance(item, Mapping)
                and str(item.get("type") or "") == "merchant_product_image"
                and _normalized_https_url(item.get("url")) == asset["url"]
                and str(item.get("rights_status") or "") == "merchant_confirmed"
            ),
            None,
        )
        if matching_record is None:
            raise PublishSourceRightsEvidenceError(
                "publish_evidence_not_ready",
                f"image_rights_uncovered:{asset['url_sha256']}",
            )
        covered_assets.append(
            {
                "asset_id": asset["asset_id"],
                "url_sha256": asset["url_sha256"],
                "evidence_type": "merchant_product_fact_report",
                "evidence_id": report_id,
            }
        )

    source_mode = str(packet.get("source_mode") or "").strip()
    evidence: dict[str, Any] = {
        "contract_version": PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION,
        "status": "ready",
        "server_resolved": True,
        "scope": {
            "company_id": clean_company_id,
            "store_id": clean_store_id,
            "listing_project_key": project["key"],
        },
        "refs": {
            "product_fact_report_id": report_id,
            "media_job_id": media_job_id,
        },
        "product_source": {
            "status": "verified",
            "source_mode": source_mode,
            "evidence_type": "merchant_product_fact_report",
            "evidence_id": report_id,
        },
        "image_rights": {
            "status": "verified",
            "required_asset_count": len(assets),
            "covered_asset_count": len(covered_assets),
            "coverage_complete": len(covered_assets) == len(assets),
            "assets": covered_assets,
        },
        "secret_exposed": False,
    }
    if media_job_id and media_covered_count == 0:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_does_not_cover_requested_assets")
    evidence["fingerprint"] = _fingerprint(evidence)
    evidence["resolved_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return evidence


def validate_publish_source_rights_evidence(
    evidence: Mapping[str, Any],
    *,
    company_id: str,
    store_id: str,
    listing_project_identity: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the semantic integrity and scope of a stored evidence snapshot.

    This does not replace repository re-resolution at approval/execute time; it
    verifies that the stored snapshot is canonical, untampered, and covers the
    exact current asset manifest.
    """

    try:
        _validate_snapshot(
            evidence,
            company_id=company_id,
            store_id=store_id,
            listing_project_identity=listing_project_identity,
            asset_manifest=asset_manifest,
        )
    except PublishSourceRightsEvidenceError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        raise PublishSourceRightsEvidenceError(
            "publish_evidence_snapshot_invalid",
            "publish_evidence_shape_invalid",
        ) from exc
    return dict(evidence)


def _validate_snapshot(
    evidence: Mapping[str, Any],
    *,
    company_id: str,
    store_id: str,
    listing_project_identity: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
) -> None:
    if not isinstance(evidence, Mapping):
        _invalid_snapshot("publish_evidence_missing")
    expected_top_level = {
        "contract_version",
        "status",
        "server_resolved",
        "scope",
        "refs",
        "product_source",
        "image_rights",
        "secret_exposed",
        "fingerprint",
        "resolved_at",
    }
    if set(evidence) != expected_top_level:
        _invalid_snapshot("publish_evidence_fields_invalid")
    if (
        evidence.get("contract_version") != PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION
        or evidence.get("status") != "ready"
        or evidence.get("server_resolved") is not True
        or evidence.get("secret_exposed") is not False
    ):
        _invalid_snapshot("publish_evidence_state_invalid")

    project = _normalize_project_identity(listing_project_identity)
    scope = evidence.get("scope") if isinstance(evidence.get("scope"), Mapping) else {}
    if set(scope) != {"company_id", "store_id", "listing_project_key"}:
        _invalid_snapshot("publish_evidence_scope_fields_invalid")
    if scope != {
        "company_id": _safe_identifier(company_id, field="company_id"),
        "store_id": _safe_identifier(store_id, field="store_id"),
        "listing_project_key": project["key"],
    }:
        _invalid_snapshot("publish_evidence_scope_mismatch")

    refs = evidence.get("refs") if isinstance(evidence.get("refs"), Mapping) else {}
    if set(refs) != {"product_fact_report_id", "media_job_id"}:
        _invalid_snapshot("publish_evidence_refs_invalid")
    report_id = _safe_identifier(refs.get("product_fact_report_id"), field="product_fact_report_id")
    media_job_id = _optional_identifier(refs.get("media_job_id"))

    source = evidence.get("product_source") if isinstance(evidence.get("product_source"), Mapping) else {}
    if set(source) != {"status", "source_mode", "evidence_type", "evidence_id"}:
        _invalid_snapshot("product_source_fields_invalid")
    if not (
        source.get("status") == "verified"
        and source.get("source_mode") in {"merchant_source_supplied", "merchant_owned_product"}
        and source.get("evidence_type") == "merchant_product_fact_report"
        and source.get("evidence_id") == report_id
    ):
        _invalid_snapshot("product_source_evidence_invalid")

    requested = _normalize_requested_assets(asset_manifest)
    rights = evidence.get("image_rights") if isinstance(evidence.get("image_rights"), Mapping) else {}
    if set(rights) != {
        "status",
        "required_asset_count",
        "covered_asset_count",
        "coverage_complete",
        "assets",
    }:
        _invalid_snapshot("image_rights_fields_invalid")
    covered = rights.get("assets") if isinstance(rights.get("assets"), list) else []
    required_count = rights.get("required_asset_count")
    covered_count = rights.get("covered_asset_count")
    if not (
        rights.get("status") == "verified"
        and rights.get("coverage_complete") is True
        and type(required_count) is int
        and type(covered_count) is int
        and required_count == covered_count == len(requested) == len(covered)
        and required_count > 0
    ):
        _invalid_snapshot("image_rights_coverage_invalid")

    expected_assets = {(item["asset_id"], item["url_sha256"]) for item in requested}
    actual_assets: set[tuple[str, str]] = set()
    for item in covered:
        if not isinstance(item, Mapping) or set(item) != {"asset_id", "url_sha256", "evidence_type", "evidence_id"}:
            _invalid_snapshot("image_rights_asset_fields_invalid")
        asset_id = _optional_identifier(item.get("asset_id"))
        url_sha256 = str(item.get("url_sha256") or "")
        evidence_type = str(item.get("evidence_type") or "")
        evidence_id = str(item.get("evidence_id") or "")
        if len(url_sha256) != 64 or any(char not in "0123456789abcdef" for char in url_sha256):
            _invalid_snapshot("image_rights_url_hash_invalid")
        if evidence_type == "merchant_product_fact_report":
            if evidence_id != report_id:
                _invalid_snapshot("image_rights_report_binding_invalid")
        elif evidence_type == "approved_media_asset_job":
            if not asset_id or not media_job_id or evidence_id != media_job_id:
                _invalid_snapshot("image_rights_media_binding_invalid")
        else:
            _invalid_snapshot("image_rights_evidence_type_invalid")
        actual_assets.add((asset_id, url_sha256))
    if actual_assets != expected_assets or len(actual_assets) != len(covered):
        _invalid_snapshot("image_rights_asset_coverage_mismatch")

    resolved_at = str(evidence.get("resolved_at") or "")
    if not resolved_at.endswith("Z"):
        _invalid_snapshot("publish_evidence_resolved_at_invalid")
    datetime.fromisoformat(resolved_at[:-1] + "+00:00")
    stored_fingerprint = str(evidence.get("fingerprint") or "")
    unsigned = {key: value for key, value in evidence.items() if key not in {"fingerprint", "resolved_at"}}
    if stored_fingerprint != _fingerprint(unsigned):
        _invalid_snapshot("publish_evidence_fingerprint_invalid")


def _invalid_snapshot(blocker: str) -> None:
    raise PublishSourceRightsEvidenceError("publish_evidence_snapshot_invalid", blocker)


def _validated_media_job_assets(
    repository: PublishEvidenceRepository,
    *,
    company_id: str,
    store_id: str,
    project: Mapping[str, str],
    media_job_id: str,
) -> dict[tuple[str, str], dict[str, str]]:
    media_job = repository.get_media_asset_job(company_id=company_id, media_job_id=media_job_id)
    if not isinstance(media_job, dict):
        raise PublishSourceRightsEvidenceError("publish_evidence_reference_not_found", "media_job_not_found")
    if str(media_job.get("company_id") or "") != company_id or str(media_job.get("store_id") or "") != store_id:
        raise PublishSourceRightsEvidenceError("publish_evidence_scope_mismatch", "media_job_scope_mismatch")
    if media_job.get("status") != "approved_for_listing":
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_not_approved")
    if media_job.get("live_provider_called") is not True:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_provider_result_missing")
    if media_job.get("spend_now_allowed") is True or media_job.get("secret_exposed") is not False:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_unsafe_boundary")
    validation = media_job.get("asset_manifest_validation") if isinstance(media_job.get("asset_manifest_validation"), dict) else {}
    if validation.get("status") != "manifest_ready":
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_manifest_not_ready")
    job_payload = media_job.get("job") if isinstance(media_job.get("job"), dict) else {}
    job_spec = job_payload.get("job_spec") if isinstance(job_payload.get("job_spec"), dict) else {}
    inputs = job_spec.get("inputs") if isinstance(job_spec.get("inputs"), dict) else {}
    facts = inputs.get("product_facts") if isinstance(inputs.get("product_facts"), dict) else {}
    if str(facts.get("listing_project_key") or "") != project["key"]:
        raise PublishSourceRightsEvidenceError("publish_evidence_scope_mismatch", "media_job_listing_project_mismatch")
    reference_images = facts.get("reference_images") if isinstance(facts.get("reference_images"), list) else []
    grounded = bool(str(facts.get("source_asset_id") or "").strip()) or facts.get("private_source_transport") == "backend_asset_id"
    grounded = grounded or any(_normalized_https_url(item) for item in reference_images)
    creative = inputs.get("creative_job_spec") if isinstance(inputs.get("creative_job_spec"), dict) else {}
    if creative.get("output_safety_mode") == "concept_reference_only" or not grounded:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_concept_only_or_ungrounded")

    merchant_review = media_job.get("merchant_review") if isinstance(media_job.get("merchant_review"), dict) else {}
    confirmations = merchant_review.get("confirmations") if isinstance(merchant_review.get("confirmations"), dict) else {}
    if not (
        merchant_review.get("decision") == "approve_for_listing_draft"
        and merchant_review.get("listing_draft_only") is True
        and merchant_review.get("triggers_real_platform_write") is False
        and merchant_review.get("secret_exposed") is False
        and bool(str(merchant_review.get("reviewed_by") or "").strip())
        and confirmations.get("fact_consistency_confirmed") is True
        and confirmations.get("commercial_rights_confirmed") is True
        and confirmations.get("platform_rules_checked") is True
    ):
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_merchant_review_not_approved")
    asset_review = media_job.get("asset_review") if isinstance(media_job.get("asset_review"), dict) else {}
    if not (
        asset_review.get("status") == "approved_for_listing_draft"
        and asset_review.get("listing_use_status") == "approved_for_listing_draft"
        and bool(str(asset_review.get("reviewed_at") or "").strip())
    ):
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_asset_review_not_approved")

    manifest = media_job.get("asset_manifest") if isinstance(media_job.get("asset_manifest"), list) else []
    approved: dict[tuple[str, str], dict[str, str]] = {}
    for item in manifest:
        if not isinstance(item, Mapping):
            continue
        asset_id = _optional_identifier(item.get("asset_id") or item.get("id"))
        url = _normalized_https_url(item.get("url_or_file_path") or item.get("url"))
        if not asset_id or not url:
            continue
        if item.get("asset_type") == "concept_reference_image" or item.get("listing_use_status") == "concept_only_not_eligible_for_listing":
            continue
        if not (
            item.get("fact_review_status") == "confirmed_by_merchant"
            and item.get("commercial_use_status") == "confirmed_by_merchant"
            and item.get("listing_use_status") == "approved_for_listing_draft"
            and item.get("review_status") == "approved_for_listing_draft"
        ):
            continue
        approved[(asset_id, url)] = {
            "asset_id": asset_id,
            "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "evidence_type": "approved_media_asset_job",
            "evidence_id": media_job_id,
        }
    if not approved:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "media_job_has_no_approved_assets")
    return approved


def _validated_product_fact_report(
    report: Mapping[str, Any],
    *,
    company_id: str,
    store_id: str,
    project: Mapping[str, str],
    merchant_save_task: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if str(report.get("report_type") or "") != "merchant.product_facts":
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "product_fact_report_type_invalid")
    if str(report.get("company_id") or "") != company_id or str(report.get("store_id") or "") != store_id:
        raise PublishSourceRightsEvidenceError("publish_evidence_scope_mismatch", "product_fact_report_scope_mismatch")
    payload = report.get("report") if isinstance(report.get("report"), dict) else {}
    report_project = _normalize_project_identity(payload.get("listing_project_identity"))
    if report_project != project:
        raise PublishSourceRightsEvidenceError("publish_evidence_scope_mismatch", "listing_project_mismatch")
    packet = payload.get("merchant_product_fact_packet") if isinstance(payload.get("merchant_product_fact_packet"), dict) else {}
    # Keep visual provenance intact. New saves prove authentication separately
    # through the server-owned report AND its completed fact-save task. Legacy
    # authenticated (non-vision) reports retain their existing validation path.
    has_attestation = "merchant_save_attestation" in payload
    if (has_attestation and not valid_merchant_fact_save_attestation(report, merchant_save_task or {})) or (
        not has_attestation and packet.get("source") != "authenticated_merchant_request"
    ):
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "product_facts_not_authenticated")
    if packet.get("simulation_only") is True:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "simulation_only_product_facts")
    facts = packet.get("merchant_confirmed_facts") if isinstance(packet.get("merchant_confirmed_facts"), dict) else {}
    source_url = _normalized_http_url(facts.get("source_url"))
    owned = facts.get("merchant_owned_product_confirmed") is True
    if not source_url and not owned:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "product_source_not_attested")
    if facts.get("image_rights_confirmed") is not True:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "image_rights_not_attested")
    source_mode = str(packet.get("source_mode") or "")
    expected_source_mode = "merchant_source_supplied" if source_url else "merchant_owned_product"
    if source_mode != expected_source_mode:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "product_source_mode_inconsistent")
    return dict(packet)


def _get_company_report(
    repository: PublishEvidenceRepository,
    *,
    company_id: str,
    report_id: str,
) -> dict[str, Any]:
    reports = repository.list_reports(company_id=company_id, limit=None)
    matches = [item for item in reports if isinstance(item, dict) and str(item.get("report_id") or "") == report_id]
    if len(matches) != 1:
        code = "publish_evidence_reference_not_found" if not matches else "publish_evidence_reference_not_unique"
        raise PublishSourceRightsEvidenceError(code, "product_fact_report_not_found")
    selected = matches[0]
    if str(selected.get("report_type") or "") == "merchant.product_facts":
        selected_payload = selected.get("report") if isinstance(selected.get("report"), Mapping) else {}
        selected_project_key = _normalize_project_identity(
            selected_payload.get("listing_project_identity")
        )["key"]
        selected_store_id = str(selected.get("store_id") or "")
        checkpoints: list[dict[str, Any]] = []
        for item in reports:
            if not isinstance(item, Mapping) or str(item.get("report_type") or "") != "merchant.product_facts":
                continue
            if str(item.get("store_id") or "") != selected_store_id:
                continue
            payload = item.get("report") if isinstance(item.get("report"), Mapping) else {}
            raw_project = payload.get("listing_project_identity")
            raw_project = raw_project if isinstance(raw_project, Mapping) else {}
            # Scope first: a legacy/unrelated report must not veto a valid
            # selected project merely because its own identity is malformed.
            # Still validate the selected record and all same-project records
            # strictly, including malformed successors and revoked rights.
            if str(raw_project.get("key") or "").strip() != selected_project_key:
                continue
            if (
                _normalize_project_identity(raw_project)["key"]
                == selected_project_key
            ):
                checkpoints.append(dict(item))
        latest = max(
            checkpoints,
            key=lambda item: (str(item.get("created_at") or ""), str(item.get("report_id") or "")),
            default=selected,
        )
        if str(latest.get("report_id") or "") != report_id:
            raise PublishSourceRightsEvidenceError(
                "publish_evidence_changed",
                "product_fact_report_superseded",
            )
    return selected


def _normalize_requested_assets(asset_manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_assets = asset_manifest.get("assets") if isinstance(asset_manifest, Mapping) else None
    if not isinstance(raw_assets, list) or not raw_assets:
        raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "image_assets_missing")
    assets: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(raw_assets):
        if not isinstance(item, Mapping):
            raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "image_asset_invalid")
        asset_type = str(item.get("asset_type") or "image").strip()
        role = str(item.get("role") or ("main" if index == 0 else "gallery")).strip()
        if asset_type not in {"image", "product_image"} or role not in {"main", "gallery"}:
            raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "image_asset_contract_invalid")
        url = _normalized_https_url(item.get("url") or item.get("url_or_file_path"))
        if not url:
            raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "image_asset_https_url_required")
        if url in seen_urls:
            raise PublishSourceRightsEvidenceError("publish_evidence_not_ready", "duplicate_image_asset_url")
        seen_urls.add(url)
        assets.append(
            {
                "asset_id": _optional_identifier(item.get("asset_id")),
                "asset_type": asset_type,
                "role": role,
                "url": url,
                "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            }
        )
    return assets


def _normalize_project_identity(value: Any) -> dict[str, str]:
    raw = value if isinstance(value, Mapping) else {}
    key = _safe_identifier(raw.get("key"), field="listing_project_key")
    return {
        "key": key,
        "source_report_id": _optional_identifier(raw.get("source_report_id") or raw.get("source_id")),
        "candidate_id": _optional_identifier(raw.get("candidate_id")),
    }


def _safe_identifier(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 180 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in text):
        raise PublishSourceRightsEvidenceError("publish_evidence_reference_invalid", f"{field}_invalid")
    return text


def _optional_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 180 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in text):
        raise PublishSourceRightsEvidenceError("publish_evidence_reference_invalid", "optional_identifier_invalid")
    return text


def _normalized_http_url(value: Any) -> str:
    return _normalized_url(value, schemes={"http", "https"})


def _normalized_https_url(value: Any) -> str:
    return _normalized_url(value, schemes={"https"})


def _normalized_url(value: Any, *, schemes: set[str]) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 2048:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    try:
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower().rstrip(".")
        username = parsed.username
        password = parsed.password
        port = parsed.port
    except ValueError:
        return ""
    if scheme not in schemes or not hostname or username or password:
        return ""
    default_port = 443 if scheme == "https" else 80
    netloc = hostname if port in (None, default_port) else f"{hostname}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
