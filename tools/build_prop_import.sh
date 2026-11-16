#!/usr/bin/env bash
# build_prop_import.sh — the `palette_3d` master route for a prop whose geometry is
# a shipped-game mesh (DoW2 `.model` decoded to OBJ) instead of a parametric recipe.
#
# Same stages as build_asset.sh (texel grid -> bake -> palette lock -> final GLB
# -> 8-direction master -> gates); only the build stage differs, so an imported prop is
# held to exactly the contract the parametric props are.
#
# Usage:
#   tools/build_prop_import.sh cover8_sandbag cover_sandbag_wall_b /tmp/props/sandbag_wall_01.obj 0.82
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ASSET="${1:?usage: build_prop_import.sh <out-name> <request-id> <obj> <height-m>}"
ID="${2:?request id required}"
OBJ="${3:?source obj required}"
HEIGHT="${4:?target height in metres required}"
PROFILE="${5:-palette_3d}"
TRIS="${6:-}"
if [ -z "$TRIS" ]; then
  if [ "$PROFILE" = "palette_3d" ] || [ "$PROFILE" = "palette_3d_hi" ] || [ "$PROFILE" = "palette_3d_prop_coarse" ]; then TRIS=600; else TRIS=2500; fi
fi
MATERIAL_MODEL="$(python3 -c "import sys; sys.path.insert(0,'tools/style'); import profiles; print(profiles.resolve('$PROFILE')['texture'].get('material_model','palette'))" 2>/dev/null || echo palette)"
lock_palette() {
  [ "$MATERIAL_MODEL" = "palette" ] || { echo "=== palette lock skipped ($MATERIAL_MODEL profile)"; return 0; }
  lock_palette "$@"
}
REQ="configs/assets/examples.json"
LIB="assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend"
OUT="output/gen/${ASSET}"
BUILD="output/gen/build/${ID}"
DIRS=8
SIZE=256

echo "=== 1/8 build (imported) $ID"
tools/blender_run.sh --job script -- -b -P tools/blender/parametric_prop.py -- \
  --request "$REQ" --id "$ID" --out "$BUILD" --library "$LIB" \
  --obj "$OBJ" --height "$HEIGHT" --target-tris "$TRIS" --max-footprint 2.2 \
  --profile-override "$PROFILE" >/dev/null

echo "=== 2/8 texel grid"
tools/blender_run.sh --job uv -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage texel --glb "$BUILD/$ID.glb" --out "$OUT" --id "$ID" --profile "$PROFILE"

echo "=== 3/8 bake atlas"
tools/blender_run.sh --job bake -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage albedo --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" \
  --profile "$PROFILE" --library "$LIB" --faction iron_directorate

echo "=== 4/8 palette-lock atlas"
# The final stage consumes the locked atlas name. For a non-palette profile the lock is a
# pass-through: copy the baked atlas to the expected filename.
if [ "$MATERIAL_MODEL" != "palette" ]; then
  cp "$OUT/atlas/atlas_albedo.png" "$OUT/atlas/atlas_albedo_pixel.png"
  [ -f "$OUT/atlas/atlas_emission.png" ] && cp "$OUT/atlas/atlas_emission.png" "$OUT/atlas/atlas_emission_pixel.png"
fi
lock_palette "$OUT/atlas/atlas_albedo.png" --profile "$PROFILE" \
  --dither bayer4 --out-dir "$OUT/atlas" --suffix _pixel

echo "=== 5/8 final GLB"
tools/blender_run.sh --job script -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage final --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" --profile "$PROFILE"

echo "=== 6/8 8-direction master"
tools/blender_run.sh --job render -- -b -P tools/blender/render_master.py -- \
  --glb "$OUT/${ID}_pixel.glb" --out "$OUT" --id "$ID" --size "$SIZE" \
  --directions "$DIRS" --masks --anchor centre

echo "=== 7/8 palette-lock frames"
lock_palette --dir "$OUT/render" --profile "$PROFILE" \
  --dither bayer4 --out-dir "$OUT/render_pixel" --suffix ""

echo "=== 8/8 gates"
python3 tools/glb_contract.py "$OUT/${ID}_pixel.glb" --kind prop
if [ "$MATERIAL_MODEL" = "palette" ]; then
  python3 tools/style/check_texel_grid.py "$OUT/${ID}_pixel.glb" --profile "$PROFILE"
fi
if [ "$MATERIAL_MODEL" = "palette" ]; then
  python3 tools/style/check_palette_asset.py --dir "$OUT/render_pixel" --profile "$PROFILE" --kind cover
fi
python3 tools/style/check_master.py --dir "$OUT" --profile "$PROFILE" \
  --expect-directions "$DIRS" --require-distinct
echo "OK  ${OUT}"
