#!/usr/bin/env python3
"""Pure unit checks for authoritative publish source/rights evidence."""

from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.publish_source_rights import (  # noqa: E402
    PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION,
    PublishSourceRightsEvidenceError,
    canonicalize_publish_asset_manifest,
    resolve_publish_source_rights_evidence,
    validate_publish_source_rights_evidence,
)


class EvidenceRepository:
    def __init__(self, *, reports: list[dict[str, Any]], media_jobs: dict[str, dict[str, Any]] | None = None) -> None:
        self.reports = reports
        self.media_jobs = media_jobs or {}

    def list_reports(self, *, company_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        del limit
        return [item for item in self.reports if item.get("company_id") == company_id]

    def get_media_asset_job(self, *, company_id: str, media_job_id: str) -> dict[str, Any] | None:
        item = self.media_jobs.get(media_job_id)
        if item and item.get("company_id") == company_id:
            return item
        return None


def product_fact_report(
    *,
    image_url: str = "https://cdn.example.test/product-main.jpg",
    owned_confirmed: bool = True,
    image_rights_confirmed: bool = True,
    source_url: str = "",
) -> dict[str, Any]:
    merchant_facts: dict[str, Any] = {
        "image_rights_confirmed": image_rights_confirmed,
        "merchant_owned_product_confirmed": owned_confirmed,
    }
    source_records: list[dict[str, Any]] = []
    if source_url:
        merchant_facts["source_url"] = source_url
        source_records.append(
            {"type": "merchant_product_link", "url": source_url, "rights_status": "not_applicable"}
        )
    source_records.append(
        {
            "type": "merchant_product_image",
            "url": image_url,
            "rights_status": "merchant_confirmed" if image_rights_confirmed else "pending",
        }
    )
    return {
        "report_id": "report-product-facts-a",
        "report_type": "merchant.product_facts",
        "company_id": "company-a",
        "store_id": "store-a",
        "report": {
            "listing_project_identity": {
                "key": "listing-project-a",
                "source_report_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            "merchant_product_fact_packet": {
                "source": "authenticated_merchant_request",
                "source_mode": "merchant_source_supplied" if source_url else "merchant_owned_product",
                "simulation_only": False,
                "merchant_confirmed_facts": merchant_facts,
                "source_records": source_records,
            },
        },
    }


def approved_media_job(*, image_url: str = "https://cdn.example.test/generated-main.jpg") -> dict[str, Any]:
    return {
        "media_job_id": "media-job-approved-a",
        "company_id": "company-a",
        "store_id": "store-a",
        "status": "approved_for_listing",
        "live_provider_called": True,
        "spend_now_allowed": False,
        "secret_exposed": False,
        "job": {
            "job_spec": {
                "inputs": {
                    "product_facts": {
                        "listing_project_key": "listing-project-a",
                        "source_asset_id": "media-source-a",
                        "private_source_transport": "backend_asset_id",
                    }
                }
            }
        },
        "asset_manifest_validation": {"status": "manifest_ready"},
        "merchant_review": {
            "decision": "approve_for_listing_draft",
            "listing_draft_only": True,
            "triggers_real_platform_write": False,
            "reviewed_by": "merchant-a",
            "secret_exposed": False,
            "confirmations": {
                "fact_consistency_confirmed": True,
                "commercial_rights_confirmed": True,
                "platform_rules_checked": True,
            },
        },
        "asset_review": {
            "status": "approved_for_listing_draft",
            "listing_use_status": "approved_for_listing_draft",
            "reviewed_at": "2026-08-31T10:00:00Z",
        },
        "asset_manifest": [
            {
                "asset_id": "generated-asset-a",
                "asset_type": "product_image",
                "url_or_file_path": image_url,
                "fact_review_status": "confirmed_by_merchant",
                "commercial_use_status": "confirmed_by_merchant",
                "listing_use_status": "approved_for_listing_draft",
                "review_status": "approved_for_listing_draft",
            }
        ],
    }


def main() -> int:
    image_url = "https://cdn.example.test/product-main.jpg"
    repository = EvidenceRepository(reports=[product_fact_report(image_url=image_url)])
    evidence = resolve_publish_source_rights_evidence(
        repository,
        company_id="company-a",
        store_id="store-a",
        listing_project_identity={
            "key": "listing-project-a",
            "source_id": "market-report-a",
            "candidate_id": "candidate-a",
        },
        asset_manifest={
            "assets": [
                {
                    "asset_type": "image",
                    "role": "main",
                    "url": image_url,
                    "rights_status": "attacker-controlled",
                    "commercial_use_status": "attacker-controlled",
                }
            ]
        },
        evidence_refs={"product_fact_report_id": "report-product-facts-a"},
    )
    assert evidence["contract_version"] == PUBLISH_SOURCE_RIGHTS_CONTRACT_VERSION
    assert evidence["status"] == "ready"
    assert evidence["server_resolved"] is True
    assert evidence["scope"] == {
        "company_id": "company-a",
        "store_id": "store-a",
        "listing_project_key": "listing-project-a",
    }
    assert evidence["image_rights"]["required_asset_count"] == 1
    assert evidence["image_rights"]["covered_asset_count"] == 1
    assert evidence["image_rights"]["coverage_complete"] is True
    assert evidence["image_rights"]["assets"][0]["evidence_type"] == "merchant_product_fact_report"
    assert "rights_status" not in evidence["image_rights"]["assets"][0]
    assert len(evidence["image_rights"]["assets"][0]["url_sha256"]) == 64
    assert len(evidence["fingerprint"]) == 64
    assert evidence["secret_exposed"] is False

    canonical_manifest = canonicalize_publish_asset_manifest(
        {
            "assets": [
                {
                    "asset_type": "image",
                    "role": "main",
                    "url": "https://CDN.EXAMPLE.TEST:443/product-main.jpg#browser-fragment",
                }
            ]
        }
    )
    assert canonical_manifest["assets"][0]["url"] == "https://cdn.example.test/product-main.jpg"

    older = product_fact_report(image_url=image_url)
    older["created_at"] = "2026-08-31T00:00:00+00:00"
    newer = deepcopy(older)
    newer["report_id"] = "report-product-facts-b"
    newer["created_at"] = "2026-08-31T00:01:00+00:00"
    newer["report"]["merchant_product_fact_packet"]["merchant_confirmed_facts"][
        "image_rights_confirmed"
    ] = False
    try:
        resolve_publish_source_rights_evidence(
            EvidenceRepository(reports=[older, newer]),
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={"assets": [{"asset_type": "image", "role": "main", "url": image_url}]},
            evidence_refs={"product_fact_report_id": older["report_id"]},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_changed"
        assert "product_fact_report_superseded" in exc.blockers
    else:
        raise AssertionError("an older positive fact checkpoint must not survive a newer project checkpoint")

    generated_url = "https://cdn.example.test/generated-main.jpg"
    media_repository = EvidenceRepository(
        reports=[product_fact_report()],
        media_jobs={"media-job-approved-a": approved_media_job(image_url=generated_url)},
    )
    generated_evidence = resolve_publish_source_rights_evidence(
        media_repository,
        company_id="company-a",
        store_id="store-a",
        listing_project_identity={
            "key": "listing-project-a",
            "source_id": "market-report-a",
            "candidate_id": "candidate-a",
        },
        asset_manifest={
            "assets": [
                {
                    "asset_id": "generated-asset-a",
                    "asset_type": "product_image",
                    "role": "main",
                    "url": generated_url,
                }
            ]
        },
        evidence_refs={
            "product_fact_report_id": "report-product-facts-a",
            "media_job_id": "media-job-approved-a",
        },
    )
    generated_asset = generated_evidence["image_rights"]["assets"][0]
    assert generated_asset["evidence_type"] == "approved_media_asset_job"
    assert generated_asset["evidence_id"] == "media-job-approved-a"
    assert generated_asset["asset_id"] == "generated-asset-a"

    try:
        resolve_publish_source_rights_evidence(
            EvidenceRepository(reports=[product_fact_report(owned_confirmed=False)]),
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={"assets": [{"asset_type": "image", "role": "main", "url": image_url}]},
            evidence_refs={"product_fact_report_id": "report-product-facts-a"},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_not_ready"
        assert "product_source_not_attested" in exc.blockers
    else:
        raise AssertionError("absence of source URL must not be inferred as merchant ownership")

    unknown_url = "https://cdn.example.test/unreviewed-second.jpg"
    try:
        resolve_publish_source_rights_evidence(
            repository,
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={
                "assets": [
                    {"asset_type": "image", "role": "main", "url": image_url},
                    {"asset_type": "image", "role": "gallery", "url": unknown_url},
                ]
            },
            evidence_refs={"product_fact_report_id": "report-product-facts-a"},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_not_ready"
        assert any(item.startswith("image_rights_uncovered:") for item in exc.blockers)
    else:
        raise AssertionError("one reviewed image must not cover an unreviewed gallery image")

    try:
        resolve_publish_source_rights_evidence(
            repository,
            company_id="company-a",
            store_id="store-other",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={"assets": [{"asset_type": "image", "role": "main", "url": image_url}]},
            evidence_refs={"product_fact_report_id": "report-product-facts-a"},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_scope_mismatch"
        assert "product_fact_report_scope_mismatch" in exc.blockers
    else:
        raise AssertionError("product-fact evidence must not cross store scope")

    revoked_job = approved_media_job(image_url=generated_url)
    revoked_job["status"] = "needs_rework"
    try:
        resolve_publish_source_rights_evidence(
            EvidenceRepository(
                reports=[product_fact_report()],
                media_jobs={"media-job-approved-a": revoked_job},
            ),
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={
                "assets": [
                    {
                        "asset_id": "generated-asset-a",
                        "asset_type": "product_image",
                        "role": "main",
                        "url": generated_url,
                    }
                ]
            },
            evidence_refs={
                "product_fact_report_id": "report-product-facts-a",
                "media_job_id": "media-job-approved-a",
            },
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_not_ready"
        assert "media_job_not_approved" in exc.blockers
    else:
        raise AssertionError("a revoked media review must block fresh resolution")

    repeated = resolve_publish_source_rights_evidence(
        repository,
        company_id="company-a",
        store_id="store-a",
        listing_project_identity={
            "key": "listing-project-a",
            "source_id": "market-report-a",
            "candidate_id": "candidate-a",
        },
        asset_manifest={"assets": [{"asset_type": "image", "role": "main", "url": image_url}]},
        evidence_refs={"product_fact_report_id": "report-product-facts-a"},
    )
    assert repeated["fingerprint"] == evidence["fingerprint"]

    supplier_evidence = resolve_publish_source_rights_evidence(
        EvidenceRepository(
            reports=[
                product_fact_report(
                    owned_confirmed=False,
                    source_url="https://supplier.example.test/products/incense-burner",
                )
            ]
        ),
        company_id="company-a",
        store_id="store-a",
        listing_project_identity={
            "key": "listing-project-a",
            "source_id": "market-report-a",
            "candidate_id": "candidate-a",
        },
        asset_manifest={"assets": [{"asset_type": "image", "role": "main", "url": image_url}]},
        evidence_refs={"product_fact_report_id": "report-product-facts-a"},
    )
    assert supplier_evidence["product_source"]["source_mode"] == "merchant_source_supplied"

    try:
        resolve_publish_source_rights_evidence(
            EvidenceRepository(reports=[product_fact_report(image_rights_confirmed=False)]),
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={
                "assets": [
                    {
                        "asset_type": "image",
                        "role": "main",
                        "url": image_url,
                        "rights_status": "merchant_confirmed",
                        "commercial_use_status": "confirmed_by_merchant",
                    }
                ]
            },
            evidence_refs={"product_fact_report_id": "report-product-facts-a"},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_not_ready"
        assert "image_rights_not_attested" in exc.blockers
    else:
        raise AssertionError("client-provided rights fields must never award image rights")

    try:
        resolve_publish_source_rights_evidence(
            repository,
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={
                "assets": [
                    {
                        "asset_type": "image",
                        "role": "main",
                        "url": "https://cdn.example.test:bad/image.jpg",
                    }
                ]
            },
            evidence_refs={"product_fact_report_id": "report-product-facts-a"},
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_not_ready"
        assert "image_asset_https_url_required" in exc.blockers
    else:
        raise AssertionError("malformed media URLs must fail closed with a structured denial")

    validated = validate_publish_source_rights_evidence(
        generated_evidence,
        company_id="company-a",
        store_id="store-a",
        listing_project_identity={
            "key": "listing-project-a",
            "source_id": "market-report-a",
            "candidate_id": "candidate-a",
        },
        asset_manifest={
            "assets": [
                {
                    "asset_id": "generated-asset-a",
                    "asset_type": "product_image",
                    "role": "main",
                    "url": generated_url,
                }
            ]
        },
    )
    assert validated["status"] == "ready"
    assert validated["fingerprint"] == generated_evidence["fingerprint"]
    tampered = {
        **generated_evidence,
        "image_rights": {**generated_evidence["image_rights"], "covered_asset_count": 2},
    }
    try:
        validate_publish_source_rights_evidence(
            tampered,
            company_id="company-a",
            store_id="store-a",
            listing_project_identity={
                "key": "listing-project-a",
                "source_id": "market-report-a",
                "candidate_id": "candidate-a",
            },
            asset_manifest={
                "assets": [
                    {
                        "asset_id": "generated-asset-a",
                        "asset_type": "product_image",
                        "role": "main",
                        "url": generated_url,
                    }
                ]
            },
        )
    except PublishSourceRightsEvidenceError as exc:
        assert exc.code == "publish_evidence_snapshot_invalid"
        assert exc.to_dict()["secret_exposed"] is False
    else:
        raise AssertionError("tampered image-rights counts must be rejected")
    print("PASS jiejing_publish_source_rights_evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
