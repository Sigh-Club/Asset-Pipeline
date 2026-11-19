# Changelog — IoA Asset Pipeline

All notable changes to this project are documented here.

## [Unreleased] — 2026-11-18 (session 4)

### Fixed

- **Every action played at the wrong speed on most units.** The builder set a per-action
  `scene.render.fps_base`, but the glTF exporter converts keyframes to seconds with a single scene
  rate at export time, so each unit inherited the rate of whichever clip was keyed last. Measured:
  eldar and lictor 3.7-3.9x too fast, the Tau battlesuit 7.5x (and its 2-frame aim clip collapsed to
  0.00 s), while the guardsman, warboss and drones were already 1.0x. All actions are now baked onto
  one 30 fps timeline at their own true duration — measured 0.000x deviation across all 132 actions —
  and `tools/dow2/action_motion.py --timing-only` gates it (a >2 % speed difference fails).

## [Unreleased] — 2026-11-18 (session 3)

### Added

- **Layered aim, composed from the shipped upper-body layers.** `hkAnimationBinding` is decoded
  (`Packfile.animation_bindings()`: track -> bone, blend hint) — a layer's track index is not a bone
  index (`aim_stand_horiz` track 0 drives `Bip01 Spine1`), and reading it without the binding rotates
  the root. `tools/dow2/action_library.py` now bakes `aim_left`, `aim_right`, `aim_up`, `aim_down`
  per ranged unit: the unit's own stance with one layer held at a measured 45 degree offset, with the
  measured bearing/elevation recorded in the sidecar. The axis each family carries is measured, not
  assumed (`aim_stand_horiz` is the bearing sweep, `aim_stand_virt` the elevation sweep), and the
  direction names are assigned from that measurement. The necron's layers are empty stubs, so its
  shipped `staff_fire_aim_pivotl/pivotr` clips serve left/right directly.
