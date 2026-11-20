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

## 8. What is still missing from the picture

- **vista** (469 per map) — the horizon layer; 65 shipped models, 13 in the kit;
- **structures and gameplay entities** — 36 types, the landmarks the rules in §4 refer to;
- **ground layers** — 8 per map with 2 masks; decoded, not blended.

Until those are rendered, a board can be *correct* by these numbers and still look emptier than the
map it came from. That is the next programme, not a defect in the rules.
