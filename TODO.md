# Asset-pipeline — live work tracker

**Updated 2026-11-23 (AAA-PC tier).** This is the actionable list, and it is the honest one: it states
what works, what is partial, and what is broken, with the measurement that decides each. Read it
before touching the DoW2 import.

Authority and detail:

- [`docs/ASSET_SPEC.md`](docs/ASSET_SPEC.md) — **the contract**, source-agnostic: what any asset
  must satisfy to work here, every item labelled measured / engine / choice. Read this first.
- [`docs/METHOD_PORTABILITY.md`](docs/METHOD_PORTABILITY.md) — the IP boundary (what we inherit, what
  we replace) and the adapter interface that lets a non-DoW2 source feed the pipeline.
- [`docs/ASSET_SPEC.md`](docs/ASSET_SPEC.md) §11 + `npm run guard:spec` — the enforcement.
- [`docs/DOW2_COMMUNITY_TOOLCHAIN.md`](docs/DOW2_COMMUNITY_TOOLCHAIN.md) — **one implementation of
  that contract**: the community importer, its constants, the pose sequence, the pruning rules, the
  export flags, the traps.
- [`docs/DOW2_ANIMATION_DECODE.md`](docs/DOW2_ANIMATION_DECODE.md) — the clip formats (delta-compressed
  **and** interleaved) and our decoder.
- [`docs/HANDOFF_TURN_BASED.md`](docs/HANDOFF_TURN_BASED.md) — the self-contained handoff prompt.
- [`docs/DOW2_STANCE_REFERENCE.md`](docs/DOW2_STANCE_REFERENCE.md) — how DoW2 units stand and the
  import rules.
- `docs/KNOWN-ISSUES.md` — recorded defects, not masked.

---

## 0. AAA-PC tier — built and gated (2026-11-23)

The pipeline can now produce the published AAA-PC band from an existing generative source, and refuses
to pass unless every gate passes:

```bash
tools/build_unit_aaa.sh line_infantry \
  output/img23d/line_infantry_mv/front.glb \
  output/img23d/line_infantry_mv/atlas/unit_textured.glb iron_directorate
```

Measured on line infantry: **120,000 tris, 1,366 px/m at 4096, 4K baked normal+AO, 22 joints,
9 clips, 4 transferred material slots, 15.3 MB, `glb_contract --kind aaa_pc` PASS, band PASS**.

Authority: [`docs/STYLE_BANDS.md`](docs/STYLE_BANDS.md) (sourced industry bands, our measured
position, and the dead-end list). The fidelity gap was three of ours, not the generator's:
a 4,160-tri profile with `normal_map: false`; bake tools that existed but were never called; and a
`texel_grid` UV layout that cannot carry a PBR normal map. All three are closed.

Open on this tier: a real LOD chain (the profile declares 120K→60K→25K→10K but only LOD0 is built);
per-unit material-slot review (slots transfer by nearest surface, which is correct but unaudited); and
the vision review gate (`tools/review/`) is built but not yet certified — see the T1 entry below.

### Modular assembly — the correction this pipeline needed (2026-11-23)

