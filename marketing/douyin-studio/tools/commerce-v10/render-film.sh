#!/usr/bin/env bash
set -euo pipefail
film_dir="${JIEJING_V10_OUTPUT:-/workspace/jiejing-deliverables/11.0/20261007-ai-commerce-v10}/film"
movie_path="${JIEJING_V10_MOVIE:-${film_dir}/../jiejing-douyin-v10.mp4}"
test ! -e "$movie_path" || { echo 'Preserve existing output; specify a new JIEJING_V10_MOVIE.' >&2; exit 1; }
test -x /usr/bin/chromium
cd "$film_dir"
export HYPERFRAMES_BROWSER_PATH=/usr/bin/chromium
/workspace/toolchains/jiejing-hyperframes/node_modules/.bin/hyperframes check --json
/workspace/toolchains/jiejing-hyperframes/node_modules/.bin/hyperframes render --output "$movie_path" --fps 30 --quality delivery --workers 2 --no-best-effort
