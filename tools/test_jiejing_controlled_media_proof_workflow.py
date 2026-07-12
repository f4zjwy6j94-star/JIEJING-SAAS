from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    workflow = (ROOT / ".github" / "workflows" / "jiejing-controlled-media-proof.yml").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "github-actions" / "jiejing-controlled-media-proof.sh").read_text(encoding="utf-8")

    required_workflow = (
        "workflow_dispatch:",
        "generate one controlled media proof",
        "runs-on: [self-hosted, jiejing-staging]",
        "actions/upload-artifact@v4",
        "retention-days: 7",
        "bash deploy/github-actions/jiejing-controlled-media-proof.sh",
    )
    for marker in required_workflow:
        if marker not in workflow:
            raise AssertionError(f"controlled media workflow is missing {marker}")

    required_script = (
        "REFUSE_CONTROLLED_MEDIA_CONFIRMATION_MISMATCH",
        "real_platform_writes_enabled",
        "JIEJING_CONTROLLED_MEDIA_VIDEO_PROOF=true",
        "docker compose",
        "file_signature_valid",
        "SECRET_EXPOSED=false",
    )
    for marker in required_script:
        if marker not in script:
            raise AssertionError(f"controlled media script is missing {marker}")
    if "docker compose down" in script or "docker volume rm" in script:
        raise AssertionError("controlled media proof must not stop services or remove volumes")
    if "printenv" in script or "cat ../../private" in script:
        raise AssertionError("controlled media proof must not print provider credentials")

    print("PASS jiejing_controlled_media_proof_workflow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

