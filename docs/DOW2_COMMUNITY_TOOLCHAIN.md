# DoW2 community toolchain — the recipe that actually builds the units

> Audience: the next agent. This is the method the lab units are built with. It is not our own
> assembly: it is the community importer used by the DoW2 modding scene (Santos Tools 2 lineage, the
> tooling behind the Elite mod), plus our own clip reader in place of its Windows binary. Everything
> below was verified on the shipped files and by rendering the result.

## Why a "simple import" is not simple

A DoW2 unit is not a file. It is a kit — body, head, weapon, the bone table, and a folder of clips —
and the game snaps them together at runtime. Three consequences, each measured:

1. **The model's rig and the clips' rig are different skeletons.** Same bone names, different frames.
   Only 5 of 39 local rests match between the guardsman's `FOLDSKEL` and its clip skeleton.
2. **Clip transforms are in DirectX space** and the conversion to Blender includes a mirror
   (`BLENDER_TO_DX` below). Without it, left and right swap and the mesh shears.
3. **The game layers animations** (base + upper-body additive, driven by `.hkanim`). One clip is one
   ingredient. We export individual clips; the game's composed pose is a later step.

The heads are not in the armour: they are the unit blueprint's `animator_attachments`
(`cadian_trooper`, `warboss_head_01`). Read the `ebps`, not just the wargear.

## The tool

`atmalto/dow2-blender` v0.3.3 (DoW2 Tools). Release zip, unpacked into
`~/.config/blender/5.1/scripts/addons/dow2_tools`. It enables on Blender 5.1 (declares 4.3) and its
**model import is pure Python** and works on Linux. Its animation *reader* is a Windows `.exe`
(`blender_hkx/havok_io_cli.exe`) used for import/export of `.hkx` and `.hkanim`; on Linux we replace
it with `tools/hkx/hkxread.py`, which decodes the same data (validated: frame 0 reproduces each
file's own reference pose to 1e-5 m).

ModDB is behind Cloudflare: use `stealth-fetch`, not `curl`.

## The constants (copied from the add-on, not invented)

```python
BONE_AXIS_ADAPTER     = Matrix.Rotation(radians(-90), 4, 'Z')   # model/skeleton_space.py
BONE_AXIS_ADAPTER_INV = BONE_AXIS_ADAPTER.inverted()
BLENDER_TO_DX = Matrix(((-1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))  # utils.py
DX_TO_BLENDER = BLENDER_TO_DX.inverted()
def dx_to_blender(M): return DX_TO_BLENDER @ M @ BLENDER_TO_DX
```

## The sequence

1. **Assemble with the add-on's importer**, merging extra parts onto one armature:

   ```
   bpy.ops.import_scene.dow2_model(filepath=body,  merge=False)
   bpy.ops.import_scene.dow2_model(filepath=head,  merge=True)
   bpy.ops.import_scene.dow2_model(filepath=weapon, merge=True)
   ```

   The add-on builds the armature from the model's own `FOLDSKEL`, applies the bone-axis adapter,
   binds the shipped weights and resolves the materials (it imports `_dif`, `_nrm`, `_spc`, `_emi`).

   **Prune what the add-on imports, per part.** It imports every damage state (`healthy`, `wreck`)
   and every LoD of every mesh group, and the game draws one of each. Exporting them all stacks
   coincident copies: the farseer's head arrived as two 865-vertex copies (one per state) plus a
   third at LoD2, and the eldar face rendered as a grey plate with a hole because the wreck head was
   drawn over the healthy one. Keep `dow2_group == "healthy"` and the **lowest LoD that part
   actually ships** — not a global `lod0`: the chaos sorcerer's head and backpack are authored only
   at LoD2, and a global rule deletes them (measured: 4 meshes -> 1).

2. **Weapons come from the unit blueprint's `default_wargear`, through the weapon's own wargear
   file.** `default_wargear` names the items (`chaos_sorcerer_hero.txt` -> sorcerer_default_sword +
   bolt_pistol_sorcerer; `eld_farseer.txt` -> witchblade + shuriken pistol; `ork_warboss.txt` ->
   twin-linked shoota + huge choppa; the Tau commander -> plasma rifle + shield) and each item's
   `render_models` names the shipped model. Two traps here: a `chapter_render_models` block is a DLC
   swap for the same slot (the Ork Freebooterz cutlass beside the choppa), and some wargear is an
   attachment with no model at all (the Tau `shield_default`). Both are skipped by
   `tools/dow2/parts.py:entries_outside_chapters`.

3. **Materials must export opaque unless the source declares a cutout.** The add-on wires every
   material's diffuse alpha into the Principled Alpha and sets the blend mode to HASHED; glTF has no
   hashed mode, so the exporter writes `alphaMode: BLEND` for all of them, and a BLEND material is
   drawn without depth writes and sorted per object — which is why the lab units could be seen
   through and parts vanished at an angle. `dow2_alphaTest` is the shipped cutout flag and it is
   false on every unit material measured here, so the alpha is removed (OPAQUE); where it is true, a
   `Math: ROUND` node is inserted, which is the graph Blender's exporter maps to MASK/cutoff 0.5.
   Backface culling is switched on to match the game.

4. **Layers compose through their own binding, never by track index.** A layer clip drives one bone
   (`aim_stand_horiz` -> `Bip01 Spine1`), and the file's `hkAnimationBinding` is what says which. The
   composed action replaces that bone's local transform with the layer's at the chosen frame; the
   layer's translation and scale equal the base's, so nothing else moves. `action_library.py` bakes
   the four cardinal aim directions this way and records the measured bearing/elevation per action.

4b. **Map a clip's tracks through its `hkAnimationBinding`, never by index.** A full-body clip ships an
   identity map, but a partial clip binds its tracks to specific bones — the Wartrukk's
   `chassis_idle_01` binds 3 tracks to bones 1, 41 and 42 (chassis, exhaust, exhaust cap). Applying
   track *i* to bone *i* put the chassis rotation on the root and played the truck tipped onto its side
   (111 deg off bind); 33 clips across 8 units were affected. Bones the clip does not track stay at the
   clip's own reference pose, which is what a partial clip means.

5. **Pose with the add-on's own maths** (`animation/import_core.py`): for each tracked bone,

   ```
   L  = dx_to_blender(track local)
   W  = parent_world @ L
   d  = rest_local^-1 @ (parent_world^-1 @ W)
   d  = ADAPTER_INV @ d @ ADAPTER
   set location/rotation_quaternion/scale, keyframe
   ```

   where `rest_local` is the armature bone's rest relative to the *nearest mapped ancestor in the
   clip's hierarchy* (the add-on's `parent_anim_idx`). Bones the model lacks (the necron's cape
   chain) are skipped and their children hang off the nearest ancestor the model has.

