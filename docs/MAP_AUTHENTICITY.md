# Can DoW2 art carry an XCOM-style tactical game?

Answering the question directly, from an inventory of what actually ships, rather than from taste.

## Verdict

**Yes — but not by re-composing the kit.** The assets are good enough at a tactical camera and are
nowhere near good enough to survive being mixed. Every visible defect on our current board is a
composition defect, not an asset defect. Two of the three things that make it look cheap are
measurable and self-inflicted: we mix palettes on one board, and we build architecture out of cover
props. The third — texture resolution — is a hard ceiling that dictates the camera, not the plan.

## What the assets actually are (measured)

From the 57 decoded shipped maps (`output/source_lab/maps/*.json`) and the exported kit
(`frontend/public/assets/models/env/env_kit.json`):

| Property | Measured value |
|---|---|
| distinct environment models in the shipped maps | **741** |
| models we exported | **435** (58%) |
| triangle budget | median **368**, p90 1,834, max 5,184; **265 of 435 are under 500 tris** |
| texture resolution | **256x256** (`wall_01`), 512x256 (`metal_wall_01`), 512x1024 (`high_wall_03`), 512x512 (`building_wall_01`) |
| pieces at least 4 m tall | 194 |
| pieces at least 6 m tall | 95 |
| pieces at least 10 m long | 123 |
| biome tags on the props | jungle 789, urban 581, desert 540, volcanic 498, ice 313, spacehulk 242, military 188, industrial 124, ruins 104 |

This is a 2009 RTS kit: low-poly, low-resolution, authored to be seen from a 20–40 m RTS camera,
in hundreds, under baked light. That is not "low effort" — it is a coherent budget, and it holds up
exactly as far as DoW2 held up.

## Why the current board looks cheap (measured causes, not opinions)

1. **Palettes are mixed on a single board.** 20 of 68 staged boards place props from **3 or more**
   biomes; the worst places from **10**. A jungle clay wall next to a volcanic basalt block next to
   an urban metal plate is the "mixed materials and colours" the eye rejects. In DoW2 a map uses one
   map's palette, because a map *is* one palette.
2. **Architecture is built from cover.** The shell family is `wall_01` (3.4 m), `low_concrete_wall_01`
   (3.2 m), `metal_wall_01` (5.97 m), `ig_defense_wall_02` (7.2 m) — these are authored as *cover and
   barriers*, and we extrude buildings out of them. The shipped architectural pieces — 
   `facade_sh_building` (7.9 m tall), `building_pillar_03_inner` (**23.25 m**), `wall_spinelarge`
   (7.71 m), `urban_atrium_wall_small`, `wall_spine` (6.75 m), `temple_center_wall01` (12.67 m long)
   — are barely used.
3. **Faction identity is absent.** We have the faction structures exported (`ig_bunker` 1407 tris,
   `chaos_generator`, `ork_generator`, `warp_generator`, `brood_nest_01`, `hive_node`, `sm_beacon`,
   `waggh_banner`) and across all 68 staged boards there are **4 faction-structure placements**.
   That is why nothing reads as Imperial.
