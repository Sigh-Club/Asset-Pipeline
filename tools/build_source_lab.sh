#!/usr/bin/env bash
# build_source_lab.sh — build a unit ENTIRELY from the shipped Dawn of War II data.
#
# Nothing is invented. The part list comes from the unit's shipped wargear blueprint (`render_models`,
# 2,694 entries across the data — a unit is armour + head + accessories, not one model), the body,
# textures, skeleton and clips all come from the shipped files, and the clips are the ones authored
# for that unit's weapon loadout. No procedural clips, no palette repaint, no fitted template.
#
# Usage: tools/build_source_lab.sh <unit> <wargear.txt> <skeleton.hkx> <loadout-dir> <weapon.glb> <height>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LAB="$ROOT/../Imperium-of-Ash/frontend/public/assets/models/units/lab"
TEX="$ROOT/output/source_lab/tex"
TMP="$ROOT/output/source_lab/work"
RETRIB="${DOW2_RETRIB:-/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution}"
ART="${DOW2_ART:-$RETRIB/sga_art}"
if [ ! -d "$ART" ]; then
  echo "DoW2 art not found at $ART — set DOW2_ART (see docs/DOW2_STANCE_REFERENCE.md)" >&2
  exit 2
fi
mkdir -p "$LAB" "$TEX" "$TMP"

unit="$1"; wargear="$2"; skel="$3"; anim="$4"; weapon="$5"; height="$6"
echo "=== $unit"
[ -f "$wargear" ] || { echo "$unit WARGEAR_MISSING $wargear"; exit 1; }
[ -d "$anim" ] || { echo "$unit ANIM_MISSING $anim"; exit 1; }

# 1. the unit's parts, exactly as the shipped wargear data lists them
mapfile -t PARTS < <(python3 tools/dow2/parts.py --wargear "$wargear" --art "$ART" 2>/dev/null)
[ "${#PARTS[@]}" -gt 0 ] || { echo "$unit NO_PARTS"; exit 1; }
echo "$unit parts: ${#PARTS[@]}"
for p in "${PARTS[@]}"; do echo "   $(basename "$(dirname "$p")")/$(basename "$p")"; done

# 2. every shipped texture those parts reference -> PNG
for p in "${PARTS[@]}"; do
  for dds in "$(dirname "$p")"/*_dif*.dds; do
    [ -f "$dds" ] || continue
    python3 tools/dow2/dds_to_png.py "$TEX" "$dds" >/dev/null 2>&1 || true
  done
done
# shared armour textures: DoW2 keeps some families in a `shared_textures` folder rather than beside
# the part (measured: ig_armour_common_a has none of its own and uses shared_textures/ig_armour_dif)
for p in "${PARTS[@]}"; do
  for dds in "$(dirname "$p")"/../shared_textures/*_dif*.dds "$(dirname "$p")"/../../shared_textures/*_dif*.dds; do
    [ -f "$dds" ] || continue
    python3 tools/dow2/dds_to_png.py "$TEX" "$dds" >/dev/null 2>&1 || true
  done
done
echo "$unit textures cached: $(ls "$TEX" | wc -l)"

# 2b. the shipped weapon model, if the caller names one (see the weapon wargear's render_models)
WEAPON_MODEL_ARG=()
WEAPON_MODEL="${7:-}"
if [ -n "$WEAPON_MODEL" ]; then
  [ -f "$WEAPON_MODEL" ] || { echo "$unit WEAPON_MODEL_MISSING $WEAPON_MODEL"; exit 1; }
  for dds in "$(dirname "$WEAPON_MODEL")"/*_dif*.dds; do
    [ -f "$dds" ] || continue
    python3 tools/dow2/dds_to_png.py "$TEX" "$dds" >/dev/null 2>&1 || true
  done
  WEAPON_MODEL_ARG=(--weapon-model "$WEAPON_MODEL")
  # the shipped model replaces our GLB weapon: passing both merges two weapons
  weapon=""
  echo "$unit weapon model: $(basename "$WEAPON_MODEL")"
fi

# 3. the unit's action library: named actions with the shipped timing and events, read from the
#    unit's own `.motiontree` (FOLDEVCT/DATAEVNT -> FOLDACTC/DATAACTN). The clips are decoded from
#    their delta-compressed tracks, not from their reference poses, so one rig plays all of them.
ACTION_ARG=()
UNIT_DIR="$(dirname "$(dirname "$anim")")"
MOTIONTREE="$(ls "$UNIT_DIR"/*.motiontree 2>/dev/null | head -1 || true)"
if [ -n "$MOTIONTREE" ]; then
  mkdir -p "$ROOT/output/source_lab/actions"
  python3 tools/dow2/action_library.py --loadout "$anim" --motiontree "$MOTIONTREE" \
    --unit "$unit" --out "$ROOT/output/source_lab/actions/$unit.json" | sed 's/^/   /'
  ACTION_ARG=(--actions "$ROOT/output/source_lab/actions/$unit.json")
else
  echo "$unit no .motiontree — falling back to the reference-pose library"
fi

# 4. assemble: shipped parts + shipped skeleton + shipped textures + shipped clips
timeout 1800 blender -b -P tools/blender/dow2_build_unit.py -- \
  --model "${PARTS[@]}" --hkx "$skel" --anim-dir "$anim" --out "$TMP/$unit" --id "$unit" \
  --height "$height" --texture-root "$TEX" ${weapon:+--weapon "$weapon"} \
  "${WEAPON_MODEL_ARG[@]}" "${ACTION_ARG[@]}" \
  >"$TMP/$unit.log" 2>&1 || { echo "$unit BUILD_FAIL (see $TMP/$unit.log)"; exit 1; }

grep -E "^(GEOMETRY|MATERIALS|UVS|WEIGHTS|POSES|ACTION|ACTIONS|WEAPON)" "$TMP/$unit.log" | sed 's/^/   /'
cp "$TMP/$unit/$unit.glb" "$LAB/$unit.glb"
[ -f "$TMP/$unit/$unit.actions.json" ] && cp "$TMP/$unit/$unit.actions.json" "$LAB/$unit.actions.json"
echo "$unit BUILT -> lab/$unit.glb"