6. **Match bones case-insensitively against the armature's own names.** The add-on keeps the model's
   `FOLDSKEL` names (`bip01 r thigh`), not our canonical vocabulary. Mapping through
   `skeleton.canonical()` finds nothing, leaves every bone unkeyed, and exports a constant pose —
   this is what made the lictor's idle silent and the eldar have no idle.

7. **Export with `export_optimize_animation_size=False`.** Blender's glTF exporter otherwise
   collapses each action to two constant keys.

7b. **Bake every action onto ONE timeline at its own true duration.** The exporter converts keyframe
   numbers to seconds with a single scene rate, so a per-action `fps_base` is silently lost: whichever
   clip was keyed last set the rate for the whole file, and units whose last clip was slow exported
   fast (measured: eldar and lictor 3.7-3.9x, Tau battlesuit 7.5x, its 2-frame aim clip 0.00 s). Set
   `fps` once, and for each output frame derive the source frame from its time
   (`src = round(k * src_fps / BAKED_FPS)`), never from a re-quantised source index.
   `tools/dow2/action_motion.py --timing-only` fails a build that drifts more than 2 %.

8. **Scale sanity.** A clip's scale track is either sane (every component within ±25% of 1, measured
   across the corpus) or a decode artefact — the necron overlord's run from −4951 to 699 while its
   translations are correct. Judge the track as a whole: if any component is outside [0.5, 2.0], use
   1 for the whole clip. Per-component clamping left plausible-looking 0.38–3.13 values that made
   the model pulse (max joint scale deviation 0.12; 0.0003 after).