Research and comparison: [`docs/ASSEMBLY_MODEL.md`](docs/ASSEMBLY_MODEL.md). Short version: modern
characters are **assembled from parts on a shared skeleton with sockets** (Epic: "modular characters
comprised of multiple Skeletal Meshes"; gear attaches to sockets), and our AAA route was building one
fused mesh with one atlas — which is why every material decision was a global compromise.

Now emitted by `tools/build_unit_aaa.sh` alongside the combined LOD0:

```
output/aaa/line_infantry/parts/line_infantry_{armour_primary,metal_trim,armour_secondary,underlayer}.glb
output/aaa/line_infantry/unit.manifest.json   # parts, tris, sockets (Head/RightHand/LeftHand/Spine*/Hips), skeleton
```

Implemented as a pipeline stage (`tools/blender/aaa_assemble.py`, step 2/5), verified by re-loading
every export: `skeleton.glb` with 22 bones, 9 clips and **5 SOCKET_* nodes parented to their joints**
(`SOCKET_weapon_r`→RightHand, `SOCKET_weapon_l`→LeftHand, `SOCKET_head`→Head, `SOCKET_back`→Spine2,
`SOCKET_hips`→Hips); 4 parts at 43,008 / 31,266 / 29,724 / 16,002 tris, each skinned to that rig with
its own LOD1–LOD3 chain (50/25/10 %); `unit.manifest.json` carrying budgets, sockets and provenance.
Re-importing skeleton + parts renders the identical figure, so the set is complete.

Open, in order: per-part bakes (parts currently share the whole-body 4K bake); gear actually attached
at a socket rather than fused into the sculpt; parts authored/sourced separately rather than split on
material boundaries (`provenance` in the manifest says so).

## 1. Current programme

Copy DoW2 units 1:1 — geometry, rig, weights, materials, weapons, clips — and drive them from a
turn-based action system. DoW2 is an RTS, so the deliverable is its **action library**, not its
locomotion cycles.

## 2. State, measured (2026-11-18, session 2)

| piece | state | evidence |
|---|---|---|
| assembly | **working, community toolchain, table-driven** | `tools/dow2/build_community_units.py` builds all seven units from a table of shipped files; damage states and extra LoDs are pruned per part |
| rig | **working** | the add-on builds the armature from the model's own `FOLDSKEL` with its bone-axis adapter |
| clips | **working, both formats** | delta-compressed **and** `hkInterleavedSkeletalAnimation` (151 of 182 interleaved clips validate against their own reference pose; the 31 others are partial-track clips) |
| heads | **working** | from the ebps `animator_attachments`, chapter variants skipped |
| weapons | **working for all seven** | each unit's `default_wargear` resolved to shipped models: guardsman lasgun, necron tachyon arrow, tau plasma rifle, chaos power sword + bolt pistol, eldar witchblade + shuriken pistol, warboss kustom shoota + huge choppa, lictor talons (part of its armour) |
| materials | **working, opaque** | every unit material exports `OPAQUE` + single-sided (the add-on's alpha wiring made every material `BLEND`, which is why units were see-through and lost parts at an angle); `dow2_alphaTest` honoured as MASK where a source declares a cutout |
| action coverage | **7–21 actions per unit** | see the scorecard below; the four aim directions are new, and the Tau's aim set is static by design (its stance clip is two identical frames) |
| layering | **aim directions baked, fire/idle layers not** | the shipped single-track upper-body layers are composed onto the stance for `aim_left`/`aim_right`/`aim_up`/`aim_down` (5 units; the necron uses its shipped aim-pivot clips). The `.hkanim` is a clip container (227 embedded packfiles), so the state machine's *other* layer uses (fire over run, idle additive) are still exported as base clips |
| lab page | **45 units live** | `fidelity.json` regenerated (45 units, 542 actions, 0 FAIL), `UNIT_ASSET_REV 20261153`, dist rebuilt byte-identical to `public/` |
| masters conversion | **complete — 52 of 52 master entries dropped** | `tools/dow2/roster.json` (45 units) → `dow2Roster.ts` → `UNIT_MODELS` serves every archetype from a converted unit and drops the authored masters; the tab is now `ROSTER · converted` |
| playback speed | **1:1 with the shipped clip** | every action baked at its own duration on one 30 fps timeline; measured 0.000x deviation across 132 actions (`action_motion --timing-only`) |

### Per-unit scorecard

Rubric (110 points): assembly 20 · rig/weights 20 · materials 15 · weapons 15 · action coverage 20
(resolved/20, capped) · visual gate 10 · layered animation 10 (5 = aim directions composed from the
shipped layers, 3 = shipped aim-pivot clips only, 0 = no composition). A component is only scored when
it is measured — the visual gate means the renders were read against `docs/evidence/dow2-stance/`.

| unit | assembly | rig | materials | weapons | actions | visual | layering | total |
|---|---|---|---|---|---|---|---|---|
| dow_ig_guardsman | 20 | 20 | 15 | 15 | 20 | 10 | 5 | **95 %** |
| dow_eldar_farseer | 20 | 20 | 15 | 15 | 18 | 10 | 5 | **94 %** |
| dow_ork_warboss | 20 | 20 | 15 | 15 | 18 | 10 | 5 | **94 %** |
| dow_chaos_sorcerer | 20 | 20 | 15 | 15 | 17 | 10 | 5 | **93 %** |
| dow_tau_battlesuit | 20 | 20 | 15 | 15 | 15 | 10 | 5 | **91 %** |
| dow_tyranid_lictor | 20 | 20 | 15 | 15 | 13 | 10 | 5 | **89 %** |
| dow_necron_overlord | 20 | 20 | 15 | 15 | 11 | 10 | 3 | **85 %** |
| dow_tau_gun_drone | 20 | 20 | 15 | 15 | 7 | 10 | 5 | **84 %** |
| dow_tau_marker_drone | 20 | 20 | 15 | 15 | 7 | 10 | 5 | **84 %** |
| dow_tau_shield_drone | 20 | 20 | 15 | 15 | 5 | 10 | 5 | **82 %** |

Action coverage per unit (of the 20-name action set plus the four aim directions; missing names are
loadouts that ship no clip for them, which the manifest records as `not shipped`):

- guardsman 21 — 17 named actions + 4 aim directions; missing ability, leap, death_sync
- eldar 18 — missing idle_crouch, reload, ability, thrown_getup, death_sync, pinned
- warboss 18 — missing idle_crouch, reload, ability, leap, death_sync, pinned
- chaos 17 — missing idle_combat, idle_crouch, reload, grenade, leap, death_sync, pinned
- tau 15 — missing idle_combat, idle_crouch, reload, melee_01..03, ability, death_sync, pinned
- lictor 13 — missing idle_combat, aim, fire, reload, grenade, death_sync, pinned (a melee creature:
  its loadout ships no ranged clips, so it has no aim layers either)
- necron 11 — missing idle_combat, idle_crouch, reload, melee_03, grenade, ability, hit, thrown_getup,
  leap, death_sync, pinned
- tau_gun_drone 7 / tau_marker_drone 7 — turret rigs whose loadouts ship 12 clips each (`dhg_*`/`dm_*`):
  idle, fire, move, two deaths and two aim layers. No aim stance clip (the layers rotate the gun mount
  onto the idle), no melee, no reload, no crouch
- tau_shield_drone 5 — idle, ability (`sd_ability_field`), death, move. It ships no fire clip: its
  loadout is a support field

The gap to 100 % is the same two things for every unit: the game's layered animation (10 points) and
the actions their loadout genuinely does not ship.

## 2b. Roster conversion (the masters tab)

The masters tab lists `UNIT_MODELS`; the DoW2 roster is prepended to it and a master is dropped
automatically once every archetype it serves is covered (`stillNeeded` in `unitModels.ts`). Measured
now: **all 52 master entries are dropped** — every archetype is served by a converted unit, and the
authored masters are gone from the roster view. The tab is relabelled `ROSTER · converted`.

Coverage per faction (45 units): iron_directorate 9, cinderborn 9, eldar 5, ork 6, tyranid 6, tau 4,
necron 2. Where the shipped data offers fewer units than roles (Necron: 2 units for 4 roles; Tau: 4 for
6), one converted unit covers several archetypes — that is what the game itself does, and it is
recorded in `tools/dow2/roster.json` rather than invented.

Converting one is: add a row to `tools/dow2/roster.json` (ebps stem, faction, archetypes, optional
body/head overrides), run `discover_units.py --emit-build-specs` + `--emit-catalogue`, build with
`build_community_units.py --specs`, then the render gate. Data traps already paid for: several units'
own `.model` is a skeleton stub with no geometry (the body is the wargear armour — the ogryn, the
Zoanthropes and the Great Unclean One have *neither*, so they are skipped); some loadouts name clips
without the `fb_` prefix; vehicle rigs have no hand bones and name their clips `idle`/`drive`/
`death_die`; and a clip can ship for a unit without animating it (the Chimera's `fire_banewolf` drives
the Banewolf's turret — the action library now rejects a static candidate when a moving one exists).

## 2b2. Method capture and the portable spec (session 9, P0) — DONE

The pipeline was bootstrapped by reverse engineering DoW2, and the docs recorded *what we did with
DoW2* rather than *the method itself*. That is now fixed, because the art must eventually be ours.

- **`docs/ASSET_SPEC.md`** — the source-agnostic contract: space/scale, mesh (attribute set, 4
  influences/vertex, LODs, bounding volumes), rig, animation (per-frame local transforms, quaternion
  continuity, duration formula), material (the 28-slot interface and the specular-RGB/gloss-A
  convention with its exact metalness/roughness arithmetic), collision/physics/cover, terrain (8
  layers, 2 RGBA weight masks, activity grid, normalised blend), map format. Every item is labelled
  **measured** / **engine** / **choice**, with the file and line that settles it.
- **`docs/asset_spec.json`** — the machine-readable form, and **`tools/spec/validate_assets.py`**
  (exposed as `npm run guard:spec`) which checks our assets against it and cross-checks the spec
  against `tools/glb_contract.py`'s limits so prose, spec and gate cannot drift.
- **`docs/METHOD_PORTABILITY.md`** — the IP boundary with a primary source (US Copyright Office
  Circular 31, 17 U.S.C. §102(b): methods and systems are not protected; expression is), the
  inherit/replace lists, and the adapter interface a non-DoW2 source must satisfy.
- **Spec §9, "whose limit is it"** — 4 influences/vertex is a vertex-format fact (enforced); DoW2's
  54 bones per mesh is a D3D9 constant budget (recorded, **not** enforced: 19 converted units exceed
  it, up to 110 joints, and render correctly under our 256-bone WebGL2 limit).
- Measured state: `guard:spec` PASS over `env=151, prop=38, tile=1, unit=200, weapon=8`, with 28
  flat-colour imports recorded (shipped weapon shells and two necron units ship no texture, so no UV
  set exists to carry) and 19 units over the source engine's bone limit.
- Gate change: a `weapon` class was added to `tools/glb_contract.py` and to `scripts/guard_glb.py`'s
  path mapping (a standalone weapon has no armature of its own — it parents to a hand bone), keeping
  `guard:glb` at 246 checked / 0 failing.

Still to adopt from the community package (recorded, not started): the `.simbox` physics hulls, the
`.collision` simple/complex generators, `.markers`, `.hkanim` additive layering and `.motiontree`
state machines. Terrain layer blending is **done** on both surfaces: the forge and the game render
the eight-layer blend from the decoded masks (`docs/ASSET_SPEC.md` §7).

## 2c0. Map import into the forge (session 9, P1) — DONE

`tools/dow2/forge_import.py` converts a decoded shipped map into a forge layout (relief, biome,
placements) and six maps ship under
`Imperium-of-Ash/frontend/public/assets/maps/shipped/`. Three bugs were measured and fixed:

- **relief was carried at source scale**: 172-309 steps (60-108 m) on a 24x20 board of 2 m cells, so
  the camera sat inside the hillside. The board's relief is now normalised to a **6-step (2.1 m)**
  budget with the true source range kept in `source.relief`; a test asserts no imported layout
  exceeds it.
- **vista pieces were placed as board props**: `rock_pile_long_01` is 17 x 11.8 x 26.9 m and landed
  as a monolith in the middle of the board. `vista_*` entries are now excluded from placement, and a
  test asserts it.
- **the camera did not fit the board**: `span * 0.62 + 5` put a 48 m board outside a 45-degree frame.
  Framing now fits the board's diagonal to the camera's horizontal field of view and lifts the target
  to mid-relief.

Tests: `mapLayout.test.ts` 14 passing, including relief round-trip, resize/crop behaviour (the board
has a 4x4 floor), malformed height rows, and every shipped import inside the board, inside the kit,
non-vista, with relief within budget.

## 2c1. Map import quality and passability (session 9, P2) — DONE

- **The nav grid is decoded**: `WRLD/WLDI/PFDR/PRMP` layer 0 is width x height passability bytes
  (measured on `xp2_a_chapterkeepselenon`: 93,168 of 163,840 cells are zero, i.e. blocked). Imports
  now paint `impassable` where the majority of the nav cells under a board cell are zero, so an
  imported map carries its real walkable shape (61-174 painted cells per board).
- **The prop mapping is exact-then-head-noun, not prefix.** The old longest-shared-prefix rule is why
  a desert map placed `desert_mussel` 38 times. Resolution is now printed per map and recorded in
  `source.placement_resolution` with the top unresolved names: 47-74% of placements resolve.
- **The kit was rebuilt to 185 props (172 board, 13 vista)** from the corpus by frequency and scale
  (`--min-placements 25 --max-size 10`), up from 109. Exact coverage of corpus placements rose from
  30% to 51%. Two selection bugs were fixed: a blueprint's name is not its model's file name
  (`lab_wall_02a` ships as `sh_labwall_02a.model`, the most-placed wall in the corpus), and a flat
  `max(dimension)` test rejected a 12 m wall for being long while accepting a 7 m boulder.
- **Props with no diffuse map** in the source carry a `tint` measured from their biome's ground
  colour, and the forge applies it; the forge's lighting was also re-balanced (exposure 1.5 -> 1.0,
  total illumination ~6x -> daylight) because pale albedo clipped to white.
- **The forge paints relief**: `raise`/`lower` brushes at `ELEVATION_STEP`, clamped to
  `MAX_RELIEF_STEPS` (6), and `layoutToHeightGrid` exports it. Paint overlays follow the terrain.
- **A flaky test was fixed at the source**: `demoBackend.test.ts` failed 1 run in 3 because the demo
  shapes its board from an unseeded `Math.random`. `setDemoRandom` now lets a test fix the board;
  682 tests pass, repeatedly.

## 2c2. Composition model (session 9, P5) — DONE

The board is now authorable against a measurement instead of a taste. `tools/dow2/composition_model.py`
measures the corpus (57 maps, 2,861 placements, 225 board windows) and `docs/MAP_COMPOSITION.md`
records the grammar. The parameters an author builds to:

- a board is a **1:1 window** (48x40 m for 24x20 cells), never a squashed map;
- **~26 props** on a 24x20 board (1.13 per 100 m2), **~74** on 40x40;
- prop spacing **~3.94 m** in runs, clumping index **1.30** (a uniform scatter measures 0.94);
- **35% of props embedded in blocked geometry**; lanes **18 m** wide; landmarks every **~37 m** and
  cover deliberately *not* heaped around them (87% of props are >20 m from the nearest objective);
- decals at **0.21 per 100 m2** (~13 per board) — the layer we do not render yet.

Two findings were falsified and recorded: props are *not* gathered into pockets (single-linkage at
3-20 m gives singleton clusters; the clumping is 1.30 on a dispersion index), and **density does not
separate an authored board from a random scatter** — arrangement does (clumping 1.31 vs 0.94, spacing
3.86 vs 4.42 m). A rule that only fixes prop *count* still looks random.

`tools/dow2/test_composition_model.py` is the acceptance test and passes: it fails if shipped windows
stop being more clumped and more tightly spaced than a uniform scatter, or if a parameter vanishes.

Consequence fixed in the import: `forge_import.py` now windows at 1:1 instead of squashing the map
onto the board. Imported boards went from 172 props to 7-22, which is the corpus band — the old
figure was a 6.6x overdensity.

## 2c3. Decal layer (session 9, P6 step 1) — DONE

The painted ground is decoded and rendered. `SCEN/GEWD/TERR/TTEX/COMP/RCSP/SPLT` holds one record per
decal: `u32 id, u32 name_len, name, f32 x, z, size_x, size_z, rotation` — measured across the corpus
as **420 distinct decals over 19,930 placements** (349 per map, sizes 1.3-70 m).

- `tools/dow2/decal_kit.py` resolves each decal name to its shipped texture
  (`nm_snow/snow_slab_01` -> `terrain_textures/splats/nm_snow/snow_slab_01_dif.dds`) and exports 420
  textures with the corpus usage count to `frontend/public/assets/decals/` (74 MB).
- `forge_import.py` carries the decals inside a board window into the layout (`decals` array, float
  cell coordinates, metres, radians).
- The forge renders them at their authored position, size and rotation, with a `decals` toggle, and
  the layout format round-trips them (18 mapLayout tests, including footprint-based removal and
  crop-on-resize).

## 2c4. Landmark layer (session 9, P6 step 2) — DONE

The maps' functional identity is imported: capture points, requisition points, resource drops,
generators, stratagem drops. 36 distinct gameplay blueprints exist across the corpus and they are
named by function, not by mesh — `victory_point_pvp` is drawn with `victory_point_02`,
`strategic_point_pvp` with the `capture_point` beacon. `forge_import.py` carries that mapping
explicitly and skips invisible helpers (blockers, spawns, `*_proxy` meshes), because rendering a proxy
puts a box where nothing should be.

- 16 visible gameplay markers built into the kit (gameplay group).
- Import resolution rose to **74-90% of placements per map** (from 47-74%).
- The kit is now 417 props (every board-scale prop the corpus uses, 84% placement coverage) at
  363 MB, and `guard:glb` checks 544 files at 0 failing.

## 2c5. Ground blending (session 9, P6 step 3) — DONE

The terrain now renders as the shipped maps build it: **eight layers blended by two RGBA masks**
(layer `i` weight = `mask[i // 4]` channel `i % 4`, `sum(w_i * layer_i) / sum(w_i)`). The masks are raw
RGBA at map resolution, decoded from `RCTI/MASK` (512x512 on a 1v1 map, 800x800 on a large one).

- `tools/dow2/terrain_bundle.py` writes per map: 8 layer textures, 2 masks, and a manifest.
- `forge_import.py` attaches the bundle to the layout; the forge renders it with
  `frontend/src/three/terrainBlend.ts`.
- Measured on the six shipped layouts: 7-8 layers and both masks each; 16 MB of textures.

Two traps paid for: GLSL ES 1.0 cannot index a sampler array with a loop variable (the eight samples
are unrolled), and the shader's lighting had to be matched to the forge's rig or the terrain renders
as a dark slab with lit props on it.

## 2c6. Vista (session 9, P6 step 4) — DONE, with a measured caveat

The shipped vista models are in the kit and a placed vista piece imports and renders (verified on
`6p_angelgate`, whose three 60 m drain pipes now draw on the board). Two things were measured and
recorded rather than assumed:

- `counts.vista_objects` (469/map, 1026 on hive city) is **a reference count, not a placement count**:
  each `VIZO` under `SCEN/MEAD/MOM!/OBJS` is a `DATAOREF` reference to an object defined elsewhere.
- Only **3 distinct vista blueprints** are actually placed across the 57 maps
  (`smokestack_large_02` x8, `long_flags_01` x3, `pipe_drain_large_01` x1), because DoW2's horizon is
  largely baked into the terrain and skybox.
- `forge_import.py --centre x,z` puts a board window over any feature, which is how a vista-heavy
  board is produced; `--only`/`--centre` runs now merge into the shipped index instead of replacing
  it.
- The camera frames props' own extents: a 60 m drain pipe on a 48 m board previously put the camera
  inside the scenery.

## 2c7. Board grammar (session 9, P7) — DONE

The RNG scatter is gone. `frontend/src/three/boardGrammar.ts` generates a board from the measured
parameters: lanes first, building plots with alleys, cover 60% in runs along the buildings and 40%
spread in the open at the measured spacing, a minority embedded in the blocked mass, one landmark, and
decals on the lanes. It measures its own clumping and repairs it into the corpus band (0.85-2.1),
because the block layout alone swung from 0.4 to 3.7.

Certified with `tools/dow2/score_generated.py`, which scores generated boards with the same
`score_board` the corpus model uses. Measured over 12 boards at 24x20: density 1.15/100 m2 (corpus
1.13), **mean deviation 0.25** (shipped windows 0.65, uniform scatter 0.55), clumping **1.45**
(corpus 1.30, scatter 0.94).

Replaced: the cell-wise `Math.random()` pass in `addRandomCover` (used by the urban, jungle and desert
battlefield generators) and the second random pass in `defaultScenario.ts`. The forge gains a
`generate` button and a board-size control.

Two failures found and fixed, both recorded: the first version piled every prop on the perimeter of
one big block, and the scorer compared cell coordinates against a model measured in metres (reporting
dispersion 3.7 for boards already repaired to 1.45).

## 2c8. Staged layout library (session 9, P8) — DONE

68 staged layouts: 32 map variants (8 shipped windows x 4 seeds, cover re-laid on the imported ground)
and 36 biome boards (12 biomes x 3 seeds). `frontend/scripts/stageLayouts.ts` builds them,
`public/assets/maps/catalogue.json` carries the metadata and measurements, and the forge's `staged`
browser lists them so the library can be walked and judged.

Measured: density 0.99-1.15 per 100 m2 (corpus 0.41-1.31), clumping 0.90-2.08 (corpus 0.81-2.14),
embedded share 0.14-0.45 (corpus 0.35); scored against the corpus model, mean deviation 0.30 over 68
boards with clumping median 1.45.

`stagedLayouts.test.ts` guards it: every entry has a file, every prop is in the kit and inside the
board, every entry is in band, every window offers several distinct fights, and a map variant keeps
its imported ground.

Also this session: the vehicle-husk gap was closed (16 husks built, 270 of 273 corpus husk placements
covered) and `model_for` now resolves a blueprint's model from its own `animator` line rather than
guessing from names.

## 2c9. Staged layouts in the game (session 9, P9) — DONE

The library is playable, which is the only way to judge a generated board as a game rather than as a
plan.

- `Imperium-of-Ash/frontend/src/data/demoLayout.ts` holds the active layout; `buildDemoBattle` builds
  the grid from it (`layoutToTerrainGrid`), places its props as dressing, takes the board size from
  the layout and places both forces on passable ground. Without a staged layout the board is the
  product model's 23x23; the hardcoded 23/21 bounds are now board-derived.
- `/layouts` lists the catalogue (68 boards with density, clumping, embedded share) with kind and
  biome filters and a play button per row.
- `demoLayout.test.ts` (5 tests): board size, blocked ground, props as dressing, unit placement on
  passable cells, and the 23x23 fallback.

Recorded: the offline demo still shows the global server-status overlay when no Go backend is
running. That is pre-existing and unrelated to the layout path — the board renders behind it.

## 2c10. Real-world scale and weight-correct roster (session 9, P10) — DONE

- **Scale**: the shipped models are not in metres and their ratios differ per model (guardsman
  2.97 m, Chimera 6.96 m, Baneblade 10.55 m against 1.85 / 3.7 / 5.3). `build_community_units.py`
  now carries a real-world height per unit and the importer scales the rig to it before export, so
  the correction is baked into geometry and skeleton together. All 45 units rebuilt: guardsman
  1.96 m, Chimera 3.70, Sentinel 4.47, Manticore 4.00, Baneblade 5.30.
- **Roster**: the archetype mapping was positional, so a Baneblade held `logistics_engineer` and a
  Sentinel `pathfinder_scouts` — a scout squad rendered as a walker. Each heavy/vehicle model now
  carries a unique weight-class archetype and no infantry model carries one.
- `UNIT_ASSET_REV` bumped so clients reload the rebuilt models.

**A mission now reads the catalogue.** `backend/internal/stagedboard` loads the staged catalogue, picks
the board for the mission's biome (hashed from the mission id), derives the authoritative cells (paint ->
terrain, relief -> elevation, props -> cover tiers from the shipped cover volumes), places both sides in
the board's landing zones, and publishes `board_surface` / `board_light` / `decals` / `rooms` on the
battle state. Verified live on `m-pve-urban-1`: board `6p_angelgate_v2202`, 24x20, 183 impassable / 237
open / 60 cover, and the client drew the map's own ground mesh and the baked light. The generated parcel
grid is now the fallback for a biome with no staged board, not the default.

Recorded, not done: the `VIZO` reference graph is decoded as references but not resolved.

The board now draws what the pipeline decodes: the map's eight-layer ground at the board's window
origin, its painted decals, and building faces from the shipped wall kit at 1:1 scale
(`frontend/src/three/boardGround.ts`, `decalLayer.ts`, `structureShells.ts`).

## 2c. Environment kit and the map forge (session 8)

The map-making half of the programme. Measured inventory of what the extraction offers, and what was
built from it:

| piece | state | numbers |
|---|---|---|
| ground materials | **indexed** | `tools/dow2/ground_library.py` → `output/source_lab/ground_library.json`: 1,324 shipped terrain materials (3,519 splats, 1,041 tiles, 537 reflection cubemaps, 23 grass sets) indexed by biome with measured mean colours; 1,216 diffuse maps converted to PNG |
| map corpus | **decoded** | `tools/dow2/scenario_decode.py`: 156 of 164 shipped `.scenario` maps → per-map JSON (entity placements with position, terrain chunks, splats, vista objects) and `output/source_lab/biome_palette.json` (per-biome prop frequency) |
| environment kit | **78 props built** | `tools/dow2/build_env_kit.py` + `tools/blender/dow2_env_import.py`: the props the shipped maps place most per biome, filtered to combat-board scale (≤8 m, ≥8 tris), each with its shipped `.coverbox` volume and measured footprint; GLBs under `Imperium-of-Ash/frontend/public/assets/models/env/` |
| map forge page | **live at `/maps`** | `pages/MapForgePage.tsx` + `three/mapLayout.ts`: the engine grid (2 m tiles, 0.35 m elevation steps), prop palette by biome, cover brush, rotate/raise/remove, save/load JSON, two hand-authored example layouts |

Why the page exists: IoA's battlefield generation scatters cover with `Math.random()`
(`data/scenarios/defaultScenario.ts`), so a layout cannot be judged as a place. The forge places every
prop by hand on the same grid the combat engine uses, shows the shipped cover volume for each prop, and
serialises to a layout a mission can load.

The scenario decoder now follows the community add-on's own map structure (heightmaps, 8 ground layer
pairs, 2 blend masks, per-chunk layer usage, the nav grid, blueprint-accurate placements — see
`docs/DOW2_COMMUNITY_TOOLCHAIN.md`), and the ground palette is built from the maps' layer records.

