# Board grammar — XCOM's rules, DoW2's assets

This is the authoritative statement of what a combat board is in this game. It exists because the
product drifted twice: first into "import a DoW2 map window and fight on it" (which has no grammar at
all — its buildings are solid paint), and then into "generate a board and draw it with our own grey
deck tile" (which has the grammar but not the art). Neither is the product.

**The product is XCOM's combat and XCOM's level grammar, dressed with Dawn of War II's art.** The
grammar decides where walls, floors, cover, doors, roofs and landing zones are. The art is DoW2: the
shipped wall kit, the shipped props, the shipped ground layers, the imported units — placed at 1:1, never
stretched.

**Evidence base:** every number in this document is cited to the shipped source in
`Imperium-of-Ash/docs/game-design/REFERENCE_SOURCE_REVIEW.md`. Read that before changing a rule here.

## Vocabulary, and where the source names are allowed

Three words are easy to confuse and the confusion has cost us work, so they are defined here.

| Word | What it means in this project |
|---|---|
| **the reference tactics game** | the game whose *mechanics and level grammar* we copy. Named in documents, never in code. |
| **the shipped kit / the source game** | the game whose *art* we use at 1:1: models, textures, ground, props, animations. |
| **the board** | what we build: a combat grid with our grammar and the shipped art standing on it. |

**Naming rule (owner, 2026-11-23): the source names do not appear in code.** No `xcom`, no `dow2`, no
`dawn of war`, in any casing, in:

- identifiers, types, constants, exported symbols;
- file and directory names;
- CSS class names and element ids;
- player-facing strings.

Use our own vocabulary (`board`, `cell`, `cover`, `kit`, `prop`, `parcel`, `prefab`, `roster`,
`clip`) or a neutral technical term (`unit_roster`, `turn_queue`, `clip_candidates`). The words belong
in documents, and in a code comment only when the comment is citing a concrete artefact — a source
file name (`XComWorldData.uc`), a shipped asset, or a document path. Prose in a comment says "the
shipped kit" or "the reference game", not "XCOM".

The reason is not tidiness: a codebase that names the *source* makes every later reader think we are
building a clone, and it hides which parts are ours to change. Our vocabulary is the contract.

## How to review a board

A review judges the product board, so it has to *be* the product board. Two surfaces do that:
`/demo` (a staged board, `?board=<n>` to pin one, `?reveal=1` to lift the fog for an art read) and
`/layouts`. A sandbox or fixture board — anything that builds its own grid — is a *mechanical*
harness: it may legitimately have no shipped ground and no baked light, so do not judge art on it.
If a harness is being used to judge art, that is a bug in the harness, not a verdict on the board.

## What XCOM's grammar actually is (measured from the shipped game)

Read from `XComWorldData.uc`, `XComCoverGrid.uc`, `XComCoverInterface.uc` and the XCOM 2 SDK plot
templates:

| Property | XCOM's value | Source |
|---|---|---|
| cell size | **1.5 m** (`WORLD_StepSize = 96` uu at 64 uu/m) | XComWorldData.uc |
| floor height | **1.0 m** (`WORLD_FloorHeight = 64`) | XComWorldData.uc |
| low cover height | **0.64 m** (`Cover_LowCoverHeight`) | XComWorldData.uc |
| high cover height | **0.96 m** (`Cover_HighCoverHeight`) | XComWorldData.uc |
| climb-over height | **1.6 m** (`Cover_MinClimbOverHeight`) | XComWorldData.uc |
| cover points per cell | **4, one per direction**, each with a tier, a location and a rotation | XComCoverGrid.uc |
| cover extras | peek-left / peek-right per direction, diagonal, climb-onto, climb-over | XComWorldData.uc cover bitfield |
| cover generation | traced from geometry at **16 cm** density, normal test at ~45° | XComWorldData.uc |
| plot lattice | **80 × 80 m**, parcels by size and role, mandatory/optional slots | XCOM 2 `Template_Plot_*` packages |

The parcels in those XCOM 2 templates are named by size and role — `ARC_16/24/32/48/64_Periphery_Commercial`,
`ARC_Periphery_CTY_Boulevard`, `ARC_RFT_Walkway_06x06_Mandatory/Optional` — and the plot is assembled
from them into the lattice. That is the composition model to copy: a catalogue of sized, role-tagged
pieces with mandatory and optional slots, not a scatter.

## What a board is here

