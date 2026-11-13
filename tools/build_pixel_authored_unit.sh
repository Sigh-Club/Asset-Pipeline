#!/usr/bin/env bash
# build_pixel_authored_unit.sh — authored modular unit -> certified pixel_3d master.
#
# Skips the img23d/decimate stages: the mesh is authored at the pixel-tier budget
# with contract material slots and per-part bone groups, so it is rigged directly
# and then goes through the same texel/atlas/palette/master/gate chain as the
# generative route.
#
# Usage:
#   tools/build_pixel_authored_unit.sh unit8 line_infantry iron_directorate
#
# Palette lock uses --dither none: the material library is already band-limited,
# so bayer4 on a flat panel only adds speckle (A/B checked on the line infantry
# master; palette gate stays 0 off-palette either way).
#
# Requires output/units/<faction>/<unit>/<unit>_rigged.glb (rig_unit_proof.py
# --bind authored). Set BUILD_RIG=1 to rig from the authored mesh first.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ASSET="${1:?usage: build_pixel_authored_unit.sh <out-name> <unit-id> <faction>}"
ID="${2:?unit id required}"
FACTION="${3:?faction required}"
LIB="assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend"
PROFILE="${PROFILE:-pixel_3d}"
MATERIAL_MAP="${MATERIAL_MAP:-}"
SRC_DIR="output/units/${FACTION}/${ID}"
SRC="${SRC_DIR}/${ID}_rigged.glb"
OUT="output/gen/${ASSET}"

if [[ "${BUILD_RIG:-0}" == "1" ]]; then
  echo "=== 0/8 authored mesh + authored-weight rig"
  blender -b -P tools/blender/parametric_unit.py -- \
    --config "configs/units/${FACTION}.json" --unit "$ID" --out "$SRC_DIR" --id "$ID"
  HOLD="$(python3 -c "import json;print(json.load(open('${SRC_DIR}/authored_report.json'))['hold'])" 2>/dev/null || echo relaxed)"
  tools/blender_run.sh --job render -- -b -P tools/blender/rig_unit_proof.py -- \
    --glb "${SRC_DIR}/${ID}_authored.glb" --out "$SRC_DIR/rig" --bind authored \
    --hold "$HOLD" --clips all
  cp "${SRC_DIR}/rig/unit_rigged.glb" "$SRC"
fi
[[ -f "$SRC" ]] || { echo "missing $SRC (run with BUILD_RIG=1)"; exit 1; }

echo "=== 1/8 texel grid"
tools/blender_run.sh --job uv -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage texel --glb "$SRC" --out "$OUT" --id "$ID" --profile "$PROFILE"

echo "=== 2/8 bake atlas"
tools/blender_run.sh --job bake -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage albedo --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" \
  --profile "$PROFILE" --library "$LIB" --faction "$FACTION" \
  ${MATERIAL_MAP:+--material-map "$MATERIAL_MAP"}

echo "=== 2b/8 denoise baked atlas"
python3 tools/style/denoise_atlas.py "$OUT/atlas/atlas_albedo.png" --size 5

echo "=== 3/8 palette-lock atlas"
python3 tools/style/palette_lock.py "$OUT/atlas/atlas_albedo.png" --profile "$PROFILE" \
  --dither none --out-dir "$OUT/atlas" --suffix _pixel
if [[ -f "$OUT/atlas/atlas_emission.png" ]]; then
  python3 tools/style/palette_lock.py "$OUT/atlas/atlas_emission.png" --profile "$PROFILE" \
    --dither none --out-dir "$OUT/atlas" --suffix _pixel
fi

echo "=== 4/8 final GLB"
tools/blender_run.sh --job script -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage final --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" --profile "$PROFILE"

echo "=== 5/8 8-direction master (aim pose, feet anchored)"
tools/blender_run.sh --job render -- -b -P tools/blender/render_pixel_master.py -- \
  --glb "$OUT/${ID}_pixel.glb" --out "$OUT" --id "$ID" --size 256 --directions 8 \
  --masks --anchor bottom --action aim --keep-smooth --exclude-mesh Icosphere

echo "=== 6/8 palette-lock frames"
python3 tools/style/palette_lock.py --dir "$OUT/render" --profile "$PROFILE" \
  --dither none --out-dir "$OUT/render_pixel" --suffix ""

echo "=== 7/8 gates"
python3 tools/glb_contract.py "$OUT/${ID}_pixel.glb" --kind unit
python3 tools/style/check_texel_grid.py "$OUT/${ID}_pixel.glb" --profile "$PROFILE"
python3 tools/style/check_pixel_asset.py --dir "$OUT/render_pixel" \
  --profile "$PROFILE" --kind unit
python3 tools/style/check_master.py --dir "$OUT" --profile "$PROFILE" \
  --expect-directions 8 --require-distinct

echo "=== 8/8 done"
echo "OK  ${OUT}"
