#!/usr/bin/env bash
set -euo pipefail

# Runs one explicitly authorized media-provider proof inside the staging SaaS
# container. Provider credentials remain in the container environment.

EXPECTED_CONFIRM="generate one controlled media proof"
CONFIRM="${JIEJING_CONTROLLED_MEDIA_PROOF_CONFIRM:-}"
PRODUCT="${JIEJING_ACCEPTANCE_PRODUCT:-}"
APP_DIR="${JIEJING_STAGING_APP_DIR:-/opt/jiejing-staging/app}"
WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"

if [[ "$CONFIRM" != "$EXPECTED_CONFIRM" ]]; then
  echo "REFUSE_CONTROLLED_MEDIA_CONFIRMATION_MISMATCH=1" >&2
  exit 61
fi

if [[ -z "$PRODUCT" || ${#PRODUCT} -gt 500 ]]; then
  echo "REFUSE_INVALID_ACCEPTANCE_PRODUCT=1" >&2
  exit 62
fi

resolved_app_dir="$(readlink -f -- "$APP_DIR" 2>/dev/null || true)"
resolved_workspace="$(readlink -f -- "$WORKSPACE" 2>/dev/null || true)"
if [[ -z "$resolved_app_dir" || -z "$resolved_workspace" ]]; then
  echo "REFUSE_UNRESOLVED_CONTROLLED_MEDIA_PATH=1" >&2
  exit 63
fi

case "$resolved_app_dir" in
  /opt/jiejing-staging/app|/opt/jiejing-staging/app/*) ;;
  *) echo "REFUSE_APP_DIR_OUTSIDE_STAGING=$resolved_app_dir" >&2; exit 64 ;;
esac

cd "$resolved_app_dir"
COMPOSE_FILE="deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  COMPOSE_FILE="deploy/docker-compose.public-staging.yml"
fi
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
COST_SAVER_OVERRIDE="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$resolved_app_dir/../private/docker-compose.cost-saver-local.yml}"
if [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" && -f "$COST_SAVER_OVERRIDE" ]]; then
  COMPOSE_ARGS+=(-f "$COST_SAVER_OVERRIDE")
fi

health_json="$(sudo -n docker compose "${COMPOSE_ARGS[@]}" exec -T jiejing-saas python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=10).read().decode())")"
HEALTH_JSON="$health_json" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["HEALTH_JSON"])
if payload.get("real_platform_writes_enabled") is not False:
    raise SystemExit("REFUSE_REAL_PLATFORM_WRITES_ENABLED=1")
if payload.get("secret_exposed") is not False:
    raise SystemExit("REFUSE_SECRET_EXPOSURE_SIGNAL=1")
PY

sudo -n docker compose "${COMPOSE_ARGS[@]}" exec -T \
  -e JIEJING_CONTROLLED_MEDIA_VIDEO_PROOF=true \
  -e JIEJING_ACCEPTANCE_PRODUCT="$PRODUCT" \
  jiejing-saas python tools/jiejing_controlled_media_video_proof.py

container_id="$(sudo -n docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-saas)"
if [[ -z "$container_id" ]]; then
  echo "REFUSE_SAAS_CONTAINER_NOT_FOUND=1" >&2
  exit 65
fi

artifact_root="$resolved_workspace/output/jiejing-controlled-media-video-proof"
case "$artifact_root" in
  "$resolved_workspace"/output/jiejing-controlled-media-video-proof) ;;
  *) echo "REFUSE_ARTIFACT_PATH_OUTSIDE_WORKSPACE=$artifact_root" >&2; exit 66 ;;
esac
rm -rf -- "$artifact_root"
mkdir -p "$artifact_root"
sudo -n docker cp "$container_id:/app/output/jiejing-controlled-media-video-proof/." "$artifact_root/"
sudo -n chown -R "$(id -u):$(id -g)" "$artifact_root"

python3 - "$artifact_root/latest.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("ok") is not True:
    raise SystemExit("CONTROLLED_MEDIA_PROOF_NOT_OK=1")
if payload.get("real_platform_writes_enabled") is not False:
    raise SystemExit("CONTROLLED_MEDIA_PROOF_WRITE_BOUNDARY_FAILED=1")
if payload.get("secret_exposed") is not False:
    raise SystemExit("CONTROLLED_MEDIA_PROOF_SECRET_BOUNDARY_FAILED=1")
assets = payload.get("downloaded_assets") or []
asset_types = {str(item.get("asset_type") or "") for item in assets}
if not any("image" in item for item in asset_types) or not any("video" in item for item in asset_types):
    raise SystemExit("CONTROLLED_MEDIA_PROOF_ASSET_TYPES_MISSING=1")
if not assets or not all(item.get("file_signature_valid") is True for item in assets):
    raise SystemExit("CONTROLLED_MEDIA_PROOF_FILE_SIGNATURE_FAILED=1")
print(json.dumps({"ok": True, "asset_count": payload.get("asset_count"), "secret_exposed": False}))
PY

echo "CONTROLLED_MEDIA_PROOF_COMPLETED=1"
echo "REAL_PLATFORM_WRITES_ENABLED=false"
echo "SECRET_EXPOSED=false"
