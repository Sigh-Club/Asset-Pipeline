#!/usr/bin/env bash
# build_dow_roster.sh — import EVERY troop body of a DoW2 race as a playable unit.
#
# The owner's direction: import all Imperial Guard, Chaos, Eldar, Ork and Tyranid units
# wholesale — bodies, weapons and animations — so the reference corpus exists and we can
# reverse-engineer our own style from it later. No kit-bashing, no selection: every body in
# the race's armour slot becomes a unit.
#
# Each body goes through the certified chain: decode -> base mesh (declared up axis) -> certified
# frame -> authored clips -> weapon baked into the asset parented to hand_R.
#
# Usage: tools/build_dow_roster.sh <race> <label> [limit]
#   race:  race_ig | race_chaos | race_eldar | race_ork | race_tyranid
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RACE="${1:?usage: build_dow_roster.sh <race> <label> [limit]}"
LABEL="${2:?label required}"
LIMIT="${3:-0}"
SGA="${SGA_ROOT:-/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga_art}"
OUT="$ROOT/../Imperium-of-Ash/frontend/public/assets/models/units/dow"
TMP="/tmp/dowroster/$LABEL"
mkdir -p "$OUT" "$TMP"

case "$RACE" in
  race_ig)       WEAPON=lasgun;   FRAME=human.json ;;
  race_chaos)    WEAPON=bolter;   FRAME=super_human.json ;;
  race_eldar)    WEAPON=shuriken; FRAME=eldar.json ;;
  race_ork)      WEAPON=shoota;   FRAME=ork.json ;;
  race_tyranid)  WEAPON="";       FRAME=quadruped.json ;;
  race_necron)   WEAPON="";       FRAME=human.json ;;
  race_tau)      WEAPON="";       FRAME=machine.json ;;
  *) echo "unknown race $RACE"; exit 2 ;;
esac

# Body list: everything in the race's armour slot above the silhouette threshold, de-duplicated
# across the quality variants (_common/_epic/_rare/_glow/_alpha/_carnage are the same body).
python3 - "$RACE" "$LIMIT" > "$TMP/bodies.txt" <<'PY'
import sys
sys.path.insert(0, 'tools/dow2')
import chunky_mesh as C
from pathlib import Path
race, limit = sys.argv[1], int(sys.argv[2])
ROOT = Path('/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution/sga_art')
VARIANT = ('_common', '_epic', '_rare', '_glow', '_alpha', '_carnage', '_carnage_common')
seen, rows = set(), []
# slot dirs are not uniform: race_tau ships `armor`, the rest `armour`
cands = list(ROOT.rglob(f'{race}/**/troops_wargear/armour/*/*.model'))
cands += list(ROOT.rglob(f'{race}/**/troops_wargear/armor/*/*.model'))
cands += list(ROOT.rglob(f'{race}/**/troops_wargear/weapons/*/*.model'))
for m in sorted(cands):
    base = m.stem
    canon = base
    for v in VARIANT:
        if canon.endswith(v):
            canon = canon[: -len(v)]
    if canon in seen:
        continue
    try:
        ms = C.extract_model(m)
    except Exception:
        continue
    verts = sum(len(mo['verts']) for mo in ms)
    if verts < 900:
        continue
    seen.add(canon)
    rows.append((canon, str(m), verts))
rows.sort(key=lambda r: -r[2])
if limit:
    rows = rows[:limit]
for canon, path, verts in rows:
    print(f'{canon}\t{path}\t{verts}')
PY

