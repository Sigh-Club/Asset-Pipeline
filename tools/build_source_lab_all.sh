#!/usr/bin/env bash
# build_source_lab_all.sh — rebuild the whole rig lab from the shipped DoW2 data.
#
# One unit per faction, each assembled from the wargear the game itself uses (armour + head +
# accessories, resolved from `render_models`), rigged on a shipped skeleton, animated with the clips
# from the weapon loadout that unit carries, and textured with the shipped `_dif` maps. No
# procedural clips, no palette repaint, no fitted template.
#
# The table is the contract. Every column is a shipped file, not a choice we made:
#   unit        | wargear (defines the part list)                    | skeleton            | loadout dir        | weapon   | height
#
# The SKELETON column must be a file from the SAME loadout the clips come from, not the unit's own
# `.hkx`. Measured: building on `guardsman.hkx` and then applying `fb_idle_stand_01` gave every bone
# a ~180 deg delta — a constant frame difference between two different skeletons, not a pose — and
# the mesh tore 23 %. Building the rig from the clip file makes the rig's reference pose identical to
# the clip's, and the same idle then measures 0.0 % tear / 0.0 % inverted. This is the single change
# that makes DoW2's own animation usable on DoW2's own body.
#
# Notes on two entries that need the fallback path:
#  * the chaos lord ships no `.hkx` of its own, so the skeleton is read from a clip in its loadout
#    (the tool falls back to the first decodable file in the animation set);
#  * the necron overlord's clips are not Havok packfiles at all (magic 0x0003da78) and its `.model`
#    carries no FOLDSKEL, so it borrows the Imperial Guard skeleton — recorded, not hidden.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
R="${DOW2_RETRIB:-/run/media/talzanar/games/Projects/Decompilor/work/dow2-retribution}"
if [ ! -d "$R/sga_art" ]; then
  echo "DoW2 art not found at $R/sga_art — set DOW2_RETRIB (see docs/DOW2_STANCE_REFERENCE.md)" >&2
  exit 2
fi
W="$ROOT/../Imperium-of-Ash/frontend/public/assets/models/weapons"
IG="$R/sga_art/000_data/DATA/art/race_ig/troops/gaurdsman"

run() { tools/build_source_lab.sh "$@" 2>&1 | grep -E "parts:|textures cached|MATERIAL mat|GEOMETRY|POSES|BUILT|FAIL|MISSING|NO_PARTS" || true; }

run dow_ig_guardsman \
  "$R/attrib-decoded/wargear/wargear/core/race_imperial_guard/armor/flak_common.txt" \
  "$IG/animations/range_burst/fb_idle_stand_01.hkx" "$IG/animations/range_burst" "$W/lasgun.glb" 1.85

run dow_chaos_sorcerer \
  "$R/attrib-decoded/wargear/wargear/core/race_chaos/armor/survive/sorcerer_defying_death.txt" \
  "$R/sga_art/000_data/DATA/art/race_chaos/troops/chaos_lord/animations/melee_blade_range_pistol/fb_idle_stand_01.hkx" \
  "$R/sga_art/000_data/DATA/art/race_chaos/troops/chaos_lord/animations/melee_blade_range_pistol" \
  "$W/bolter.glb" 2.15

# the banshee ships no `range_burst`; its ranged loadout is `melee_blade_range_pistol`
run dow_eldar_farseer \
  "$R/attrib-decoded/wargear/wargear/core/race_eldar/armor/farseer_armor_common.txt" \
  "$R/sga_art/000_data/DATA/art/race_eldar/troops/banshee/animations/melee_blade_range_pistol/fb_idle_stand_01.hkx" \
  "$R/sga_art/000_data/DATA/art/race_eldar/troops/banshee/animations/melee_blade_range_pistol" \
  "$W/shuriken.glb" 1.95

run dow_ork_warboss \
  "$R/attrib-decoded/wargear/wargear/core/race_ork/armor/war_boss_epic.txt" \
  "$R/sga_art/000_data/DATA/art/race_ork/troops/boy/animations/dakka_deff_gun/fb_idle_stand_01.hkx" \
  "$R/sga_art/000_data/DATA/art/race_ork/troops/boy/animations/dakka_deff_gun" \
  "$W/shoota.glb" 1.9

# the carnifex ships `talons_crushing` / `talons_venomcannon`, not `range_burst`
run dow_tyranid_lictor \
  "$R/attrib-decoded/wargear/wargear/core/race_tyranid/armor/lictor_common.txt" \
  "$R/sga_art/000_data/DATA/art/race_tyranid/troops/carnifex/animations/talons_venomcannon/fb_idle_stand_01.hkx" \
  "$R/sga_art/000_data/DATA/art/race_tyranid/troops/carnifex/animations/talons_venomcannon" \
  "" 2.4

run dow_necron_overlord \
  "$R/attrib-decoded/wargear/wargear/core/race_necron/armor/survive/nec_crown_tachyon.txt" \
  "$IG/guardsman.hkx" "$IG/animations/range_burst" "$W/staff.glb" 2.2