Still open on this front: structures are not in the kit yet (they are models with motiontrees —
destructible), the big vista props (cliffs, 29 m trees) are excluded by the size filter and want a
separate vista layer, and the ground library's PNGs are indexed but not yet wired into a terrain
material.

## 2c11. Prefab programme (session 10) — RESEARCHED, NOT STARTED

The map work has been dressing a structure that has no parcels. This is the programme that builds the
parcels, and it is written up with sources and gates in
[`docs/PREFAB_PIPELINE.md`](docs/PREFAB_PIPELINE.md). Research findings that decide it:

* **Texture resolution is not the ceiling.** XCOM's own spec authors props at 1024 and ships them at
  512 (`XCOM2Mods_Environments.pdf`); DoW2 ships 256–512. The gap is a **master material with channel
  packing** (spec/cavity/tint/emissive), which DoW2 already ships as `_spc`/`_ocl`. We currently
  collapse four maps into two and pin roughness constant, so every prop shares one response — that is
  the measured cause of "the pieces don't sit together".
* **XCOM's parcel contract is documented and short**: fixed sizes on a 1.5 m tile, asset archetypes
  (never raw meshes), building/floor volumes at 4 m per floor, visibility markup with a build pass,
  group spawns 3x3, spawn restrictors, turret selectors, and a parcel definition with zone, facing and
  entrance flags. Plus two helper maps (a pathing check map and a light environment) that make the
  authoring testable without loading the game.
