# Map composition — what the shipped maps actually do, measured

> Audience: whoever authors a board, and whoever writes the generator that will. Every number here
> comes from `tools/dow2/composition_model.py` over the decoded corpus, and every one is checkable
> with the command in §6. Nothing here is taste.

The point of this document is to replace "scatter some cover" with a measured grammar. It also
records the two things that measurement *falsified*, because those matter as much as the numbers.

## 1. The frame (measured, do not assume)

Placements carry world metres as `(x, height, z)`. The nav grid's cell is **1 m** and its dimensions
are the playable extent — 256×288 m for a 1v1 map, 448×448 m for a large one. A placement maps to a
nav cell by `nav_x = x + width/2`, `nav_y = z + height/2`.

Our combat board is 2 m per cell, so **a board is a window into a map at 1:1 scale**, never the map
squashed to fit. A 24×20 board covers 48×40 m of ground, and that is the scale a unit's height means
anything at.

## 2. The parameters

Corpus: 57 decoded map instances, 2,861 placements classified, 225 board-sized windows sampled.

| parameter | board window, 48×40 m | whole map | note |
|---|---|---|---|
| props | **26 median** (13–42 p10–p90) | 564 median | a board should carry ~26, not 172 |
| density | **1.13 per 100 m²** | 0.86 per 100 m² | window density is higher than map-average, because boards are placed over the action |
| prop spacing (nearest neighbour) | **3.94 m median** (2.67–6.27) | 4.1 m | props form runs at ~4 m, not isolated dots |
| clumping (index of dispersion, 10 m cells) | **1.30 median** (0.81–2.14) | 0.64 | >1 means clumped; a uniform random scatter measures 0.94 |
| hot-cell share (props in cells with ≥3) | **0.40** | 0.40 | 40% of props sit in dense groups |
| corridor width | **18 m median** (14–27) | same | lanes are wide; a 4 m gap is a doorway, not a lane |
| landmarks per map | — | **16 median** (1–28) | victory/strategic points, turret positions |
| decals (splats) | 0.21 per 100 m² | 349 per map | ~13 per board window |
| vista objects | — | **469 per map** | horizon layer |
| props on walkable ground | — | 0.65 | 35% of props are embedded in blocked geometry (walls, structures) |
| prop to nearest landmark | — | 36.9 m median | cover is *not* clustered around objectives |
| props within 20 m of a landmark | — | 0.13 | only 13% |

## 3. Two things this falsified

**"Props are gathered into cover pockets."** Single-linkage clustering at 3–20 m reports a median
cluster size of 1–2 on every shipped map. Props are *dispersed*: near-uniform coverage at ~4 m
spacing, with 40% of them in denser runs. The clumping that exists is measured by the index of
dispersion (1.30), not by finding clusters.

**"A real map is measurably denser or more clustered than a random scatter."** Density does not
separate them at all — generate a scatter at the same prop count and its density is identical by
construction. What separates authored from random is **arrangement**:

| metric | shipped windows | uniform random scatter |
|---|---|---|
| clumping (dispersion) | **1.31** | 0.94 |
| prop spacing | **3.86 m** | 4.42 m |

So an authoring rule that only fixes *how many* props a board has will still look random. The rules
that matter are about spacing and grouping.

## 4. The authoring rules that follow

1. **Window, don't squash.** A board is 48×40 m of ground at 1:1. Place it over the action (the prop
   centroid), never stretch a 256 m map across it.
2. **~26 props on a 24×20 board** (1.1 per 100 m²), and **~74 on a 40×40 board**.
3. **Space props at ~4 m**, in runs of 2–5, so the clumping index lands at 1.2–2.1. Isolated props
   at 10 m spacing read as litter.
4. **Embed ~35% of props in blocked geometry** — a wall with crates against it, a rock in a cliff
   face. Cover that stands alone in the open is not how these maps are built.
5. **Lanes are 18 m wide** (14–27). A board's impassable mass should leave lanes in that band.
6. **Landmarks are every ~37 m**, and cover is *not* heaped around them: 87% of props are more than
   20 m from the nearest objective. Rings of cover around a capture point are a different game's
   grammar.
7. **Decals at ~0.2 per 100 m²** — about 13 per board window. This is the layer we do not render yet
   and the largest single reason an imported board looks emptier than the map it came from.