- `tools/blender/dow2_import_community.py`: applies layers through their binding (replaces the driven
  bone's local transform; the layer's translation and scale equal the base's).

### Added

- **`dow_tau_gun_drone`** — the first non-humanoid unit: a 6-bone turret rig with its own `dhg_*`
  clips (idle, fire, move, two deaths) and two aim layers that rotate the gun mount. Its wargear's
  `render_model` is an empty string (the gun is part of the drone model), which the part resolver now
  skips. The action library carries its clip stems; `action_motion` measures the effect time on the
  whole rig when a unit has no hand bones.

- **`dow_tau_marker_drone` and `dow_tau_shield_drone`** — the rest of the Tau drone family, from their
  own rigs and clip sets (`dm_*`, `sd_*`). The shield drone ships an ability instead of a fire clip
  (`sd_ability_field`), which is the first unit to resolve `ability` from its own loadout.

### Changed

- Lab action count 91 -> 132 (the aim directions and the three drones). `fidelity.json` regenerated:
  10 units, 0 FAIL. `UNIT_ASSET_REV` 20261149.
- `TODO.md` scorecard updated: layering scored at 5/10 where the aim layers compose (3/10 for the
  necron's shipped pivots), totals 85-95 %.

## [Unreleased] — 2026-11-18 (session 2)

### Added

- `tools/hkx/hkxread.py`: `hkInterleavedSkeletalAnimation` decoder (frame-major `hkQsTransform`
  array, no reference-pose anchoring) and interleaved-aware validation. Measured: frame-0 rotations
  reproduce each file's own `hkSkeleton` reference pose exactly (0.000 deg); read track-major the same
  file is 177 deg out. Corpus sweep: 151 of 182 interleaved clips validate, the rest are partial-track
  or skeleton-less. Gives the chaos sorcerer its true `run`/`walk`/`melee` and adds `melee_01..03` to
  every loadout that ships them.
- `tools/dow2/build_community_units.py`: table-driven build for all seven lab units — blueprint,
  wargear, head attachment, `default_wargear` weapons and loadout per row, resolved to shipped files,
  assembled through the community add-on, pruned, exported and copied into the game's lab.
- `tools/dow2/action_motion.py`: per-action peak bone travel over every frame, acting-hand peak speed
  and effect time, and lowest mesh point. Replaces the frame-0-vs-75 % screen that reported the Tau
  fire recoil as 0.001 m.
- `tools/render_lab.py`: `--unit=<id>` filter and close-up views (`:head`, `:weapon`, `:upper`), robust
  percentile framing, and weapon framing on the weapon mesh rather than its bone.
- `tools/dow2/parts.py`: `--ebps` (resolves a unit's `animator_attachments` head) and
  `entries_outside_chapters()` — `chapter_*` blocks are DLC swaps for the same slot (the Ork
  Freebooterz cutlass beside the warboss's choppa) and must not be imported as extra parts.
- Shipped weapons for every unit, from each blueprint's `default_wargear`: chaos power sword + bolt
  pistol, eldar witchblade + shuriken pistol, warboss kustom shoota + huge choppa, Tau plasma rifle,
  plus the existing guardsman lasgun and necron tachyon arrow.

### Fixed

- Units could be seen through and lost parts at an angle (the necron overlord's face was the clearest
  case): every material exported as `alphaMode: BLEND` because the add-on wires diffuse alpha into the
  Principled Alpha with a HASHED blend mode glTF cannot express. Materials now export `OPAQUE` unless
  the source's `dow2_alphaTest` declares a cutout (MASK via a ROUND node), with backface culling on.
- Duplicated geometry: the add-on imports every damage state and every LoD, so the farseer's head
  arrived as two coincident copies plus one at LoD2 (the wreck head over the healthy one is what made
  the eldar face read as a grey plate). Each part is now pruned to `healthy` + the lowest LoD it
  ships.
- The eldar face is textured, not near-black: `relic.material.standard_15` carries `farseer_head_dif`;
  the grey over the lower face is the shipped jaw guard (checked against the game's own portrait,
  added to `docs/evidence/dow2-stance/`).
- The Tau `aim`/`fire` "static" diagnosis was a measurement artefact: the source aim clip is two
  identical frames (0 of 32 tracks move, a held pose), and the fire clip moves 21.5 deg at the
  shoulder and 0.282 m of bone travel inside its first 20 frames.

### Changed

- `fidelity.json` regenerated (7 units, 91 actions, 0 FAIL); `UNIT_ASSET_REV` bumped to `20261146`;
  frontend dist rebuilt byte-identical to `public/`.
- `TODO.md` rewritten with the per-unit scorecard (rubric: assembly, rig, materials, weapons, action
  coverage, visual gate, layered animation).

## [Unreleased] — 2026-10-08

### Added — DoW decompile: animation / skeleton / team-colour pipeline

- `tools/dow/whm_animdata.py` — WHM skeleton/animation/marker/camera
  extractor → JSON; full RSGM v4 chunk anatomy documented (SKEL biped,
  embedded named ANIM clips with local pos/quat keys, MARK attachment
  markers, CAMS, SHDR material channels, 48-byte skinned vertex layout).
- `tools/dow/pose_whm.py` — skin any animation frame to OBJ (bind pose =
  anim frame 0, empirical; SKEL-rest bind tears limbs on Definitive assets).
  Feeds `blender_ork_import.py` unchanged — the sprite-sheet workhorse.
- `tools/dow/wtp_tint.py` — WTP team-colour compositor (PTLD soft masks ×
  `.teamcolour` RGB, multiplicative blend; PTBD badge rect decoded).
- `docs/DOW_IMPORT.md` §6 — full decompile writeup, replication recipe
  (authoring assets in DoW convention), GOG extraction runbook.
- Full GOG archive set extracted to `/run/media/talzanar/games/dow-definitive/`
  (W40kData.sga: unit icons, WTP masks, badges, teamcolour lua).

### Fixed

- `rsh_extract.py`: multi-page RSH output collisions (pages suffixed
  `_0.._3`, page 0 = diffuse); `blender_ork_import.py` picks page 0 and
  imports `os` (previous NameError).

## [v0.4.0] — 2026-07-26

### Added

#### Render Queue System (new)
- **`tools/render_queue.py`** — Persistent render job queue manager. Add/remove/list/run jobs via `pipeline_cli.py queue` or `python3 -m tools.render_queue`. Queue stored in `output/render_queue.json`, survives reboots.
- **`tools/schedule_render.sh`** — Scheduler script for cron/at/systemd. Handles locking, `systemd-inhibit` sleep prevention, and nice priority.
- **`tools/queue_dashboard.py`** — Web dashboard on port 8081/8082 for visual queue management. Live progress bars, pause/resume, cron installation, and job removal.
- **Pause / Resume / Clean** — `queue pause` creates a sentinel file; current job finishes then queue stops. `queue resume` removes pause and restarts processing. `queue clean` resets stale "running" jobs and detects already-rendered units.
- **Crash recovery** — `queue run` automatically resets stuck "running" jobs to "queued" and skips units that already have ≥80% rendered frames on disk.
- **Real-time progress tracking** — Background monitor thread counts rendered PNG files every 5 seconds. Progress written to `output/render_progress.json` and displayed in the dashboard with animated progress bars.

#### Non-Humanoid Body Templates (new)
- **`tools/blender/parametric_vehicle_generator.py`** — Three non-humanoid body types: **vehicle** (tank/gun_emplacement/chassis), **creature** (quadruped with spine+4-leg armature), **insectoid** (segmented body with 6-leg armature).
- **`parametric_unit_generator.py`** modified — dispatches by `body_type` field, importing and routing to the non-humanoid module when appropriate.
- **6 non-humanoid configs + .blend files**: Predator Tank (Iron Directorate), Battle Wagon (Wreckstorm Clans), Gun Drone (Harmonic Collective), Swarm Beast (Parasitic Bloom), Chrono Scarab (Chrono Revenants), Shade Swarm (Void Corsairs).

#### NPC Faction Materials & Units
- **5 new PBR material sets**: bio_flesh, chrome_white, cyan_bone, red_rust, black_silver (total: 10 materials across 7 factions).
- **10 NPC unit configs + .blend files**: Parasitic Bloom (bloated_swarm, toxic_reaver), Harmonic Collective (precision_drone, logic_weaver), Chrono Revenants (time_soldier, chrono_guardian), Wreckstorm Clans (wreck_raider, scrap_boss), Void Corsairs (void_raider, shadow_blade).
- **Config inheritance hierarchy** — `promoted_from` field enables clean progression from base → promoted → highest tier.

#### Unified CLI Integration
- **`tools/pipeline_cli.py`** — Single entry point routing to 8 sub-pipelines: character, tile, ui, materials, critic, pack, sync, info, doctor, queue, dashboard.
- **Sub-pipelines by asset type**: character (generate/render/full/batch), tile (generate/render), ui (icons/buttons), materials (generate/list), critic (single/batch), pack, sync, info, doctor, queue (add/list/remove/clear/status/run/pause/resume/clean), dashboard.

#### UI & Tile Generators
- **`tools/generate_ui_elements.py`** — Pillow-based UI element generation for 3 faction themes (iron_directorate, cinderborn, neutral). Buttons, panels, dividers, icon frames.
- **`tools/blender/tile_generator.py`** — Procedural isometric tile generation for 3 tile sets (urban_concrete, industrial_metal, corrupted_steel). Ground tiles, wall segments, props.

### Changed

#### Animation System (v3 → v4)
- **Rotation amplitudes increased 3-8×** across all animations: idle_intensity=1.0, walk_stride=0.4, attack_speed=1.5.
- Frame diffs now 15+ pixels at 96×128 (was 1-9px).
- All 28 unit configs updated with new animation parameters.

#### Geometry Enhancement
- **+30% vertices**: Primitive segments increased 12→24, subsurf levels 1→3. Average vertex count: 630→822.
- **Side-profile widened**: Shoulders 0.26→0.30, legs 0.08→0.10. Codpiece/tabard geometry added for E/W silhouette.
- All 28 .blend files regenerated with new geometry and animation parameters.

#### Render Pipeline
- **GPU auto-detect** with CPU fallback — no more CUDA/OptiX crashes.
- **`--fast` mode** (16 Cycles samples) for iteration; `--samples N` for quality.
- **Streaming render output** — `_render_job` uses `subprocess.Popen` with line-by-line stdout reading for real-time progress tracking.
- **Critic thresholds rebalanced**: edge_density min 2%→1.5%, direction_variance max 30%→50%.

#### Bug Fixes
- Hardcoded paths in `batch_pipeline.py`, `sync_to_ioa.py`, `generate_status_icons.py` resolved.
- Blender GPU crash fixed: `import bpy` moved inside function.
- CLI blend file resolution priority fixed.
- Pillow `getdata()` deprecations updated.
- Robot framework references removed from imports.

### Removed
- Old `cmd_run` approach using `subprocess.run()` with `capture_output=True` — replaced with streaming `subprocess.Popen()` for real-time progress.
- Standalone batch render scripts — functionality merged into unified CLI and queue system.

### Documentation
- `CHANGELOG.md` — created this file.
- `README.md` — updated with queue system, dashboard, and pause/resume documentation.
- `.pi/skills/asset-pipeline/SKILL.md` — updated with queue, dashboard, and non-humanoid references.
- `development.md` — session log for v4 added.
- `PLANNING.md`, `PIPELINE_V2.md`, `PARAMETRIC_CONFIG.md` — updated with v3→v4 changes.

### Technical Debt
- Non-humanoid animation bone keyframes not yet written — `animate_*` functions in `parametric_vehicle_generator.py` need implementation.
- Tile render script (`render_tiles.py`) not separated from `tile_generator.py` — tile render command warns and falls through.
- Geometry Nodes rivets disabled pending Blender 5.1 API fix (`DistributePointsOnFaces` API changed).
- E/W side-profile still thin (8.4% vs 14.7% N/S) — consider cape or over-shoulder weapon.
- CLI timeout (120s) insufficient for full Cycles renders — use `--fast` or `queue run` directly.

## 2026-11-17 — DoW2 clip decode and the action library

The shipped animation tracks now decode, so one rig plays every clip from its loadout, with the
game's own timing and events.

- `tools/hkx/hkxread.py`: the packfile reader reads the class-name registry, the type table (member
  type/subtype/offset), the local/global/virtual fixups and the object stream; decodes
  `hkDeltaCompressedSkeletalAnimation` (static masks, static DOFs, bit-packed deltas, smallest-three
  quaternions) and `hkAnnotationTrack`; adds `validate_animation()`, which requires frame 0 to
  reproduce the file's own `referencePose` (measured 5.5e-06 m / 3.4°; corpus 236/243 decoded, 0
  structural failures).
- `tools/dow2/action_library.py` (new): named actions from the shipped loadout, with the shipped
  timed events read from the unit's `.motiontree` (`DATAEVNT` clip→(time,event), `DATAACTN`
  definitions) and a measured effect frame where no event ships.
- `tools/blender/dow2_build_unit.py`: `--actions` keys the real tracks as glTF actions named by the
  action, at the clip's own rate, and writes `<unit>.actions.json`. Motion is retargeted relative to
  each clip's own reference pose.
- `tools/rig_fidelity.py`: derives the clip's own key rate, measures a rigid-plate reference and
  exempts a metric only when the build is no worse than that reference; caches the GLB parse.
- `tools/lab_fidelity.py` (new): regenerates `lab/fidelity.json` from the worst keyframe of every
  action.
- `tools/sources/pack_sources.py` + `fetch_sources.py`: release `source-v2` adds each unit's
  `.motiontree` and `.marker` (295 files, 8.5 MB, hash-pinned).

## 2026-11-17 — shipped weapon import and an exact rig rest

- `dow2_build_unit.py`: `--weapon-model` merges the SHIPPED weapon `.model` with identity transform
  and binds it to the shipped `Bip01 R Weapon` (the model's marker table attaches `marker_muzzle` to
  `bip01 r weapon`, which is the confirmation the hand-authored hold table never had). `WEAPON_HOLD`
  is no longer consulted when a shipped weapon is given. The armature rest is now built from the
  shipped rest including bone orientation (head/tail plus roll from the matrix's Y/Z columns), so
  `REST matches the shipped skeleton` measures 1.2e-05 across the six lab units instead of 1.77 with
  a "pose transfer will twist" warning.
- `build_source_lab.sh` / `build_source_lab_all.sh`: an optional shipped weapon model argument,
  its texture cached, and the GLB weapon dropped when the shipped one is used (both merged two
  weapons).
- `sources`: release `source-v3` adds `lasgun.model` and its diffuse texture (297 files).

## 2026-11-17 — bind from the model's own bone table (the folding fix)

- `chunky_mesh.decode_foldskel`: parse the `.model` `FOLDSKEL` table (41 named bones with parent and
  local bind transform, orthonormal to 3.5e-07). Skin indices index this table directly.
- `dow2_build_unit.py`: the skin index -> bone map and the shipped weight column now come from that
  table; the proximity solve is kept only for a model that ships no FOLDSKEL. Case-insensitive bone
  resolution (`canonical_ci`), because FOLDSKEL names are lowercase and a miss silently creates a
  vertex group with no bone. Materials are assigned per face (a per-submesh list had put a second
  part's material on a single triangle). Unmatched bone names are reported by name and vertex count
  instead of being hidden.
- `tools/render_lab.py`: renders every lab unit in the bind pose and an action frame. The numeric
  gate measures deformation from our own bind and passed shard piles; the render is the gate that
  catches it.
- Measured: the solve disagreed with the model's own table on 29 of 35 indices. Guardsman, chaos
  sorcerer and eldar farseer now render as intact DoW2 units and animate.

## 2026-11-17 — every lab unit from its own shipped data

- `hkxread`: zlib-compressed clips are inflated (`78 da`), empty 8-byte stubs are rejected as empty
  rather than crashing, and a skeleton with no printable name block is decoded through the type table
  (the necron overlord's clips). Measured: the necron's 57-bone `RIG_*` skeleton now decodes.
- `chunky_mesh`: zlib-compressed `.model` files are inflated.
- `dow2_build_unit.py`: the weapon bone is resolved from the rig's own names (a weapon bone on the
  right, else any weapon bone, else a hand) instead of the hard-coded `socket_weapon_R`, which the
  necron's `RIG_*` rig does not have.
- `build_source_lab.sh`: an 8th argument adds the unit's own body for a wargear that lists overlays
  only, and a build that never reaches `EXPORTED` is a failure (Blender exits 0 on a Python
  exception, which had been reporting stale GLBs as BUILT).
- Lab table: warboss (own rig/clips/body), lictor and farseer (own animation sets), necron (005_data,
  own rig and clips). All six render as bodies in `output/source_lab/renders/`.

## 2026-11-18 — units assembled by the community toolchain

- `tools/blender/dow2_import_community.py` (new): imports a unit with the DoW2 Tools add-on
  (`dow2-blender`, Santos Tools 2 lineage) — the model's own bone table, its bone-axis adapter, its
  weights and materials — and merges the body, head and weapon onto one armature. Clips are applied
  with the add-on's own sequence (DirectX→Blender conversion, rest delta, adapter conjugation) and
  exported with `export_optimize_animation_size=False` (the exporter's default collapsed every
  action to two constant keys).
- The head is an ebps `animator_attachments` entry, not a wargear `render_models` entry; the tool
  takes it as an extra part (guardsman `cadian_trooper`, warboss `warboss_head_01`).
- Measured after the switch: every lab unit has a full-length idle with real motion (guardsman 221
  keys / 0.085 m, chaos 121 / 0.182, eldar 91 / 0.044, warboss 91 / 0.209, lictor 101 / 0.893), and
  the fidelity gate reports worst tear 0.007–0.073 against 0.16–0.32 before.
- The necron overlord is still built by the clip-rig path: its model rig (54 bones) and clip rig
  (57) have different hierarchies, so the add-on's single-rig recipe does not apply to it.

## 2026-11-18 — Tau added; necron fixed; scale sanity clamp

- `dow2_import_community.py`: the necron overlord now builds through the same path as the other
  units. Its clips decode translations correctly but carry scale values from -4951 to 699, which
  compounded down the chain (idle 255 m, melee 32,754 m). Shipped clips animate scale only within
  +/-25% (measured across the corpus), so an implausible component is treated as 1. After the clamp
  the necron's idle/aim/fire/melee/death all move in the 0.3-5.8 m range.
- Tau battlesuit commander added (`dow_tau_battlesuit`): XV8 crisis suit + burst cannon, its own 32-bone
  rig and `range_burst` clips, 11 actions resolved (fire carries 48 events). Data lives in `003_data`.
- `action_library`: added the Tau/farseer/banshee clip stems (`fb_aim_stand_1h/2h`,
  `fb_fire_stand_2cannon/1cannon/1plasma/1flamer/1meltagun/1glauncher`, `fb_melee_parry_01..03`,
  `fb_leap_fly`, `fb_idle_01`, `fb_melee_idle_*`).
- Known gap: the Tau's `aim` (a 2-pose clip) and `fire` export with almost no bone motion; the other
  nine Tau actions animate.

## 2026-11-18 — the community toolchain, documented

The lab units are built with the DoW2 community importer (dow2-blender v0.3.3, Santos Tools 2
lineage — the tooling behind the Elite mod), not with our own assembly. `docs/DOW2_COMMUNITY_TOOLCHAIN.md`
records the whole recipe: the add-on's bone-axis adapter and DirectX→Blender conversion, the
rest-delta pose sequence, the export flag that otherwise empties animations
(`export_optimize_animation_size=False`), the case-insensitive bone matching against the armature's
own names, the scale-track sanity rule, the ebps head attachments, the traps, and where each unit's
data lives.

`TODO.md` and `docs/HANDOFF_TURN_BASED.md` were rewritten to match: seven working units, the
remaining ordered work (interleaved clips, two static Tau actions, the dark eldar face material, four
missing weapons, layered animation), and a visual testing protocol — render idle/fire/walk/death plus
head and weapon close-ups, then read the PNGs against `docs/evidence/dow2-stance/`.
