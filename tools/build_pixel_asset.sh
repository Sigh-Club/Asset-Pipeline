#!/usr/bin/env bash
# build_pixel_asset.sh — the full `pixel_3d` master route for one hard-surface
# asset request: build -> texel grid -> bake -> palette lock -> final GLB ->
# 8-direction master -> palette-locked frames -> gates.
#
# Every stage is idempotent and each one writes its own report, so a failure is
# traceable to the stage that produced it. Hard-surface assets never go through
# img23d (image-to-3D fuses parts and loses real dimensions).
#
# Usage:
#   tools/build_pixel_asset.sh barrel8  iron_directorate_barrel_a     prop
#   tools/build_pixel_asset.sh weapon8  iron_directorate_lasrifle     weapon
#   tools/build_pixel_asset.sh tile8    tile_floor_industrial_a       tile
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ASSET="${1:?usage: build_pixel_asset.sh <out-name> <request-id> <kind>}"
ID="${2:?request id required}"
KIND="${3:?kind required}"
REQ="configs/assets/examples.json"
LIB="assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend"
OUT="output/gen/${ASSET}"
BUILD="output/gen/build/${ID}"
DIRS=8
SIZE=256

# the pixel tier bakes from the band-limited material variants (1 texel budget),
# never from the 1K AAA library: point-sampling a 50:1 downscale reads as noise
echo "=== 1/8 build $ID"
tools/blender_run.sh --job script -- -b -P tools/blender/parametric_prop.py -- \
  --request "$REQ" --id "$ID" --out "$BUILD" --library "$LIB" >/dev/null

echo "=== 2/8 texel grid"
tools/blender_run.sh --job uv -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage texel --glb "$BUILD/$ID.glb" --out "$OUT" --id "$ID" --profile pixel_3d

echo "=== 3/8 bake atlas"
tools/blender_run.sh --job bake -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage albedo --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" \
  --profile pixel_3d --library "$LIB" --faction iron_directorate

echo "=== 4/8 palette-lock atlas"
python3 tools/style/palette_lock.py "$OUT/atlas/atlas_albedo.png" --profile pixel_3d \
  --dither bayer4 --out-dir "$OUT/atlas" --suffix _pixel

if [[ -f "$OUT/atlas/atlas_emission.png" ]]; then
  python3 tools/style/palette_lock.py "$OUT/atlas/atlas_emission.png" --profile pixel_3d \
    --dither none --out-dir "$OUT/atlas" --suffix _pixel
fi

echo "=== 5/8 final GLB"
tools/blender_run.sh --job script -- -b -P tools/blender/bake_pixel_atlas.py -- \
  --stage final --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" --profile pixel_3d

echo "=== 6/8 8-direction master"
ANCHOR="centre"; [[ "$KIND" == "unit" ]] && ANCHOR="bottom"
tools/blender_run.sh --job render -- -b -P tools/blender/render_pixel_master.py -- \
  --glb "$OUT/${ID}_pixel.glb" --out "$OUT" --id "$ID" --size "$SIZE" \
  --directions "$DIRS" --masks --anchor "$ANCHOR"

echo "=== 7/8 palette-lock frames"
python3 tools/style/palette_lock.py --dir "$OUT/render" --profile pixel_3d \
  --dither bayer4 --out-dir "$OUT/render_pixel" --suffix ""

echo "=== 8/8 gates"
CONTRACT_KIND="$KIND"; [[ "$KIND" == "weapon" ]] && CONTRACT_KIND="prop"
python3 tools/glb_contract.py "$OUT/${ID}_pixel.glb" --kind "$CONTRACT_KIND"
python3 tools/style/check_texel_grid.py "$OUT/${ID}_pixel.glb" --profile pixel_3d
python3 tools/style/check_pixel_asset.py --dir "$OUT/render_pixel" \
  --profile pixel_3d --kind "$KIND"
python3 tools/style/check_master.py --dir "$OUT" --profile pixel_3d \
  --expect-directions "$DIRS" --require-distinct
echo "OK  ${OUT}"
