#!/usr/bin/env bash
# build_unit_aaa.sh — the AAA-PC route for a rigged unit, gated end to end.
#
# Produces the band declared in docs/STYLE_BANDS.md (80-120k LOD0, PBR with baked
# normal/AO, >=1024 px/m, rigged) from an existing high-poly source, then refuses
# to report success unless every gate passes.
#
# This is the *output tier* route. The palette/pixel route (build_unit.sh) stays
# as-is for the retro tier; both are legitimate, they are different bands.
#
# Usage:
#   tools/build_unit_aaa.sh <unit-id> <high-poly.glb> <reference-rigged.glb> <faction>
#
# Example:
#   tools/build_unit_aaa.sh line_infantry \
#     output/img23d/line_infantry_mv/front.glb \
#     output/img23d/line_infantry_mv/atlas/unit_textured.glb \
#     iron_directorate
#
# Exit 0 only when: the rebuild meets its texel floor, the GLB meets the aaa_pc
# contract, and the profile still satisfies the target band.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ID="${1:?usage: build_unit_aaa.sh <unit-id> <high-poly.glb> <reference-rigged.glb> <faction>}"
HIGH="${2:?high-poly source GLB required}"
REF="${3:?reference rigged GLB required}"
FACTION="${4:?faction required}"
OUT="output/aaa/${ID}"
LIB="assets/materials/grimdark_scifi/grimdark_scifi.blend"
PROFILE="aaa_pc"

# band targets, from docs/STYLE_BANDS.md §1 and the profile (one source of truth)
TRIS=$(python3 -c "
import sys; sys.path.insert(0,'tools')
from style.profiles import resolve
p = resolve('${PROFILE}')
print(p['geometry']['tris_max'])")
RES=4096          # 2048 measures 537 px/m on a 3.9 m2 body — below the 1024 floor
DENSITY=$(python3 -c "
import sys; sys.path.insert(0,'tools')
from style.profiles import resolve
p = resolve('${PROFILE}')
print(p['texture'].get('texel_density_px_m', 1024))")

echo "=== 1/6 rebuild at the ${PROFILE} band (${TRIS} tris, ${RES}px, ${DENSITY} px/m floor)"
tools/blender_run.sh --job bake -- -b -P tools/blender/aaa_rebuild.py -- \
  --high "$HIGH" --slot-source "$REF" --out "$OUT" --id "$ID" \
  --tris "$TRIS" --res "$RES" --min-texel-density "$DENSITY" \
  --library "$LIB" --faction "$FACTION"

echo "=== 2/6 assemble: skeleton + sockets + parts + per-part LODs"
tools/blender_run.sh --job script -- -b -P tools/blender/aaa_assemble.py -- \
  --glb "$OUT/${ID}_aaa.glb" --out "$OUT" --id "$ID" --high "$HIGH" \
  --library "$LIB" --faction "$FACTION"

echo "=== 3/6 socket-parent rigid gear (helmet, boots, plates)"
tools/blender_run.sh --job script -- -b -P tools/blender/aaa_socket_gear.py -- \
  --from-parts "$OUT/parts" --out "$OUT" --id "$ID"

echo "=== 4/6 asset contract (${PROFILE})"
python3 tools/glb_contract.py "$OUT/${ID}_aaa.glb" --kind "$PROFILE"

echo "=== 5/6 measured band report"
python3 - "$OUT/aaa_report.json" "$DENSITY" "$TRIS" <<'PY'
import json, sys
rep = json.load(open(sys.argv[1]))
floor = float(sys.argv[2]); tris = int(sys.argv[3])
lod0 = rep['geometry']['lod0_tris']
density = rep['uv']['texel_density_px_m']
problems = []
if lod0 < 80000:
    problems.append(f'LOD0 {lod0} below the 80k band floor')
if lod0 > tris:
    problems.append(f'LOD0 {lod0} above the declared {tris}')
if density < floor:
    problems.append(f'texel density {density} below {floor}')
if not rep.get('rig', {}).get('weights_transferred'):
    problems.append('skin weights were not transferred')
if not rep.get('materials', {}).get('slots_transferred'):
    problems.append('material slots were not transferred')
print(f"  LOD0={lod0} tris, {density} px/m, slots={rep['materials']['slots_transferred']}, "
      f"rig={rep['rig']['weights_transferred']}")
if problems:
    print('  FAIL: ' + '; '.join(problems))
    sys.exit(1)
print('  band: PASS')
PY

echo "=== 6/6 profile vs published band"
python3 tools/style/bands.py --target "$PROFILE" | tail -1

echo "OK  ${OUT}/${ID}_aaa.glb"