## 5. How this is enforced

`tools/dow2/test_composition_model.py` is the acceptance test. It fails if:

- shipped windows stop being more clumped than a uniform scatter (the model would be measuring
  nothing);
- shipped props stop being more tightly spaced than a scatter;
- any shipped window leaves a wide sanity band (a model that quietly redefined "normal");
- a parameter disappears from the model.

Measured on the current corpus: shipped dispersion 1.31 vs random 0.94, shipped spacing 3.86 m vs
random 4.42 m, 220 windows, **PASS**.

A generated layout is judged with the same function: `score_board(props, area, model)` returns the
deviation from the corpus band per metric, so a generator can be told *what* is wrong (too sparse,
too evenly spaced, no dense runs) rather than only that it looks wrong.

## 6. Reproduce

```bash
cd asset-pipeline
python3 tools/dow2/composition_model.py --report          # measure the corpus
python3 tools/dow2/test_composition_model.py             # acceptance test
```

## 7. The decal layer (decoded and rendered)

Decals are the painted ground: craters, stains, road markings, snow slabs, rubble. They live at
`SCEN/GEWD/TERR/TTEX/COMP/RCSP/SPLT`, one record each:

```
u32 id, u32 name_len, name[name_len], f32 x, f32 z, f32 size_x, f32 size_z, f32 rotation
```

with the position in the same world metres as entity placements. Measured over the corpus: **420
distinct decals, 19,930 placements**, sizes from 1.3 m to 70 m. `tools/dow2/decal_kit.py` resolves
each name to its shipped texture (`nm_snow/snow_slab_01` →
`terrain_textures/splats/nm_snow/snow_slab_01_dif.dds`) and exports the palette with the corpus's
usage count; `forge_import.py` carries the decals inside a board window into the layout, and the
forge renders them at their authored position, size and rotation.

## 8. The landmark layer (gameplay structures)

The maps' functional identity: capture points, requisition points, resource drops, generators. 36
distinct gameplay blueprints across the corpus, and they are named by function rather than by the
mesh that draws them — a `victory_point_pvp` is drawn with `victory_point_02`, a `strategic_point_pvp`
with the `capture_point` beacon. `forge_import.py` carries that mapping explicitly (`GAMEPLAY_ALIASES`)
and skips the invisible helpers (`move_blockers`, `starting_position`, the `*_proxy` meshes), because
rendering a proxy puts a box on the board where nothing should be.

16 visible gameplay markers are in the kit (`capture_point`, `victory_point_02`, `requisition_point`,
`generator_ffa`, the resource drops, the stratagem drops, containers). Import resolution is now 74-90%
of placements per map, up from 47-74%, with the gameplay markers included.

## 9. The ground layer (decoded and blended)

The terrain is eight layers blended by two RGBA masks — layer `i`'s weight is `mask[i // 4]` channel
`i % 4`, accumulated as `sum(w_i * layer_i) / sum(w_i)`. The masks are raw RGBA at map resolution
(512×512 on a 1v1 map, 800×800 on a large one) and are decoded from `RCTI/MASK`; the layer textures
resolve from the map's own `RCTI/LAYR` records the same way a biome tile does.

`tools/dow2/terrain_bundle.py` writes, per map, the eight layer textures, the two masks and a
manifest; `forge_import.py` attaches that bundle to the layout, and the forge renders it with the
engine's own blend (`frontend/src/three/terrainBlend.ts`). Measured on the six shipped layouts: 7-8
layers and both masks each.

Two implementation notes worth keeping:

