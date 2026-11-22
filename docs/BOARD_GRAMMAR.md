# Board grammar — XCOM's rules, DoW2's assets

This is the authoritative statement of what a combat board is in this game. It exists because the
product drifted twice: first into "import a DoW2 map window and fight on it" (which has no grammar at
all — its buildings are solid paint), and then into "generate a board and draw it with our own grey
deck tile" (which has the grammar but not the art). Neither is the product.

**The product is XCOM's combat and XCOM's level grammar, dressed with Dawn of War II's art.** The
grammar decides where walls, floors, cover, doors, roofs and landing zones are. The art is DoW2: the
shipped wall kit, the shipped props, the shipped ground layers, the imported units — placed at 1:1, never
stretched.

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
