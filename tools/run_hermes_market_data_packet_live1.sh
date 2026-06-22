#!/usr/bin/env bash
set -u

PROMPT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/market_data_packet_short_prompt.md"
OUT="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_data_packet.md"
LOG="/mnt/c/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo/output/runtime-live-hermes-test/tumbler-market-live1/hermes_market_data_packet.log"

timeout 240 /home/hermes/.local/bin/hermes --profile market-manager -z "$(cat "$PROMPT")" --yolo > "$OUT.tmp" 2> "$LOG"
rc=$?
if [ "$rc" -eq 0 ] && [ -s "$OUT.tmp" ]; then
  mv "$OUT.tmp" "$OUT"
  echo "OK_DATA_PACKET $OUT"
else
  rm -f "$OUT.tmp"
  echo "FAIL_DATA_PACKET rc=$rc"
  tail -80 "$LOG" || true
  exit 1
fi
