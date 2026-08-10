#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/build/custom2}"
mkdir -p "$OUT"

python3 "$ROOT/src/raw_translator.py" \
  --input "$ROOT/examples/custom2/input/custom2_two_agent.zip" \
  --initial "$ROOT/examples/custom2/input/initial.json" \
  --output "$OUT/custom2_raw.ispl"

python3 "$ROOT/src/jason_guided.py" \
  --raw "$OUT/custom2_raw.ispl" \
  --fire-jason "$ROOT/agents/fire_brigade.asl" \
  --ambulance-jason "$ROOT/agents/ambulance_team.asl" \
  --bridge "$ROOT/config/jason_translation.json" \
  --initial "$ROOT/examples/custom2/input/initial.json" \
  --output "$OUT/custom2_jason_guided.ispl"

cmp "$OUT/custom2_raw.ispl" \
    "$ROOT/examples/custom2/generated/custom2_raw.ispl"
cmp "$OUT/custom2_jason_guided.ispl" \
    "$ROOT/examples/custom2/generated/custom2_jason_guided.ispl"

echo "Custom2 regeneration matches the checked-in models."

if command -v mcmas >/dev/null 2>&1; then
  echo
  echo "Running MCMAS on the Jason-guided model:"
  mcmas "$OUT/custom2_jason_guided.ispl"
else
  echo
  echo "MCMAS was not found in PATH. Model generation and comparison are complete."
fi