4. **The ground in the demo is our deck tile, not a shipped surface.** The shipped terrain is an
   8-layer blend with two RGBA masks per map (the engine's own), and it is the single largest surface
   in frame. Losing it loses the location.

## The structural trap nobody has named yet

The faction structures exist in the kit with `placements: 0` — every one of them. They are **army
models**, authored for a base-building plot, not map dressing. They have no map context: no matching
ground, no matching prop language, no matching lighting. Place `ig_bunker` on our generated ground and
it looks like a model dropped on a floor, because that is what it is.

Map dressing has the opposite property: it is authored *in situ*, coherent with its map, and it has no
interiors (DoW2 buildings are solid; the RTS never walks inside them).

So the assets divide cleanly, and the division is the design:

| Source | Gives us | Costs |
|---|---|---|
| shipped map geography (props, ground, decals, heights, nav) | authentic, coherent, real places at 1:1 | solid buildings, no interiors; one palette per map |
| faction structures (`ig_bunker`, shrines, ork walls) | faction identity, Imperial/Chaos/Ork reads | no context — needs its own ground and dressing authored around it |
| our own geometry | anything | looks like our own geometry |

Mixing these three inside one space is what produces the current board. Keeping them in **separate,
coherent contexts** is the whole fix.

## What DoW2's own maps do that ours does not (from the reference frames)

Read off the shipped frames (foundry interior, ruined street):

* **the ground carries the location**: rails set into the floor, painted hazard lines, cracked slabs,
  rubble drifts, kerbs. It is never a neutral tile.
* **cover is placed in purposeful lines and corners** — crate stacks against walls, barrel rows at
  junctions — not scattered.
* **overhead structure frames the space**: catwalks, gantries, pipes, arches. This is what stops a
  yard reading as a box.
* **light is local and warm against dark ambient**: lamps, fires, emissive panels. Flat hemisphere
  light is not how any DoW2 map is lit.
* **walls have relief**: buttresses, recesses, arches, banners. A single plate texture on a flat
  plane is the one thing DoW2 never does.

## The realistic approach

Three constraints, in order of impact, each with a check:

1. **One palette per board.** A board binds to exactly one shipped map for its props, ground, decals
   and light. Check: assert every placed prop's biome is in the board's palette set; the current
   corpus violates this on 20 of 68 boards.
2. **Architecture comes from architecture.** Shells are assembled from the 6–23 m architectural
   pieces, not from cover walls. Cover props do cover only. Check: shell pieces must be drawn from a
   named architectural family; the guard fails if a cover-scale piece is used as a wall.
3. **Faction structures get their own parcel.** A faction building is placed with an authored plinth
   of matching ground and dressing around it — a parcel, not a drop-in. Check: no faction structure
   may sit on another map's ground.

And the assembly method, which is the part that makes maps read as real places rather than as our
grammar's output:

**Cut parcels out of the shipped geography and solve the connections.** `cut_parcels.py` tiles the
decoded maps at 12 m and measures each tile's edge openings from the shipped walkability grid —
direction, offset and length, which is XCOM's entrance model measured rather than declared:

| tile | parcels | with ≥2 openings | openings on ≥2 edges |
|---|---|---|---|
| 12 m | 38,454 | 13,110 | **11,447** |
| 16 m | 25,324 | 6,339 | 5,009 |
| 21 m | 15,793 | 3,672 | 3,013 |

Measured zones at 12 m: open 16,245, fortified 7,896, industrial 5,773, ruined 3,762, natural 2,931,
overgrown 1,615, civic 232. Opening lengths 2–8 cells, evenly spread — real streets, real doorways.

`assemble_parcels.py` then fills a lattice with XCOM's solver (objective parcel first, constraint-first
slot order, bounded backtracking, no duplicates, symmetric seam matching, height continuity). Because
every parcel is taken from **one** map, the palette, ground, decals and lighting are continuous by
construction — constraint 1 is satisfied by the method rather than by a check.

Verified yield on a 4x3 lattice (48x36 m, the size of one of our boards), 60 seeds:

| Result | Value |
|---|---|
| boards solved | **60 of 60** |
| boards where every parcel is reachable | **60 of 60** |
| largest walkable component share | median **0.999**, min 0.927 |
| solve attempts per board | median **2** |
| wall time | 6.5 s for 60 boards (~0.1 s per board) |

Two defects were found and fixed by measuring this, both worth recording because they are the kind
that survives a green test:

* the solver returned parcels in *fill* order while the consumer joins tiles in *row-major* order, so
  every board's walkability was assembled misaligned — the boards looked fine and scored 40%;
* requiring every parcel to open into the board during the search cut the solve rate to 11 of 40,
  while verifying and retrying reached 60 of 60. Verify, do not constrain, when the constraint is a
  post-condition the search cannot see.

## What is genuinely not possible with these assets

* **Interiors that look authored.** DoW2 ships no enterable building shells. Rooms must be carved from
  solid masses (we do) or composed from interior pieces (`building_pillar_03_inner`,
  `urban_atrium_wall_small`, `wall_arched_01`) — and they will read as composed, not authored.
* **Modern material fidelity at close range.** 256–512 px albedo, no detail normals. The camera must
  stay at tactical distance (≥15 m, ≥40° down) or the ceiling shows.
* **A second storey with believable stairs.** DoW2 has ramps and plateaus, not floors.
* **DoW2's baked lighting.** It ships lightmaps we cannot use directly; we approximate with a baked
  rig per board (`boardLight.ts`) — which is the right approximation, but it is an approximation.

## What must be invented, and is worth inventing

* **The objective/landmark layer** (XCOM authors this per mission; DoW2 encodes it as victory and
  strategic points — we have those decoded as `landmark` placements and should read them).
* **Deployment zones** (derived, already done).
* **Interiors**, as composed rooms with two exits (already done, needs better pieces).
* **Faction parcels**: one authored plinth per faction structure, so Imperial reads as Imperial without
  contaminating a map's palette.
