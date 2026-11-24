# The reference's map grammar, measured from the shipped SDK

This is the answer to "should we imitate the reference's layouts and generation, and what exactly are
they?" — with numbers taken from the installed XCOM 2 SDK on this machine, not from memory or a summary.

Sources, all primary and local:

- `XCOM 2 SDK/XComGame/Config/DefaultParcels.ini` — 172 parcel definitions.
- `XCOM 2 SDK/XComGame/Config/DefaultPCPs.ini` — 443 plot-cover-parcel (road) definitions.
- `XCOM 2 SDK/XComGame/Content/XCOM_2/Maps/{Parcels,Plots,PCPs}` — 201 parcels, 122 plots, 454 PCPs.
- `docs/BOARD_METHOD_RESEARCH.md` — the GDC 2018 talk and the Gears Tactics write-up.
- `tools/xcom2/read_umap.py` — a package reader for measuring a parcel's contents directly.

## Parcels: the size mix and the entrance grammar

From the shipped parcel definitions (172 registered):

| size | count | footprint (GDC 2018) | area |
| --- | --- | --- | --- |
| Small | 55 | 12x12 tiles = 18x18 m | 324 m2 |
| Medium | 81 | 12x24 tiles = 18x36 m | 648 m2 |
| Large | 36 | 24x24 tiles = 36x36 m | 1296 m2 |

**Medium is the most common size (47%), large is 21%.** Our boards are 48x48 m (2304 m2) — **larger than
the reference's largest parcel**, and we use a single size.

Entrance flags (`bHasEntranceN1`, `N2`, `E1`, `S1`, `S2`, `W1`…):

| authored entrances | parcels |
| --- | --- |
| 0 | **105** |
| 1 | 30 |
| 2 | 24 |
| 3 | 6 |
| 4 | 6 |
| 5 | 1 |

**Most parcels declare no entrance at all** — they are solid blocks and the *plot* connects them. Our
catalogue required openings on two or more sides to call a cut "usable", which threw away 88% of the cuts
(22,015 → 2,651). That constraint was ours, not the reference's.

Plot types: Shanty 34, Wilderness 43, SmallTown 36, CityCenter 38, Slums 18, Facility 11, Rooftops 9.
Zones: Retail 26, Shanty 18, Neighborhood 18, Commercial 18, Wilderness 16, Civic 13, Developed 11.

## PCPs: the road network, which is what we have no equivalent of

443 road/plot-cover definitions across **23 types** — Street 65, Boulevard 61, Stream 40, DirtRoad 21,
Ravine 16, AdventRoad 16, Highway 15, Plaza 14, Park 12, Walkway 9, Periphery 90 — with **turn types**:
Straight 134, Corner 22, Intersection 20, T 20, Court 14.

Their footprints are **8-tile modules**: 8x8 (94), 8x16 (98), 16x16 (90), 16x8 (36), 16x32 (30), 32x32
(19). At the shipped 1.5 m step that is 12 m, 12x24 m, 24x24 m, 24x48 m, 48x48 m.

Two things follow. A plot is **a road network with parcels hanging off it**, not a lattice of parcels. And
there is a dedicated **Periphery** set (90 definitions) for the band around the play area.

## Cover: measured, not assumed

The parcel packages name their cover explicitly — `*_LoCover_1x1_*`, `*_HiCover_2x1_*` — so counting cover
per parcel is a string scan of the shipped `.umap`. Across 171 parcels, joined to their size class:

| size | lo-cover median | hi-cover median | cover per 100 m2 |
| --- | --- | --- | --- |
| Large | 8 | 4 | 0.93 |
| Medium | 7 | 3 | 1.54 |
| Small | 3 | 2 | 1.54 |

By plot type (cover per 100 m2): Shanty 2.70, SmallTown 2.16, Wilderness 1.54, Slums 0.77, CityCenter
0.73, Rooftops 0.62, Facility 0.00.

**The target band is 0.9–1.5 cover pieces per 100 m2, low cover about twice as common as high, and it
varies by plot type.** Cover is authored as small pieces with a 1x1 or 2x1 tile footprint.

## Where our boards stood, and where they are now

Measured with the same units (props with a low/high cover tier, per 100 m2 of board):

| | cover/100 m2 | low share |
| --- | --- | --- |
| before (tall pieces counted as cover) | 2.56–3.82, median 2.95 | **0%** |
| now (tall pieces are walls, dressing supplies cover) | 1.25–2.21, median 1.61 | 54% |
| reference | 0.93–1.54, median 1.54 | 67% |

Three corrections produced that:

1. **A piece taller than the climb-over height is a wall, not cover.** Counting every DoW2 wall as cover
   is what put our boards at 2.9 per 100 m2 with no low cover at all — cover everywhere and flanking
   everywhere.
2. **Cover is drawn from the kit of the board's own biome**, weighted two-to-one toward low pieces, because
   a parcel cut from a walled place carries no low cover of its own.
3. **The dressing target is the reference's density** (1.1 pieces per 100 m2), not a round number.

The remaining gap is the kit, not the code: our low share stops at 54% because some biomes' kits hold very
few low pieces. That is an asset task with a number attached.

## The answer to the question

**Yes — imitate the reference's layout grammar, and treat our geometry as styling.** Concretely:

1. **Plot first.** A board is a road network (PCPs) with parcel slots along it, not a lattice. We now have a
   first plot (one street with kerbs and entrances); the reference has 23 road types and turn types.
2. **Parcel size mix.** 18 m / 18x36 m / 36x36 m with medium dominant, and *most parcels need no
   authored entrance* — the plot provides the connections.
3. **Cover to the measured band** (0.9–1.5 per 100 m2, low-heavy, plot-typed), authored as small pieces
   rather than tall walls.
4. **The periphery is its own set** (the reference ships 90 definitions for it).
5. **Walls block line of sight; cover absorbs it.** This is the one the rules do not yet do: our tall props
   neither give cover (correct now) nor block sight (not yet implemented), so a wall is currently
   decoration between two open cells. That is the next gameplay task, and the reference's own quality
   criterion — line of sight — is the metric to hold it to.

What does *not* need to change: cutting authored places rather than generating geometry, the cover ladder
itself, the connectivity rule (every walkable cell reachable), and the one-board-everywhere plumbing.