1. **Plot**: an 80 × 80 m lattice at 1.5 m cells, with authored slots (periphery, route, plot, landmark).
2. **Parcels**: chosen from a catalogue by size and role. A parcel declares its floors, its walls, its
   doors and windows, its cover points and its dressing slots.
3. **Height**: floors at 1.0 m; a building may have more than one; roofs are walkable surfaces with a
   route onto them (ramp, stair, climb-onto).
4. **Cover**: directional cover points on cell edges, tiered on the 0.64 / 0.96 / 1.6 m ladder, with
   peek and climb flags — generated from the geometry and the dressing, exactly as XCOM traces it.
5. **Dressing**: DoW2 props, placed by the parcel's slots and measured composition (props/100 m²,
   clumping, embedded share, decals).
6. **Ground**: a shipped DoW2 map's own eight-layer terrain under the board, chosen by biome.
7. **Landing zones**: one per side, on walkable ground at opposite ends of the main route.

## Where we are against that (measured 2026-11-22)

| Requirement | State | Evidence |
|---|---|---|
| cell 1.5 m | **no** — ours is 2.0 m | `three/gridMath.ts` `TILE_SIZE = 2` |
| floor height 1.0 m | **no** — ours is 0.35 m | `ELEVATION_STEP = 0.35` |
| cover ladder 0.64/0.96/1.6 | **yes**, tier from prop height | `stagedboard.CoverTierForHeight`, `coverTiers.ts` |
| 4 directional cover points per cell | **no** — one tier per cell | rules read neighbours, data has no direction |
| peek / climb flags | **no** | — |
| parcels with size/role/slots | **no** — grammar places lanes and plots | `boardGrammar.ts` |
| enterable buildings | **partial** — 36/36 generated boards and 27/35 imported boards carry rooms | `roomCarving.ts`, `boardGrammar.planTerrain` |
| walkable roofs | **no** — roofs are lids | `buildRoomRoofs` |
| windows | **no** | `Cell.Opening` exists, unused by the grammar |
| more than one storey | **no** | — |
| DoW2 ground under the board | **yes** for generated boards now | `stageLayouts.ts` bundle per biome |
| DoW2 props at 1:1 | **yes** | `envKit`, `structureShells` |

## Decisions this document fixes

- **Generated boards are the default.** A mission is fought on a board built by the grammar. An imported
  DoW2 map window is a *ground and dressing source*, and a fallback — not the default board. (Changed in
  `stagedboard.Pick` and `preloadDefaultDemoLayout`.)
- **The deck tile is not a ground.** A generated board carries a shipped map's terrain bundle; it used to
  draw a 2.4 m grey module, which is why a grammar-built board still looked like a grid.
- **Art is DoW2, at 1:1.** No stretching, no repainting: a shipped prop's own diffuse, normal and
  specular, a shipped wall piece's own dimensions.
- **One renderer.** The board is drawn by the 3D board renderer, isometric camera, Three.js. The
  retired 2D board renderer is not a fallback for art review and nothing may mount it by hand; see
  `Imperium-of-Ash/docs/3D_COMBAT_MIGRATION.md`.

## How XCOM actually builds a map (read from the shipped source, 2026-11-22)

XCOM 2 does not scatter props on a terrain. It assembles a *plot* from a catalogue of **hand-authored
parcels that are named real places**, and it connects them by matching their entrances.

Measured from `XComGame/Config/DefaultParcels.ini` and
`Development/SrcOrig/XComGame/Classes/XComParcelManager.uc`:

| Property | XCOM's value |
|---|---|
| authored parcels | **172** (55 Small, 81 Medium, 36 Large) |
| parcel sizes | Small 14x14, Medium 14x28, Large 28x28 (cells) |
| parcels declaring entrances | **125** — `bHasEntranceN1/N2/E1/E2/S1/S2/W1/W2` |
| entrance lengths | 6 discrete lengths (`EEntranceLengthType_1..6`), plus "closed" entrances |
| parcel identity | a **place**: `sm_ArmsDealer_01`, `sm_ChowHouse_01`, `md_FuelDepot_01`, `sm_RadarArray_01`, `md_RecruitmentCenter_01`, `sm_TradingPost_01` |
| land-use zoning | Retail 26, Shanty 18, Neighborhood 18, Commercial 18, Wilderness 16, Civic 13, Developed 11, Closed 9, Open 7, TrainStation 2 |
| plot types | Wilderness 43, CityCenter 38, SmallTown 36, Shanty 34, Slums 18, Facility 11, Rooftops 9 |
| assembly | an **exhaustive backtracking solver** (`GenerateParcelLayout` / `ChooseNonObjectiveParcels`) that places parcels whose size, facing and entrances match, with no duplicate maps, objective parcel chosen first |
| cover | a separate authored layer: `XComPlotCoverParcel` (PCP) with its own type, turn type and required layers |
| buildings | `XComBuildingVolume` with **Floors** (multi-storey), per-floor `XComFloorVolume`, and a scanline/cutaway that reveals the interior when a unit is inside |
| layers | parcels declare `arrAvailableLayers`; the map activates layers, so one parcel yields several variants |

