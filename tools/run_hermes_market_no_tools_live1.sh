#!/usr/bin/env bash
set -u

PROMPT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/market_report_no_tools_prompt.md"
OUT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_report_no_tools.md"
LOG="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_report_no_tools.log"

timeout 150 /home/hermes/.local/bin/hermes --profile market-manager -z "$(cat "$PROMPT")" --yolo > "$OUT.tmp" 2> "$LOG"
rc=$?
if [ "$rc" -eq 0 ] && [ -s "$OUT.tmp" ]; then
  mv "$OUT.tmp" "$OUT"
  echo "OK_NO_TOOLS_REPORT $OUT"
else
  rm -f "$OUT.tmp"
  echo "FAIL_NO_TOOLS_REPORT rc=$rc"
  tail -80 "$LOG" || true
  exit 1
fi
