#!/usr/bin/env bash
# build_rig_lab.sh — rebuild a unit's skin, sockets and weapon into the rig lab.
#
# The certified masters in `models/units/` are left untouched: this writes to
# `models/units/lab/`, which the /units page shows on its own tab. The chain is
#
#   rebind_unit.py     weld + bone-heat weights, sockets on the hands, pose-independent weapon
#   animate_frames.py  the clip set, authored against the rig that now exists
#   rig_fidelity.py    the fold/tear/inversion gate, recorded per unit and per clip
#
# Usage: tools/build_rig_lab.sh <unit-id> [<unit-id> ...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LAB="$ROOT/../Imperium-of-Ash/frontend/public/assets/models/units/lab"
SRC="$ROOT/../Imperium-of-Ash/frontend/public/assets/models/units"
TMP="$ROOT/output/rig_lab"
mkdir -p "$LAB" "$TMP"

find_unit() {
  local id="$1"
  for candidate in "$SRC/$id.glb" "$SRC/dow/$id.glb"; do
    [ -f "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

for id in "$@"; do
  src="$(find_unit "$id")" || { echo "$id MISSING"; continue; }
  echo "=== $id"
  # the faction's authored weapon, socketed into the hand (the baked copy is removed)
  weapon=""
  case "$id" in
    iron_directorate_*|*ig_human*|*super_human*|*scrap_boy*|*biker*|*warboss*|*titan_fist*|*junk_goliath*|*detonation_crew*|*scrapwalker*) weapon="$SRC/../weapons/lasgun.glb" ;;
    cinderborn_*) weapon="$SRC/../weapons/bolter.glb" ;;
    void_corsairs_*|*eldar*) weapon="$SRC/../weapons/shuriken.glb" ;;
    chrono_revenants_*) weapon="$SRC/../weapons/staff.glb" ;;
    radiant_concord_*) weapon="$SRC/../weapons/lasgun.glb" ;;
    parasitic_bloom_*) weapon="" ;;
  esac
  [ -f "$weapon" ] || weapon=""
  if ! timeout 600 blender -b -P tools/blender/rebind_unit.py -- \
        --unit "$src" --out "$TMP" --id "$id" ${weapon:+--weapon "$weapon"} >"$TMP/$id.rebind.log" 2>&1; then
    echo "$id REBIND_FAIL"; continue
  fi
  if ! timeout 600 blender -b -P tools/blender/animate_frames.py -- \
        --glb "$TMP/$id.glb" --out "$TMP" --id "$id" >"$TMP/$id.clips.log" 2>&1; then
    echo "$id CLIP_FAIL"; continue
  fi
  cp "$TMP/${id}_animated.glb" "$LAB/$id.glb"
  echo "$id BUILT"
done
