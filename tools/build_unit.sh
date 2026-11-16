#!/usr/bin/env bash
# build_unit.sh — the `palette_3d` master route for a rigged unit.
#
# Source is the certified textured unit GLB (20k tris, 22 joints, 9 clips) from
# the img23d -> retopo -> rig -> bake chain. The pixel tier re-authors the mesh
# budget, the texel grid and the material model; it does not touch the rig or the
# clip set, which stay under the engine contract.
#
# Usage:
#   tools/build_unit.sh unit8 line_infantry \
#     output/img23d/line_infantry_mv/atlas/unit_textured.glb [faction]
#
# The 4th argument is the faction material prefix used by the atlas bake
# (`<faction>__<slot>` in the pixel material library). Default iron_directorate;
# ship no non-Iron-Directorate unit without passing it, or the bake silently
# falls back to the Directorate kit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ASSET="${1:?usage: build_unit.sh <out-name> <unit-id> <textured-unit.glb>}"
ID="${2:?unit id required}"
SRC="${3:?source GLB required}"
FACTION="${4:-iron_directorate}"
LIB="assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend"
OUT="output/gen/${ASSET}"

echo "=== 1/8 decimate to the profile tri budget"
tools/blender_run.sh --job decimate -- -b -P tools/blender/decimate_unit.py -- \
  --glb "$SRC" --out "$OUT" --id "$ID" --tris 4000 --profile palette_3d

echo "=== 2/8 texel grid"
tools/blender_run.sh --job uv -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage texel --glb "$OUT/${ID}_lod.glb" --out "$OUT" --id "$ID" --profile palette_3d

echo "=== 3/8 bake atlas"
tools/blender_run.sh --job bake -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage albedo --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" \
  --profile palette_3d --library "$LIB" --faction "$FACTION"

echo "=== 4/8 palette-lock atlas"
python3 tools/style/palette_lock.py "$OUT/atlas/atlas_albedo.png" --profile palette_3d \
  --dither bayer4 --out-dir "$OUT/atlas" --suffix _pixel
if [[ -f "$OUT/atlas/atlas_emission.png" ]]; then
  python3 tools/style/palette_lock.py "$OUT/atlas/atlas_emission.png" --profile palette_3d \
    --dither none --out-dir "$OUT/atlas" --suffix _pixel
fi

echo "=== 5/8 final GLB"
tools/blender_run.sh --job script -- -b -P tools/blender/bake_palette_atlas.py -- \
  --stage final --glb "$OUT/${ID}_texel.glb" --out "$OUT" --id "$ID" --profile palette_3d

echo "=== 6/8 8-direction master (aim pose, feet anchored)"
tools/blender_run.sh --job render -- -b -P tools/blender/render_master.py -- \
  --glb "$OUT/${ID}_pixel.glb" --out "$OUT" --id "$ID" --size 256 --directions 8 \
  --masks --anchor bottom --action aim --exclude-mesh Icosphere

echo "=== 7/8 palette-lock frames"
python3 tools/style/palette_lock.py --dir "$OUT/render" --profile palette_3d \
  --dither bayer4 --out-dir "$OUT/render_pixel" --suffix ""

echo "=== 8/8 gates"
python3 tools/glb_contract.py "$OUT/${ID}_pixel.glb" --kind unit
python3 tools/style/check_texel_grid.py "$OUT/${ID}_pixel.glb" --profile palette_3d
python3 tools/style/check_palette_asset.py --dir "$OUT/render_pixel" \
  --profile palette_3d --kind unit
python3 tools/style/check_master.py --dir "$OUT" --profile palette_3d \
  --expect-directions 8 --require-distinct
echo "OK  ${OUT}"