## Traps, all paid for

- Enabling the add-on twice in one session raises `register_class(...) already registered`; guard with
  `if "dow2_tools" not in bpy.context.preferences.addons`.
- Blender exits 0 on a Python exception inside `-P`. A build that never prints `EXPORTED` is a
  failure; check the log, not the exit code.
- `export_optimize_animation_size` (default on) silently empties animations.
- A clip whose hierarchy differs from the model's (necron 57 vs 54 bones) must not be placed by world
  matrix; use the rest-delta form against the nearest mapped ancestor.
- Five clip families are `hkInterleavedSkeletalAnimation`. They are decoded now (see
  `docs/DOW2_ANIMATION_DECODE.md`); a build that still shows a fallback clip is reading a stale
  manifest.

## Where each unit's data lives

| unit | art root | body | head/attachment | clips |
|---|---|---|---|---|
| dow_ig_guardsman | `000_data` | `troops_wargear/armour/ig_armour` | `heads/cadian_trooper` | `troops/gaurdsman/animations/range_burst` |
| dow_chaos_sorcerer | `000_data` | `armour/chaos_sorcerer_epic` | `heads/chaos_sorcerer_epic` + backpack | `chaos_lord/animations/melee_blade_range_pistol` |
| dow_eldar_farseer | `000_data` | `armour/farseer_armour_common` | head is in the armour | `banshee/animations/melee_blade_range_pistol` |
| dow_ork_warboss | `000_data` | `accessories/warboss_body` + `armour/warboss_armour_epic` | `heads/warboss_01` | `warboss/animations/melee_axe_range_pistol` |
| dow_tyranid_lictor | `000_data` | `armour/lictor_armour_common` | — | `lictor/animations/talons_claws` |
| dow_necron_overlord | `005_data` | `armour/necron_overlord_common` | `accessories/necron_overlord_headdress_02` | `necron_overlord/animations/melee_staff` |
| dow_tau_battlesuit | `003_data` | `armor/xv8_default_crisis_suit` | — | `battlesuit_commander/animations/range_burst` |
| dow_tau_gun_drone | `003_data` | `troops/drone_heavy_gun` (gun is part of the model) | — | `drone_heavy_gun/animations/base` (`dhg_*`) |
| dow_tau_marker_drone | `003_data` | `troops/drone_marker` | — | `drone_marker/animations/base` (`dm_*`) |
| dow_tau_shield_drone | `003_data` | `troops/shield_drone` | — | `shield_drone/animations/base` (`sd_*`, ability instead of fire) |

## The build and the gates

The table-driven build is `tools/dow2/build_community_units.py` — one row per unit naming the
blueprint, the wargear, the head attachment, the weapons and the loadout, all shipped files:

```bash
export DOW2_RETRIB=<unpacked DoW2 data>          # needs sga_art/ and attrib-decoded/
python3 tools/dow2/build_community_units.py --list
python3 tools/dow2/build_community_units.py --only dow_chaos_sorcerer   # one unit
python3 tools/dow2/build_community_units.py                            # all seven
```

It writes the action manifest, assembles through the add-on, prunes states/LoDs, fixes the materials,
exports, and copies the GLB plus `.actions.json` into the game's lab. A build that does not print
`EXPORTED` is a failure.

```bash
# renders (the visual gate; a numeric gate cannot see a wrong bind)
blender -b -P tools/render_lab.py -- <glb dir> <png dir> idle:1 fire:30 idle:1:head idle:1:weapon

# deformation gate, motion screen, and the per-action report the lab page reads
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/dow2/action_motion.py --lab <glb dir> --static-only
python3 tools/lab_fidelity.py --lab <lab dir>
```

`render_lab.py` takes `--unit=<id>` and a third shot field (`idle:1:head`, `idle:1:weapon`,
`idle:1:upper`) for the close-ups the gate requires.

## What the community tool knows about maps (reviewed 2026-11-18)

The add-on ships a `map_io/` package. Its own importer cannot run in this release — it imports a
`working/maps/chunky` module that is not in the shipped zip — but the *structure* it documents is
verified against the shipped files and is what this pipeline now reads:

