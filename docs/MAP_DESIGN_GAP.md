# What we are doing wrong, and what we have to get right

Written after measuring the reference's own shipped data (`docs/XCOM2_MEASURED_GRAMMAR.md`) and reading the
two design accounts (`docs/BOARD_METHOD_RESEARCH.md`). No claim below is from memory; each carries the
number or the source that produced it.

## The seven things we are doing wrong

### 1. We have no plot, and the plot is the whole method

The reference generates a **plot** — an authored master layout with a road network, parcel slots, lanes and
the mission it is for — and streams parcels into it. We assemble parcels into a bare lattice and hope.

Evidence: 443 PCP definitions with 23 road types and turn types (Straight 134, Corner 22, Intersection 20,
T 20, Court 14) on 8-tile modules; 90 of them are a dedicated **Periphery** set. The GDC talk describes the
plot as the master layout map. A lattice has no road, no lane and no beat, which is exactly why a board
reads as a paved plane with buildings dropped on it.

### 2. Our parcel size is wrong, and we use only one

Reference parcels: **Small 55, Medium 81, Large 36** at **18×18 m, 18×36 m, 36×36 m**. Medium dominates.
Our boards are 48×48 m — **twice the area of the reference's largest parcel** — assembled from one size.

### 3. We invented an entrance rule the reference does not have

**105 of 172 parcels declare no entrance at all** (`bHasEntranceN1`…). They are solid blocks; the plot
connects them. Our catalogue required openings on two or more sides to call a cut usable, which discarded
88% of the cuts (22,015 → 2,651) and biased every board toward pieces that happen to be open on two sides —
courtyards, not buildings.

### 4. We were counting walls as cover

Measured on our boards: **2.95 cover pieces per 100 m², 0% of them low**. Reference: **0.93–1.54 per
100 m², low about twice high**, authored as small `*_LoCover_1x1_*` / `*_HiCover_2x1_*` pieces. Counting a
20 m wall as cover gives cover everywhere, flanking everywhere, and no low cover to crouch behind.

### 5. We have no line of sight model at all

The reference names **line of sight** as one of three things that make a good tactical level. In our rules a
tall prop neither gives cover (correct now) nor blocks sight (not implemented), so a wall is decoration
between two open cells. Every sightline on our boards is unobstructed except by impassable cells.

### 6. Our biome is welded to the layout

The reference builds **one layout per plot type and swaps assets for the biome** ("all outdoor maps created
as temperate; assets and materials would swap if map loaded into arid or tundra"). We tie the layout to the
source map, so variety means authoring a new layout per map — backwards, and it is why the demo can only
rotate between maps rather than between plot types × biomes.

### 7. Our board is bigger than the camera and the content can carry

The reference's parcels are at most 36 m and its tactical camera is elevated; Gears Tactics' level designer
is explicit that with an elevated camera overlapping floors should be discouraged. We build 48 m boards,
fill them with 20 m walls, and then measure a 100 m² bare middle — the board is simply larger than the
density of authored content that can be placed on it.

## What we have to get right

1. **Plot first, parcels second.** Generate the plot: a road network from the PCP grammar (straight, corner,
   T, intersection, court on 8-tile modules), parcel slots along it, a periphery set, and lanes that give the
   board its sightlines. Then place parcels — mixed sizes — into the slots.
2. **Cover to the measured band, placed where it belongs.** 0.9–1.5 pieces per 100 m², low:high 2:1, as
   small pieces (1×1, 2×1) at lane edges and building faces — not scattered, and never a tall wall counted as
   cover.
3. **Line of sight as a rule and a metric.** Walls block sight, cover absorbs fire, and every board reports
   its sightline distribution: longest unbroken line, and the share of cells that can see more than one
   weapon range.
4. **Entrances come from the plot.** A parcel is a block; the plot's lanes and doors connect it.
5. **Biome by asset swap.** One layout per plot type, three biome skins. Eight plot types × three biomes is
   twenty-four places from eight layouts — which is how the reference ships eighty plots and four hundred
   and fifty road pieces without four hundred and fifty layouts.
6. **Board size to the content.** A board is one to four parcels (18–36 m each), not a 48 m lattice. The
   reference's own parcels prove that is where the density lands in band.

## The order to build it, with the gate that proves each step

| step | what | gate (measured, not judged) |
| --- | --- | --- |
| P1 | plot generator: road network + slots + periphery from the PCP grammar | every board has a continuous road across it, every slot touches a road or a lane, periphery present |
| P2 | parcel size mix (18 / 18×36 / 36×36 m) into the plot's slots | the board reports at least two sizes and no parcel exceeds 36 m |
| P3 | cover placement at the measured density and ratio, at lane and wall edges | 0.9–1.5 pieces per 100 m², low share ≥ 60%, measured on the emitted board |
| P4 | line of sight: walls block, cover absorbs; the metric on every board | longest sightline and long-sightline share reported; a board with no sightline over one weapon range is rejected |
| P5 | biome by asset swap: one layout, three skins | the same plot renders in three biomes with identical geometry |
| P6 | retire our invented constraints (two-sided entrances, single size) | the catalogue's usable set grows by an order of magnitude and the solver still solves |

## What not to change

Cutting authored places rather than generating geometry stands — it is what the reference does with parcels.
The cover ladder, the connectivity rule (every walkable cell reachable), the flat board (no ramps yet) and
the one-board-everywhere plumbing all stand. What is missing is the *structure between* the pieces: the plot.
