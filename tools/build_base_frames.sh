#!/usr/bin/env bash
# build_base_frames.sh — rebuild the certified base frames from the extracted DoW2 art.
#
# Frames shipped (each with attachment sockets for gear and a bind pose ready for
# animation):
#   ig_human      human            configs/rigs/human.json         DoW2 ig_base
#   super_human   super-human      configs/rigs/super_human.json   DoW2 space_marine_base
#                 (Space Marine and Chaos Marine share this frame; Chaos differs by
#                  material/palette and its spike/horn gear)
#   eldar         slim athletic    configs/rigs/eldar.json         DoW2 guardian_common
#   carnifex      monster          configs/rigs/quadruped.json     DoW2 carnifex (4 parts merged)
#
# Each frame is audited by tools/audit_rig.py; the script fails if any frame does
# not certify.
#
# Usage: tools/build_base_frames.sh [sga_root]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SGA="${1:-/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga}"
[ -d "$SGA" ] || { echo "missing DoW2 extraction at $SGA"; exit 1; }

find_one() { find "$SGA" -name "$1" | head -1; }

build() {
  local id="$1" tpl="$2" height="$3"; shift 3
  local parts=("$@")
  local obj="/tmp/dow2obj/${id}.obj"
  mkdir -p /tmp/dow2obj
  python3 tools/dow2/chunky_mesh.py "${parts[@]}" -o "$obj"
  blender -b -P tools/blender/dow2_base.py -- --obj "$obj" --out output/base --id "$id" \
    --height "$height" --target-tris 16000 | grep -E '^BASE|^EXPORTED'
  rm -rf "output/units/$id"
  blender -b -P tools/blender/rig_template.py -- --template "configs/rigs/$tpl" \
    --mesh "output/base/${id}_base.glb" --out "output/units/$id" --id "$id" \
    | grep -E '^RIG|BIND orphan|^EXPORTED'
  python3 tools/audit_rig.py "output/units/$id/${id}_rigged.glb" | tail -3
}

build ig_human human.json 1.85 "$(find_one ig_base.model)"
build super_human super_human.json 2.15 "$(find_one space_marine_base.model)"
build eldar eldar.json 1.95 "$(find_one guardian_common.model)"
build carnifex quadruped.json 2.40 \
  "$(find_one carnifex_armour_common.model)" \
  "$(find_one carnifex_claws.model)" \
  "$(find_one carnifex_tail.model)" \
  "$(find_one carnifex_venomcannon_common.model)"

echo "base frames rebuilt: ig_human super_human eldar carnifex"
