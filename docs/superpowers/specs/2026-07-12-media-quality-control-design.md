# JIEJING Media Quality Control Design

Date: 2026-07-12
Status: approved for implementation

## Goal

Make the Media Studio understandable to ordinary merchants while preserving a provider-neutral backend. Merchants choose the business purpose, output quality, and allowed creative variation. JIEJING translates those choices into provider-specific requests and keeps every result inside the existing AssetManifest review boundary.

## Merchant Experience

The existing page structure remains unchanged. The four business templates stay visible:

- eBay listing package
- Main image optimization
- Lifestyle scene images
- Detail-page explanation images

Advanced settings add one explicit generation-quality control:

- Quick sample: low-cost direction check
- Standard quality: recommended default
- Fine quality: final candidate generation

The existing fidelity control remains the merchant-facing creative boundary:

- Strictly preserve the physical product
- Improve only lighting and background
- Creative scene exploration without changing the product subject

Product structure, color, material, included parts, logo, and confirmed specifications are always locked. The merchant cannot disable these fact locks. Creative exploration remains a concept reference and is not eligible for Listing use until a grounded review passes.

## Video Boundary

Image templates do not enable video automatically. A merchant must explicitly choose a supported real-video duration. Script and storyboard generation remains a separate text action and must never be presented as a returned video file.

The currently configured FAL video driver supports 6-second and 10-second output. The UI must not promise a 15-second generated video until a provider capable of that duration is configured and verified.

## Provider Contract

Frontend values are provider-neutral:

- `generation_tier`: `draft`, `standard`, or `high_quality`
- `quality_mode`: `fidelity_first`, `balanced`, or `creative_exploration`
- `fact_locks`: an immutable list of product facts
- `video_duration_seconds`: `0`, `6`, or `10`

The backend maps generation tiers to provider-specific quality values. For the current FAL GPT Image 2 driver the mapping is `low`, `medium`, and `high`. A grounded product request uses the image-edit endpoint and includes the signed reference image URL. An ungrounded request uses text-to-image and remains concept-only.

The FAL name, model IDs, credentials, raw provider response, and secret source remain backend-only.

## Cost And Failure Behavior

Templates default to no video. The idempotency key includes quality and video choices. Cost limits scale with the selected quality tier and requested outputs. Missing images or video are reported as partial output, not success.

No generation result writes to eBay. Results require AssetManifest validation, merchant review, Listing writeback, preflight, and confirmation-center approval.

## Verification

- Contract tests cover no-surprise video defaults, quality mapping, fact locks, reference-image edit routing, supported durations, and partial video failure.
- Frontend QA covers desktop and mobile Media Studio rendering, template selection, quality selection, and payload formation.
- Run JavaScript syntax checks, Python compilation, secret scan, focused tests, and the precloud deployment gate.
- Staging deployment remains a separate manual dry-run and explicitly approved apply step.

## Controlled staging proof

One manual GitHub Actions workflow may generate a single synthetic image and short video inside the staging SaaS container. It requires an exact confirmation phrase, refuses to run while real platform writes are enabled, keeps provider credentials inside the container, validates downloaded file signatures, and retains the proof artifact for seven days. The proof product is explicitly synthetic and must never be treated as a real supplier product or Listing asset.
