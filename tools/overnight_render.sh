#!/usr/bin/env bash
# overnight_render.sh — Regenerate + render all 34 units (Phase 1+2 DoW1-direction:
# corrected geometry proportions, Phase 2 surface textures, camera-relative lighting).
#
# Renders only the idle animation (8 directions) per unit at fast (16 samples) so the
# whole roster fits in an overnight window for review. The per-unit painted diffuse
# atlas (Phase 3) is built but not applied here — it needs a per-primitive UV unwrap
# refactor to avoid front/back colour mismatch (see docs/DEVELOPMENT.md section 16).
#
# Logs to output/overnight_render.log. Continues on per-unit errors.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
LOG="$ROOT/output/overnight_render.log"
mkdir -p output
echo "=== Overnight render start $(date) ===" | tee "$LOG"

configs=()
while IFS= read -r f; do configs+=("$f"); done < <(find configs -name "*.json" | sort)
total=${#configs[@]}
echo "Units: $total" | tee -a "$LOG"

idx=0
ok=0
fail=0
for cfg in "${configs[@]}"; do
  idx=$((idx+1))
  unit=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['unit_name'])" "$cfg")
  faction=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('faction','iron_directorate'))" "$cfg")
  blend=$(python3 -c "import json,sys,os; p=json.load(open(sys.argv[1])).get('output_blend',''); print(os.path.join(sys.argv[2],p) if not os.path.isabs(p) else p)" "$cfg" "$ROOT")
  echo "[$idx/$total] $unit ($faction)" | tee -a "$LOG"

  # 1. Regenerate model (Phase 2 PBR + corrected geometry + box-project atlas UVs)
  if ! blender --background --python "$ROOT/tools/blender/parametric_unit_generator.py" -- --config "$cfg" >>"$LOG" 2>&1; then
    echo "  GENERATE FAILED: $unit" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi

  # 2. Render idle (8 directions, fast)
  if [ ! -f "$blend" ]; then
    echo "  BLEND MISSING: $blend" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  if ! blender --background "$blend" --python "$ROOT/tools/blender/render_8dir_v2.py" -- --fast --faction "$faction" --anim idle >>"$LOG" 2>&1; then
    echo "  RENDER FAILED: $unit" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  ok=$((ok+1))
  echo "  OK ($ok done, $fail failed)" | tee -a "$LOG"
done

echo "=== Overnight render complete $(date) — ok=$ok fail=$fail of $total ===" | tee -a "$LOG"