- **GLSL ES 1.0 cannot index a sampler array with a loop variable** ("array index for samplers must be
  constant integral expressions"), so the eight samples are unrolled. It is the same arithmetic the
  engine's loop performs, in the form the compiler accepts.
- The shader's lighting is matched to the forge's rig rather than to the engine's. Without that the
  terrain renders as a dark slab with correctly lit props standing on it.

## 10. Vista — what the count actually is

`counts.vista_objects` (469 per map, 1026 on a hive-city map) is **not a placement count**. Walking
the chunk tree, each `VIZO` record under `SCEN/MEAD/MOM!/OBJS` is a `DATAOREF` reference (magic
`DATAOREF`, then a type and an object id) to a vista object defined elsewhere; the map's actual vista
*placements* appear in the entity list like any other object. Measured: only 3 distinct vista
blueprints are placed across the 57 decoded maps (`smokestack_large_02` ×8, `long_flags_01` ×3,
`pipe_drain_large_01` ×1), because DoW2's horizon is largely baked into the terrain and the skybox
rather than placed as geometry.

Consequence, recorded rather than hidden: vista is built and rendered (the shipped models are in the
kit, a placed vista piece imports and draws), but most boards will not contain one, and a board's
window is usually centred on the action rather than on the scenery. `forge_import.py --centre x,z`
puts the window over any feature, which is how a vista-heavy board is produced.

## 11. The grammar, implemented and certified

`Imperium-of-Ash/frontend/src/three/boardGrammar.ts` generates a board from the parameters in §4:
lanes first (a 35% main lane, a cross lane only when the pair stays under 55% of the area), then
building plots in the free rectangles with alleys between them, then cover — 60% in runs along the
buildings, 40% spread in the open at the measured spacing, with a minority embedded in the blocked
mass. It then **measures its own clumping and repairs it into the corpus band** (0.85-2.1): the block
layout alone swung from 0.4 to 3.7 dispersion, and the band is the contract.

`tools/dow2/score_generated.py` scores generated boards with the same `score_board` the corpus model
uses. Measured on 12 boards at 24x20:

| metric | generated | corpus | uniform scatter |
|---|---|---|---|
| density | 1.15 per 100 m² | 1.13 | same by construction |
| mean deviation from the corpus band | **0.25** | 0.65 (shipped windows) | 0.55 |
| clumping (dispersion) | **1.45** | 1.30 | 0.94 |

The generator is closer to the corpus than the shipped windows are, and clearly separated from a
scatter. Two failures found and fixed on the way, both recorded because they are the kind of thing
that silently ships:

- the first version put every prop on the perimeter of one big block — a pile beside a building;
- the scorer compared cell coordinates against a model measured in metres, which reported dispersion
  3.7 for boards the generator had already repaired to 1.45.

The grammar replaces the cell-wise `Math.random()` cover pass in `addRandomCover` (which the urban,
jungle and desert battlefield generators all call) and the second random pass in
`defaultScenario.ts`. The forge gains a `generate` button and a board-size control.

## 12. Cover asset inventory (measured against the corpus)

Asked whether the kit carries what a turn-based cover system needs, so here is the count by class,
with what the shipped maps actually place. "Cover volume" means the prop ships a `.coverbox`, which
is what the grid consumes.

| class | in kit | of which with a cover volume | corpus placements |
|---|---|---|---|
| full walls (high walls, support walls, facades, lab walls) | 87 | 58 | — |
| half/low walls (low walls, sandbags, low metal, low concrete) | 19 | 17 | — |
| barriers (barbed wire, tank traps, barricades, fences, railings) | 22 | 18 | — |
| buildings and structures (bunkers, barracks, temples, towers, gates) | 39 | 18 | — |
| rubble and debris | 40 | 30 | — |
| **vehicle husks and wrecks** | **16** | 9 | 273 placements / 18 blueprints |

Vehicle husks were the one real gap: the kit carried 2 (a turret and a dreadnought) against 273
placements in the corpus. Sixteen are now built — Predator wrecks in three states, Leman Russ,
Battlewagon, Land Raider, Ork wartrukk, Valkyrie, Falcon, Fire Prism, Wraithlord, looted tank, Chaos
Predator, plus the ruined colosseum pillar — covering **270 of 273** husk placements.

The fix that made it possible is recorded because it generalises: a blueprint's file name is not its
model's (`wrecked_valkry_04` draws `valkyrie_wreck_04`, `ork_wrecks_looted_tank` draws
`wreck_looted_pred`), so `model_for` now reads the blueprint's own `animator = "..."` line from the
decoded attrib data instead of guessing from names.

## 13. What is still missing from the picture

- **the `VIZO` reference graph** — the 469-1026 references per map are decoded as references, and
  their targets are not resolved, so a map's full backdrop is not yet reconstructed;
- **vista placements are sparse** (3 distinct blueprints in the corpus) because the horizon is baked
  into terrain and skybox, not placed.

Until those are rendered, a board can be *correct* by these numbers and still look emptier than the
map it came from. That is the next programme, not a defect in the rules.
