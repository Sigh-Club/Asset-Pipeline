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
# Scale is declared by the rig config, never by this script: passing --height here is
# how defect D-6 happened (a 2.40 m target written against a rig declaring 1.18 m).
# The up axis is declared there too (source_up_axis); dow2_base.py refuses to guess it.
#
# Usage: tools/build_base_frames.sh [sga_root]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SGA="${1:-/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga_art}"
[ -d "$SGA" ] || { echo "missing DoW2 extraction at $SGA"; exit 1; }

# sga_art is the art tree; sga/ is the per-archive record and is missing race_necron
# and race_tau entirely. Sorted so a duplicated basename resolves the same way every
# run (farseer_armour_common exists under two eldar armour directories).
find_one() { find "$SGA" -name "$1" -print | sort | head -1; }

build() {
  local id="$1" tpl="$2"; shift 2
  local parts=("$@")
  local obj="/tmp/dow2obj/${id}.obj"
  mkdir -p /tmp/dow2obj
  python3 tools/dow2/chunky_mesh.py "${parts[@]}" -o "$obj"
  blender -b -P tools/blender/dow2_base.py -- --obj "$obj" --out output/base --id "$id" \
    --rig "configs/rigs/$tpl" --target-tris 16000 \
    | grep -E '^SPAN|^AXIS|^HEIGHT|^WARN|^SCALE|^BASE|^BBOX|^EXPORTED'
  rm -rf "output/units/$id"
  blender -b -P tools/blender/rig_template.py -- --template "configs/rigs/$tpl" \
    --mesh "output/base/${id}_base.glb" --out "output/units/$id" --id "$id" \
    | grep -E '^RIG|BIND orphan|^EXPORTED'
  blender -b -P tools/blender/animate_frames.py -- --glb "output/units/$id/${id}_rigged.glb" \
    --out "output/units/$id" --id "$id" | grep -E '^CLIP|^EXPORTED'
  cp "output/units/$id/${id}_animated.glb" "output/units/$id/${id}_rigged.glb"
  python3 tools/audit_rig.py "output/units/$id/${id}_rigged.glb" | tail -3
}

build ig_human human.json "$(find_one commissar_armour.model)"
build super_human super_human.json "$(find_one power_armour_ultramarines_commander.model)"
build eldar eldar.json "$(find_one farseer_armour_common.model)"
build carnifex carnifex.json \
  "$(find_one carnifex_armour_common.model)" \
  "$(find_one carnifex_claws.model)" \
  "$(find_one carnifex_tail.model)" \
  "$(find_one carnifex_venomcannon_common.model)"

echo "base frames rebuilt: ig_human super_human eldar carnifex"