* **Kit rules are multiples and snaps**: footprints must be multiples of each other, snap at half the
  footprint (Skyrim GDC 2013). Our grid is 2 m, so families snap at 1 m and segment lengths are
  multiples of 2 m.

Phases, each with a gate that can fail (detail in the doc): P0 material spine, P1 kit classification,
P2 prefab schema + validator + check-map overlay, P3 prefab library v1, P4 streets/periphery, P5 detail
layer (decals, light presets), P6 catalogue + solver integration, P7 faction plinths.

State: **nothing implemented yet**. Existing pieces that this builds on: `cut_parcels.py` and
`assemble_parcels.py` (verified 60/60 boards, 0.1 s each), `env_kit.json` (435 props with measured
sizes and cover boxes), `terrain_bundle.py` (ground blending), `decal_kit.py` (420 decals),
`boardLight.ts` (baked light rig), `structureShells.ts` + `buildingPrefabs.ts` (the current shells,
which P1 replaces).

## 3. Ordered next work

0. **The prefab programme** (§2c11): P0 material spine first, then P1 kit classification. P0 is a
   re-export through a new master material and changes every later render; P1 decides which shipped
   pieces are architecture. Do not start P3 (prefab library) before P0 lands, or its verdict will be
   about materials rather than composition.
1. **The rest of the layering**: the aim directions are composed from the shipped layers now, but the
   game also layers fire over locomotion (`ub_fire_run*` over `fb_run`) and adds idle sway. Those are
   still exported as base clips. The layers and their bindings are decoded; what is missing is the
   *rule* that says which layer applies in which state, which lives in the `.motiontree` state
   machine (we read it only for event timing today).