| chunk path | content |
|---|---|
| `SCEN/GEWD/TERR/HMAN/HITE/HVAL/HEAD` + `VALS` | terrain grid: u32 width/height, then a zlib float heightmap |
| `TERR/TTEX/DATA` | tile world scale (f32 at offset 20; 8-32 m per tile across the corpus) |
| `TERR/TTEX/COMP/RCTI/LAYR` | the map's **8 ground layers**, each a `surface` path and a `cliff` path |
| `TERR/TTEX/COMP/RCTI/MASK` | the **2 blend masks** (ATTR = pixel dims, DATA = pixels) |
| `TERR/TTEX/COMP/RCTI/USAG` | per-chunk active-layer bits (one byte per chunk, bits 0..7) |
| `GEWD/SMEG/EBPT` | the blueprint path table for the map's placements |
| `GEWD/SMEG/ENTL/ENTY/ENTI` | placement: u32 id, i32 blueprint index, 4x3 transform rows |
| `SCEN/WRLD/WLDI/PFDR/PRMP` | the game's **nav grid** (width, height, layers, bytes) |

Its `map_io/terrain_shader_gap.md` records the runtime path from the executable
(`TerrainTextureLoad::Load` -> `RenderCompositeTiles::Load` -> `RenderTiles` ->
`ShaderParams`): the ground is eight layer textures blended by two masks, with a per-chunk active-layer
byte selecting which layers a chunk uses. That is the real ground model — a layer *pair* per index
(surface and cliff), not one texture per tile.

`tools/dow2/scenario_decode.py` was rewritten to this structure. Measured on the corpus: 156 maps, each
with its heightmap (e.g. 769x577 samples, 0-165.86 m), 8 layer pairs (e.g. `snow/snow_smooth_01` +
`stone/selenon_upheaval_01`), two masks at map resolution, a per-chunk layer-usage grid, a nav grid
(512x320x5 on a 1v1 map) and its placements with blueprint paths and transforms. `ground_kit.py
--from-maps` then builds the map forge's ground palette from those layer records rather than from
file-name guesses, resolving `stone/jungle_rocky_moss_02` to `terrain_textures/tiles/stone/
jungle_rocky_moss_02_dif.dds`.

Still to adopt from that package: the terrain material node graph (`terrain_material_nodes.py`, 438
lines: eight layers, two masks, mask-UV transform from the terrain bounds) and the collision-mesh
generator (`collision/`, walkable vs nav meshes), which is how the community authors the surfaces a
map needs for pathing.

### Building a roster, not one unit

`tools/dow2/discover_units.py` finds every unit the shipped data can build and writes both the build
specs and the game's roster:

```bash
python3 tools/dow2/discover_units.py --race ig                 # what the data offers
python3 tools/dow2/discover_units.py --emit-build-specs output/source_lab/roster_specs.json \
    --select tools/dow2/roster.json
python3 tools/dow2/discover_units.py --emit-catalogue ../Imperium-of-Ash/frontend/src/three/dow2Roster.ts \
    --select tools/dow2/roster.json
python3 tools/dow2/build_community_units.py --specs output/source_lab/roster_specs.json
```

The link is the game's own: a blueprint's `animator` field names the animation set (the art folder with
the clips and `.motiontree`), `default_wargear` names the parts, and each part's file carries the
shipped `render_models`. Two traps: several units' own `.model` is a 5-7 KB skeleton stub with no
geometry (the body is the wargear armour, and for the ogryn and the Great Unclean One it is missing
entirely — those are skipped), and some loadouts name clips without the `fb_` prefix, which the action
library carries as alternative candidates.

Measured on the current build (2026-11-18, session 6): 45 units, every one carrying its shipped
weapon or integral talons, 542 actions including the four composed aim directions per ranged unit,
motion peak 0.049-5.94 m per action, the Tau aim set static by design (its stance clip has two
identical frames), `lab_fidelity` 45 units / 0 FAIL, worst tear 0.0852 on the farseer's cloth (its
shipped rigid reference is 0.0855 on the same clip).