**The flow comes from entrance matching.** A parcel's streets connect to its neighbours' streets because
the solver only accepts a placement whose entrance faces the neighbour's matching entrance, at the
matching length, with the parcel's street front facing the plot. That is why XCOM's maps read as a real
location: the street network is *solved*, not painted.

**The "real place" read comes from the parcels being places.** An arms dealer, a chow house, a fuel
depot, a radar array, a recruitment centre — each is authored as that thing, with its own dressing,
signage and roof kit, then re-used.

## Where we are against that

| XCOM | Ours |
|---|---|
| 172 authored parcels with names, zones, entrances | **0 parcels** — lanes + plots + a scattered prop palette |
| entrances solved so streets connect | doors carved per building, never matched to a neighbour |
| land-use zoning (Retail, Civic, Wilderness) | one zone per board (a biome) |
| multi-storey volumes with floors and cutaway | one extrusion per region, flat lid, no floors |
| separate authored cover parcels | cover derived from prop heights |
| 1.5 m cell, 1.0 m floor | 2.0 m cell, 0.35 m floor |

## Known gaps in the frame (measured from the live demo, 2026-11-22)

Looking at the demo the way a player does — home page, TRY OFFLINE DEMO — the board had three defects
that had nothing to do with texture quality:

- **the ground ended at a hard rectangular edge with black beyond it**, so the board read as a slab
  floating in a void. The shipped map continues past the board's window and the ground shader maps world
  position into that map, so a larger plane under the board now shows more of the same ground.
- **the ground received no shadows at all**: the mesh set `receiveShadow` but the custom shader had no
  shadow code, so props and walls cast nothing onto the floor. Sampling three's shadow map from the
  custom shader was tried and **reverted** — it read as "shadowed" across the whole board and blackened
  the floor while the props stayed lit. Received shadows on the ground remain a known gap.
- **the frame had no buildings in it**: the composition put the rooms at the board's edge, so the
  player's view was open ground with a few cover props. Composition, not art.

## Why our buildings are boxes and XCOM's are buildings

Compared against an XCOM building (Advent city block) element by element:

| XCOM's building has | Ours had | Ours now |
|---|---|---|
| composed volumes at different heights, setbacks, a projecting entrance | **one extruded mass at one height** | still one mass — **next** |
| windows with frames and mullions in a rhythm | **none** | inset glass panels every other cell on walls ≥ 2.6 m |
| a door with a frame and canopy on the street side | one arched piece, on one face at most | unchanged — **next** |
| roof equipment: AC units, vents, pipes, planters, signage | **a bare flat lid** | shipped kit props on a deterministic minority of roof cells |
| a pale concrete roof surface | the dark wall plate | concrete surface, light tone |
| plinth, cornice, trim bands, panel seams | a thin box strip | shipped plinth/cap strips (unchanged) |
| street furniture: lamps, benches, planters, kerbs | shipped lamps and decals only | unchanged |

The single biggest remaining difference is **massing**: XCOM's buildings are two or three volumes with
different heights and setbacks; ours is one extrusion per region. That is a composition change, not an
art change, and it is next.

## Remaining work, in order

1. **Walkable roofs + windows + a second storey.** The three structural things that still make our
   buildings read as boxes rather than as XCOM buildings.
2. **Directional cover points** (4 per cell, with peek and climb flags) replacing the single tier.
3. **Parcel catalogue** with sizes, roles and mandatory/optional slots, replacing lane-and-plot filling.
4. **Metric alignment** to XCOM's 1.5 m cell and 1.0 m floor, which changes the movement and sight
   numbers and therefore needs its own balance pass.