2. **More units**: the whole Tau drone family is in (gun, marker, shield); next are other factions'
   loadouts, all through the same table (`tools/dow2/build_community_units.py`) — a drone needed only
   a table row plus its clip stems in the action library.
3. **More actions per loadout where the game ships them**: the necron (9) and tau (11) are the thin
   ones; their loadouts ship fewer clips, so this is a unit-choice question rather than a decoder gap.
4. **Ground contact per action**: measure and, where a turn-based consumer needs it, normalise the
   root height per clip. Deaths, getups and leaps legitimately go below the origin (measured: lictor
   leap 1.34 m, guardsman getup 1.42 m) because the shipped clip carries the fall.

## 4. Testing — the gate is visual

The numeric gate measures deformation from each mesh's own bind; it passed shard piles. The gate that
catches a wrong bind, a missing part or a broken animation is **looking at renders**.

```bash
# per unit: idle, fire, walk, death, and a close-up of the head and the weapon
blender -b -P tools/render_lab.py -- <lab dir> <png dir> --unit=<id> \
  idle:1 idle:60 fire:30 fire:45 walk:10 walk:20 run:10 run:20 melee:10 melee:30 death:30 death:60 \
  idle:1:head idle:1:weapon
python3 tools/dow2/action_motion.py --lab <lab dir> --static-only
python3 tools/dow2/action_motion.py --lab <lab dir> --timing-only   # playback speed vs the shipped clip
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/lab_fidelity.py --lab <lab dir>
```