TOTAL=$(wc -l < "$TMP/bodies.txt")
echo "=== $LABEL: $TOTAL bodies (frame $FRAME, weapon ${WEAPON:-none})"
: > "$TMP/report.tsv"
n=0
while IFS=$'\t' read -r name path verts; do
  n=$((n + 1))
  id="dow_${LABEL}_${name}"
  obj="$TMP/$id.obj"
  python3 tools/dow2/chunky_mesh.py "$path" -o "$obj" >/dev/null 2>&1 || { echo -e "$id\tDECODE_FAIL" >> "$TMP/report.tsv"; continue; }
  # The unit's own DoW2 skeleton (its Bip01 rig, hierarchy and reference pose). This is the
  # authoritative fit: the mesh was authored against it, so no template fit is involved.
  partstem="$(basename "$(dirname "$path")")"
  # Use the shipped skeleton only where one actually fits this body (measured against the mesh,
  # within 12% of its height). Races whose troop directories carry no skeleton file -- the eldar
  # troops have only clips, and a clip's reference pose is whatever the animator posed -- fall
  # back to the template fit rather than being bent onto a crouch pose.
  skel_hkx="$(python3 tools/dow2/skeleton.py --find --strict --art "$SGA/000_data/DATA/art" \
      --race "$RACE" --part "$partstem" --obj "$obj" \
      --height "$(python3 -c "import json;print(json.load(open('configs/rigs/$FRAME'))['height_m'])")" \
      --out - 2>/dev/null | tail -1 || true)"
  if [ -n "$skel_hkx" ] && [ -f "$skel_hkx" ]; then
    python3 tools/dow2/skeleton.py --hkx "$skel_hkx" --obj "$obj" \
      --height "$(python3 -c "import json;print(json.load(open('configs/rigs/$FRAME'))['height_m'])")" \
      --up-axis "$(python3 -c "import json;print(json.load(open('configs/rigs/$FRAME')).get('source_up_axis','y'))")" \
      --out "$TMP/$id.skeleton.json" >/dev/null 2>&1 \
      || { echo -e "$id\tSKELETON_FAIL" >> "$TMP/report.tsv"; continue; }
  fi
  timeout 300 blender -b -P tools/blender/dow2_base.py -- --obj "$obj" --out "$TMP" --id "$id" \
    --rig "configs/rigs/$FRAME" --target-tris 16000 >/dev/null 2>&1 || { echo -e "$id\tBASE_FAIL" >> "$TMP/report.tsv"; continue; }
  mkdir -p "$TMP/$id"
  if [ -f "$TMP/$id.skeleton.json" ]; then
    timeout 300 blender -b -P tools/blender/rig_template.py -- --template "configs/rigs/$FRAME" \
      --skeleton "$TMP/$id.skeleton.json" \
      --mesh "$TMP/${id}_base.glb" --out "$TMP/$id" --id "$id" >/dev/null 2>&1 || { echo -e "$id\tRIG_FAIL" >> "$TMP/report.tsv"; continue; }
  else
    timeout 300 blender -b -P tools/blender/rig_template.py -- --template "configs/rigs/$FRAME" \
      --mesh "$TMP/${id}_base.glb" --out "$TMP/$id" --id "$id" >/dev/null 2>&1 || { echo -e "$id\tRIG_FAIL" >> "$TMP/report.tsv"; continue; }
  fi
  timeout 300 blender -b -P tools/blender/animate_frames.py -- --glb "$TMP/$id/${id}_rigged.glb" \
    --out "$TMP/$id" --id "$id" >/dev/null 2>&1 || { echo -e "$id\tCLIP_FAIL" >> "$TMP/report.tsv"; continue; }
  cp "$TMP/$id/${id}_animated.glb" "$OUT/$id.glb"
  if [ -n "$WEAPON" ]; then
    timeout 300 blender -b -P tools/blender/attach_weapon_baked.py -- --unit "$OUT/$id.glb" \
      --weapon "$ROOT/../Imperium-of-Ash/frontend/public/assets/models/weapons/$WEAPON.glb" \
      --out "$OUT" --id "$id" --clip idle --frame 1 >/dev/null 2>&1 || { echo -e "$id\tBAKE_FAIL" >> "$TMP/report.tsv"; continue; }
  fi
  # grep returns non-zero when it finds nothing, and `set -e` would kill the whole run
  if [ -f "$TMP/$id.skeleton.json" ]; then
    verdict=$(python3 tools/audit_rig.py "$OUT/$id.glb" --skeleton "$TMP/$id.skeleton.json" 2>&1 | grep -E "^(PASS|FAIL)" | head -1 || true)
  else
    verdict=$(python3 tools/audit_rig.py "$OUT/$id.glb" 2>&1 | grep -E "^(PASS|FAIL)" | head -1 || true)
  fi
  [ -n "$verdict" ] || verdict="NO_VERDICT"
  echo -e "$id\t$verdict" >> "$TMP/report.tsv"
  echo "[$n/$TOTAL] $id $verdict"
done < "$TMP/bodies.txt"

echo "=== $LABEL summary"
awk -F'\t' '{print $2}' "$TMP/report.tsv" | sort | uniq -c
