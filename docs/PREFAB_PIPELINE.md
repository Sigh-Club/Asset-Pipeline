# Prefab pipeline — how to author DoW2 parcels that reach XCOM's level of detail

Research document, no code. Sources: XCOM 2 SDK `Documentation/Content/XCOM2Mods_LevelDesign.pdf` and
`XCOM2Mods_Environments.pdf` (shipped, primary), Joel Burgess & Nate Purkeypile, *Skyrim's Modular
Approach to Level Design*, GDC 2013 (transcript), the Polycount modular-environment bibliography, and
our own measurements of the DoW2 corpus. Read with `docs/MAP_AUTHENTICITY.md` (what the assets are) and
`docs/BOARD_GRAMMAR.md` (what XCOM's level grammar requires).

## 1. The finding that changes the plan

I assumed DoW2's 256–512 px textures were the ceiling. They are not. XCOM 2's own environment spec
says:

> "Most cover props in XCom 2 will use a max map size of 1024x1024 … the editor will down sample your
> texture by half. So your 1024 will be reduced down to a 512 in game."
> — `XCOM2Mods_Environments.pdf`, Texture Setup

**XCOM's props ship at 512 px.** DoW2's ship at 256–512 px. The resolution gap is one step, not an
order of magnitude. What XCOM does with that budget, and we do not, is a *material structure*:

| XCOM channel (`MSK`) | Purpose | DoW2 equivalent we already have |
|---|---|---|
| R — material mask (spec) | samples a shared PBR material library | `_spc` (specular colour) |
| G — cavity mask | baked cavity shading, sells form at low poly | `_ocl` (baked occlusion) |
| B — tint mask | per-instance faction/zone tint | derivable (per-prop mask) |
| A — emissive/opacity | lamps, signs, glass | derivable; some props ship emissive |

Our import collapses four shipped maps into two (`albedo_ao`, `roughness`) and pins metallic to 0 and
roughness to a constant. Every prop therefore shares one response, which is precisely why pieces
"don't sit together": they are all lit the same way regardless of what they are made of. **The cheap
look is a missing master material, not missing texture resolution.**

This is the single highest-value change available, and it is cheap: the channels already ship.

## 2. What XCOM requires of a parcel (the authoring checklist, from the SDK)

A parcel is a `.umap` authored to a fixed contract. Measured from `XCOM2Mods_LevelDesign.pdf`:

| Requirement | XCOM's value | Why it exists |
|---|---|---|
| tile size | 96×96 uu = **1.5 m** | the gameplay grid |
| parcel sizes | small 16×16, medium 32×16, large 32×32 tiles (24/48 m, 48/48 m) | lattice fitting |
| asset bounds | small ±768 uu (±12 m), medium ±1536/±768, large ±1536 (±24 m) | "assets outside these boundaries will collide with surrounding content" |
| asset archetypes | `XComLevelActor` / `XComDestructibleActor` / `XComInteractiveLevelActor` — never raw meshes | visibility, pathing, cover, destruction configured once, propagated to every instance |
| building markup | one `XComBuildingVolume` per roofed structure + `XComFloorVolume` per floor at Z 0/256/512 (**4 m per floor**), interior and roof volumes separate, inclusion/exclusion actor arrays | cutaway and building reveal |
| visibility markup | `HideWhenBlockingObjectOfInterest`, then a **build visibility** pass | the camera must see the unit inside a building |
| gameplay markup | `XComGroupSpawn` 3×3 (small 1, medium 2, large 4), `XComSpawnRestrictor`, `XComTurretSelector` | spawn selection, evac, turret placement |
| parcel definition | size, plot types, **zone types**, **facing** (street front), objective tags, entrance booleans | zoning and lattice matching |
| helper maps | a **parcel check map** per size and plot type (pathing visualisation + PIE) and a **light environment map** per time of day | test without loading the game; author PBR under real lighting |
| plot type | CityCenter, Slums, SmallTown, Shanty, Wilderness, Rooftops, Alien Facility — each with its own parcels and PCPs | mission→plot mapping |
| PCPs | road networks (corners, intersections, straightaways) and near/far periphery, authored as interlocking pieces | streets, and the world beyond the play space |
| biomes | **asset swapping after load** (meshes, materials, vegetation, particles) | variation without content bloat |
| light environments | separate streamed maps: skybox, dominant directional light, fog, weather | "parcels don't contain any ambient exterior lighting" |

The workflow the document describes is: blockout in a check map → place archetypes → add markup →
build visibility → test in PIE and Tactical Quick Launch → write the parcel definition. Two of those
stages are *checks* (check map, PIE) and one is a *build* step; all three are missing from our process.

## 3. Kit rules (industry, and directly applicable)

From the Skyrim GDC talk — the most transferable account of building a kit as a system:

* "Kits, first and foremost, are **systems**… The most important attribute of a kit is that it adds up
  to far more than the sum of its parts."
* **Footprints must be multiples of each other**: "a 512×512×512 room will always tile nicely with a
  256×256×256 hallway, but a 384×384×384 room will eventually create gaps and/or overlaps."
* **Snap size = half the footprint**, and as large as possible, so gaps are obvious.
* Kit-bashing is encouraged: mix sub-kits to avoid art fatigue, keeping the language recognisable.
* The failure mode they describe is *exactly* ours: design blockouts, art takes over, and "cover along
  a street has been converted into poles too thin to take cover behind… a wall intended as a visual
  blocker is now a see-through chain-link fence." Gameplay and art markup must be authored together,
  on the same prefab, or the art pass silently breaks the rules.

Applied to our grid (`TILE_SIZE = 2 m`, `ELEVATION_STEP = 0.35 m`): prefab footprints and wall
segments must be multiples of 2 m, snap at 1 m, and every prefab must carry its own gameplay markup so
a later art change cannot break it.

## 4. What a prefab is here (the schema we need)

A prefab is our parcel: a composed building or space, with markup, that the generator can place. It is
not a GLB and not a group of props — it is a **record plus a scene**:

```
identity      id, family, plot types, zone, faction, size (grid cells), facing
shell         wall/floor/roof/door/trim pieces (shipped models, 1:1, palette-locked)
entrances     per side: offset + width in cells, doorway piece, threshold height
floors        per floor: elevation, footprint, interior/exterior volumes, stair/ladder link
cover         per cover point: cell, direction, tier (0.64/0.96/1.6 m ladder), climb flags, piece
nav           walkable mask, room boundaries, door lanes
gameplay      spawn anchors (3x3 equivalents), restrictor volumes, objective sockets
dressing      decal set, roof props, wall signs, light fixtures, ambient audio
palette       the one shipped map whose materials/ground/light this prefab is locked to
damage        states and the pieces that swap (XCOM ships destructible actors; DoW2 ships rubble)
```

Every field is a **measurement or a shipped reference**, never a taste. `cover` tiers come from the
shipped ladder; `entrances` from the shipped nav; `palette` from the shipped map.

## 5. The asset work this requires

Ordered by value per unit of effort, all from shipped material:

1. **Master material** with XCOM's channel semantics (albedo, spec→roughness, cavity, tint, emissive)
   and one shared response curve. Rebuild the env kit through it. *This is the fix for "mixed
   materials".*
2. **Architectural kit families** classified from the 126 structural pieces we already export:
   wall runs (multiples of 2 m), corners, doorways (`wall_arched_01`), floors, roofs, stairs/ramps,
   trim, and windows. Each family needs a measured footprint and snap point, not a guessed size.
3. **Prefab library v1**, faction-neutral: hab block, bunker, depot/warehouse, ruined block, yard.
   Each built from family pieces only, with full markup.
4. **PCP equivalent**: street, junction, yard, and periphery pieces, cut from the same map as the
   prefabs they join.
5. **Decal library** (we already extract 420 distinct decals) organised by surface and zone, with the
   shipped density as the target (`0.21 per 100 m²` measured in `docs/MAP_COMPOSITION.md`).
6. **Light environment set** per plot type and time of day: key angle/colour/intensity, hemisphere,
   fog, weather. `boardLight.ts` already bakes a rig per board; it needs plot-type presets rather than
   per-board randomness.
7. **Faction plinths**: one authored ground+dressing pad per faction structure (`ig_bunker`,
   `chaos_generator`, `ork_generator`, `warp_generator`, …), so a faction building is placed with
   context instead of dropped on another map's ground.

## 6. The process, as a TODO programme with gates

Each phase ends in a gate that can fail. No phase is "done" on a green test alone: the gate is a
render plus a measurement.

**P0 — Material spine.** Build the master material and re-export the kit through it.
Gate: a render of six props (metal wall, concrete wall, sandbag, crate, ruined wall, glass) showing
distinct material response; a check that no prop's roughness is a constant; albedo range within the
shipped measured band.

**P1 — Kit classification and normalisation.** Split the 126 structural pieces into families; measure
footprints; reject pieces that cannot be brought to a 2 m multiple without stretching.
Gate: every family piece reports footprint, snap point and grid multiple; no piece is used as a wall
that is not in the wall family.

**P2 — Prefab schema, authoring tool, validator.** Implement §4, plus a check map equivalent (nav and
cover overlay in the forge).
Gate: the validator rejects a prefab with an entrance that does not match its own nav, a cover point
whose tier does not match its piece height, or a piece outside its palette.

**P3 — Prefab library v1.** Five prefabs, fully marked up, palette-locked.
Gate: assembled boards pass reachability (every prefab reachable), cover density inside the authored
band, and a render that reads as a place.

**P4 — Streets and periphery.** Interlocking street/junction pieces, cut from the same map.
Gate: seam matching with zero orphan openings; street continuity across a board.

**P5 — Detail layer.** Decal library, roof dressing, light fixtures, plot-type light presets.
Gate: decal density in band, light per plot type, and a close-range render where the 512 px budget does
not read as flat.

**P6 — Catalogue and solver integration.** Plot types, zones, facing, objective tags; the solver from
`assemble_parcels.py` reads the catalogue.
Gate: 100 boards generated, all reachable, palette purity 100%, zone mix matching the plot type.

**P7 — Faction plinths.** One per faction structure.
Gate: no faction structure sits on foreign ground; a render where Imperial reads as Imperial.

## 7. Acceptance metrics (what "authentic" means numerically)

| Metric | Target | Source |
|---|---|---|
| cover density | authored band 24–36% of cells | `docs/BOARD_GRAMMAR.md` |
| prop density | 0.69–2.78 per 100 m² (median–p90) | measured across 57 shipped maps |
| decal density | 0.21 per 100 m² | `docs/MAP_COMPOSITION.md` |
| palette purity | 100% of props from one shipped map | this document §1 |
| reachability | every prefab reachable | `assemble_parcels.py` gate |
| texel density | constant per surface, one repeat per 2.4 m of wall | `wallTexturing.ts` |
| material response | no constant roughness; distinct families | XCOM `MSK` model |
| light | plot-type preset, not per-board random | XCOM light environments |

## 8. Failure modes already measured (do not repeat)

* **Art pass breaking gameplay**: XCOM's own warning. In our pipeline the grammar placed cover, then
  wall heights were changed for looks and the cover tier no longer matched. Markup must live on the
  prefab.
* **Mixed palettes**: 20 of 68 staged boards mix props from 3+ biomes (worst: 10). One board, one map.
* **Cover-scale pieces used as architecture**: shells built from 3.2–7.2 m barrier walls while 7.9–23 m
  architectural pieces sat unused.
* **Faction structures with no context**: every faction structure in the kit has `placements: 0` in the
  shipped maps — they are army models, not map dressing. They need plinths.
* **A generated artefact that is not regenerated**: `dow2Roster.ts` and the staged layouts are only as
  current as the last generator run. Every phase above must regenerate and re-verify.

## 9. What must be invented, and what it costs

| Need | Cost | Honest quality ceiling |
|---|---|---|
| interiors | compose from interior pieces; carve rooms | reads composed, not authored |
| second storey | floor volumes + stair pieces | no believable stairs from DoW2 pieces; ramps only |
| trim/decals at close range | decal library from shipped decals | good; decals are cheap detail |
| light | baked rig per plot type | approximation of shipped lightmaps |
| periphery | cut from map edges, low fidelity | fine, it is fogged and out of play |

## 10. Recommended order

P0 and P1 first: they change what every later render looks like, and P0 is a re-export, not new art.
P2 can run beside them. P3 is the first phase whose gate is "does this look like a place", and it
should not start before P0 lands, or the verdict will be about materials rather than composition.