Required review for every build:
1. render each unit's idle, fire, walk and death at two frames each, plus a head close-up and a weapon
   close-up;
2. **read the PNGs** and compare against `docs/evidence/dow2-stance/` — a pose that disagrees with the
   shipped game passes every numeric gate and is still wrong;
3. flag any action whose bone motion is below 2 cm (static), and any action whose motion exceeds the
   body height (usually a fall or a leap, not an explosion);
4. record the verdict in this file, not just in the report.

## 5. Commands

```bash
export DOW2_RETRIB=<unpacked DoW2 data>    # needs sga_art/ and attrib-decoded/
python3 tools/dow2/build_community_units.py --list
python3 tools/dow2/build_community_units.py --only dow_ig_guardsman
python3 tools/dow2/build_community_units.py
```

## 6. Standing rules (learned, do not relearn)

- **Use the community importer for assembly.** Do not rebuild bone construction or pose conversion by
  hand; the recipe is in `docs/DOW2_COMMUNITY_TOOLCHAIN.md`.
- **Prune states and LoDs per part** to `healthy` + the lowest LoD that part ships.
- **Materials are opaque unless `dow2_alphaTest` says otherwise.** A `BLEND` material is drawn without
  depth writes and sorts per object: that is the see-through unit and the part that vanishes at an
  angle.
- **Skip `chapter_*` blocks** — they are DLC swaps for the same slot, not extra parts.
- **Match bones by name against the armature's own names**, case-insensitively.
- **Never trust a numeric gate without a render.** A rigid mesh measures 0 % tearing.
- **Judge poses against the shipped game**, not from imagination.
- **A build that does not print `EXPORTED` is a failure**, whatever Blender's exit code says.
