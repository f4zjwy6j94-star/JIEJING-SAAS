#!/usr/bin/env bash
set -u

PROMPT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/jiejing-hermes-handoff/tumbler-market-hermes-live1/market-manager/tumbler-market-hermes-live1_03_market.report.md"
OUT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_report.md"
LOG="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_report.log"

mkdir -p "$(dirname "$OUT")"
timeout 420 /home/hermes/.local/bin/hermes --profile market-manager -z "$(cat "$PROMPT")" --yolo > "$OUT.tmp" 2> "$LOG"
rc=$?
if [ "$rc" -eq 0 ] && [ -s "$OUT.tmp" ]; then
  mv "$OUT.tmp" "$OUT"
  echo "OK_HERMES_MARKET_REPORT $OUT"
else
  rm -f "$OUT.tmp"
  echo "FAIL_HERMES_MARKET_REPORT rc=$rc"
  tail -80 "$LOG" || true
  exit 1
fi
