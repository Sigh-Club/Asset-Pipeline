# The board as a 3D grid: relief, cover, flanking

This note answers one question: **what does a shipped map actually encode about ground, height and
cover, and how do we turn that into a three-dimensional iso board whose combat rules match the
reference game's?** Every number below was measured from the corpus in this repository or read out of
the shipped attribute files; nothing here is inferred from how the game feels.

Sources of evidence:

- `output/source_lab/maps/*.json` — 57 decoded maps (terrain, nav, entities, props, placements).
- `attrib-decoded/` — the shipped entity blueprints, read as text.
- `docs/REFERENCE_SOURCE_REVIEW.md` — the reference game's own constants (cover tiers, angle-to-cover,
  height bonus).
- `docs/MAP_COMPOSITION.md`, `docs/BOARD_GRAMMAR.md` — what our board already does.

## 1. What the shipped maps encode

### 1.1 Ground relief is real and recoverable

`terrain` in a decoded map is a heightfield: `width`/`height` 800 m, `stride` 8 m, 101 × 101 samples,
`min_height` −0.88 m, `max_height` 60.19 m. The playable nav grid is 448 × 448 m — the core inside
that 800 m terrain, which is why a naive sampling at nav coordinates finds no correlation with where
props stand.

Measured on `6p_whitewallsofcalderis`, sampling the heightfield at each of the 3,532 placed entities:

| sampling convention | correlation with entity altitude | mean absolute error |
| --- | --- | --- |
| `(x + nav/2) / 8`, `(z + nav/2) / 8` | −0.058 | 10.8 m |
| `(z + nav/2) / 8`, `(x + nav/2) / 8` | −0.060 | 11.2 m |
| **`(x + 400) / 8`, `(z + 400) / 8`** | **+0.741** | **2.4 m** |
| `(z + 400) / 8`, `(x + 400) / 8` | +0.338 | 6.4 m |

So: the terrain is centred on the 800 m extent, entity altitude is the terrain height beneath it
(within the 8 m sampling error), and **a map's relief is shipped data, not an authoring problem**.
A board that renders flat is a board that threw this away — which is exactly what our parcel emitter
currently does (`heights: [[0] * gw ...]`).

### 1.2 The passability grid has five layers, and layer 0 is not a boolean

`nav.layers = 5`; the payload is `width × height × layers` bytes (448 × 448 × 5). Layer 0 of
`6p_whitewallsofcalderis` measures **eight distinct byte values** (0, 1, 3, 5, 7, 63, 128, 192) with
0 (72,682 cells) as the blocked value. The decoder's comment claiming "0 blocked and 1 walkable" is
wrong on the second half: 1, 3, 5 and 7 are all walkable and differ in flags we have not named yet.
Layers 1–4 are separate passability sets (layer 4's histogram is nearly identical to layer 0's).

Two consequences:

- `blocked_cells` (zero bytes) is trustworthy; "walkable" is not a single value.
- Multi-layer passability is the source of the vertical structure a 3D board needs (a ramp, an upper
  floor, a bridge deck). We currently read layer 0 only.

### 1.3 Cover is a typed, directional property of a placed object

The shipped blueprints declare cover through `obj_cover_ext`:

```
obj_cover_ext
{
  $REF = "entity_extensions\obj_cover_ext"
  cover_type = "tp_heavy"
  is_cover_directional = true
  is_obj_cover = true
  lengthwise_spots = true
  cover_disable_requirements { }
  cover_enable_requirements { }
}
```

Measured across `attrib-decoded/`:

| cover_type | occurrences |
| --- | --- |
| `tp_open` | 1,916 |
| `tp_light` | 1,590 |
| `tp_heavy` | 672 |
| `tp_garrison_cover` | 101 |
| `tp_energy_shield` | 7 |

744 world-object blueprints set `is_cover_directional = true`. The four gameplay proxies
(`cover_heavy_wall_proxy`, `cover_heavy_object_proxy`, `cover_light_wall_proxy`,
`cover_light_object_proxy`) are the pure cover pieces; real props (rocks, market stalls, facades)
declare cover themselves. `structure_ext` on a cover proxy sets `snap_to_terrain = true`, so a cover
object follows the ground it is placed on.

What cover *does* is defined per unit, not per object. A tactical sergeant's `cover_ext`:

| cover_type | safety_value | speed_multiplier |
| --- | --- | --- |
| `tp_energy_shield` | 0.50 | 1 |
| `tp_garrison_cover` | 0.40 | 1 |
| `tp_heavy` | 0.40 | 1 |
| `tp_light` | 0.25 | 1 |
| `tp_open` | −0.01 | 1 |

`safety_value` is a **hit-chance** term (how much of the incoming fire the cover absorbs), not a
damage multiplier, and it is per-unit — a unit can be better or worse at using the same cover. Because
`is_cover_directional` is set, that safety value applies only to fire arriving through the covered
face: the cover is a property of an *edge* with a facing, and walking around it removes the bonus.
`cover_disable_requirements` is how an ability (or destruction) switches the cover off.

Craters are **not** a cover type in the source: `nm_craters` is a ground splat layer, and crater
entities (`*_crater_nis`) are death/NIS decoration. "A crater is heavy cover" is therefore our design
choice, and it has to be authored as relief plus a cover edge rather than inherited.

## 2. The grid this implies

A board cell is 2 m × 2 m and carries:

| field | source | rule |
| --- | --- | --- |
| `height` | resampled terrain heightfield (bilinear 8 m → 2 m) | gameplay quantises to `ELEVATION_STEP` 0.35 m; the mesh renders the true height |
| `layers[]` | nav layers 1–4 | a cell may hold more than one walkable surface (ground, upper floor, bridge); the layer above fades when a unit stands under it |
| `cover_edges[4]` | shipped cover objects: footprint, `basis` normal, `cover_type` | an edge property with a facing — never a cell property |
| `cover_safety` | the unit's own `cover_table` | resolved per defender, not per cell |
| `relief` | terrain gradient | feeds the relative-height term the reference game uses |

Cover as an **edge with a normal** is the load-bearing decision. A cell-property cover model
("this cell is heavy cover") cannot express the source data: the same rock protects from the north and
not the south, and a unit standing beside it gets nothing. The reference game's own angle-to-cover
term (10–44° of approach, 50% maximum reduction, 11 tiles of range) is the same idea expressed as a
number, and `docs/REFERENCE_SOURCE_REVIEW.md` already records it.

### 2.1 What a shot resolves

1. The attacker's line to the target crosses one or more cell edges.
2. For each crossed edge that carries cover facing the attacker, look up the **defender's**
   `cover_safety` for that cover type.
3. Reduce hit chance by that value, scaled by the approach angle inside the covered arc (full value
   head-on, zero at the arc boundary) — the reference's 10–44° / 50% rule.
4. Add the relative-height term from `height(target) − height(attacker)`.
5. If the cover object was disabled (grenade, ability, destruction), its edges carry nothing.

Flanking therefore needs no special case: it is what happens when step 2 finds no edge facing the
attacker. That is how the source behaves, and it is the cheapest correct implementation.

### 2.2 Craters

A crater is authored as negative relief (a bowl of 1–2 cells at −1 elevation step) plus a cover edge
on the rim facing outward from the blast. This gives the two things a crater should give: a unit inside
is lower than the ground around it (height term against it, but protected from the rim side) and the
rim itself is cover for a unit standing behind it. It costs no new mechanic — it is relief plus an
edge, both of which the grid already carries.

## 3. What was built, and the decision behind each

All five items below are in the tree and gated. The order is the order they were built, and each entry
records the choice, the alternative that was rejected, and the check that holds it.

### 3.1 Relief: a parcel terrace, not the map's heightfield

**Choice** — a piece stands on a terrace of four elevation steps (1.4 m) and its ground, props and cover
move together; the terrace comes from the parcel's position, not from the terrain.
**Rejected** — writing the map's own heightfield into the grid. The terrain does not follow the surfaces
the pieces stand on (a building's floor is a prop, not ground), so it put the ground tens of metres above
or below the architecture: measured, 99 of 124 props hanging in the air when seated on the terrain, and
43 of 121 buried when the piece was seated on its own footing instead.
**Check** — the emitted board reports its elevation steps (0 and 4), and `--flat` writes a flat board.

Two defects surfaced on the way and are worth remembering, because both were silent: the terrace was
assigned before the parcel's paint existed, so the board came out flat *with the flag set*; and the
ground skirt sat at −0.06 m and cut a striped curtain through every raised terrace. A feature that is
"on" and does nothing is worse than one that is off.

### 3.2 Cover: directional by geometry, not by a per-cell tier

**Choice** — cover is resolved from the *cell the cover sits on relative to the target*. The rules take
the unit vector towards the cover cell and compare it with the vector towards the attacker: inside the
covered hemisphere the shot is into cover, outside it the shot flanks (`combat_cover_exposure.go`,
`FlankingAngle` 180). A cell tier alone cannot express "the same rock protects from the north and not
the south", but the geometry can, and it does so with the data a board already carries.
**Rejected** — a per-edge cover table in the board data. It duplicates what the position of the cover
cell already says, and the two could disagree.
**Check** — `TestAssessCoverExposure` (service) covers the model; `TestParcelBoardCoverIsDirectional`
(stagedboard) proves the *authored board* feeds it: a target with cover on one side only is protected
from that side and flanked from the other. The first version of that test failed for a good reason — a
dense board has cover on several sides, so walking round one piece puts you in front of another. The test
now looks for the geometry that makes a flank definable at all.

### 3.3 A second level: the source's own upper passability

**Choice** — the decoder now keeps every passability layer the map declares (measured: five on
`6p_whitewallsofcalderis`), and the emitter raises a cell that is blocked on the ground layer and walkable
above. That is a wall walk, a bridge or a raised terrace, and it is the only second level a board can have
without inventing one. The piece's props move up with the level.
**Rejected** — deriving upper floors from the props (a "roof" family). It would be our guess about which
pieces are floors, where the map states it directly.
**Check** — the emitted boards report their raised cells (measured: 463 across the catalogue) and
`TestParcelBoardCarriesLevelsAndCraters` fails if no parcel board carries a raised level.

### 3.4 Craters: negative relief plus a covered rim

**Choice** — a crater is a 2 × 2 bowl three steps (1.05 m) below the board with heavy cover on the cells
around it. It costs no new mechanic: the rules already read a lower cell as a height term and an adjacent
cover cell as directional cover, so a unit in the bowl is low and a unit behind the rim is covered.
**Rejected** — giving the crater a cover *type* of its own. The source has no crater cover type (its
`nm_craters` is a ground splat), so a new type would be our word for something the game already models.
**Check** — `TestParcelBoardCarriesLevelsAndCraters` fails if no parcel board carries a sunken cell, and
the emitter reports the count (measured: 20 sunken cells across the catalogue).

### 3.5 The board a player sees: density, dressing, band, contact

**Choice** — a 48 m board (2 × 2 parcels); the solver measures the largest prop-free square in the
playable middle and one kit name's share; the emitter dresses bare ground, the deployment zones and the
surrounding band from the *same map's own inventory* at 1:1.
**Rejected** — a 72 m board (3 × 3). Measured: 121 m² of bare middle against 0 m² at 48 m. A strategic
map's content density cannot fill 72 m, and the reference's tactical boards are ~40 m.
**Check** — the solver reports both measures per run; the catalogue ranks boards by density; the emitter
reports what it dressed and where.

Two wrong turns are recorded because they cost a session each: filling only the largest hole left the
deployment side empty (a player looks at that half first), and "the tallest piece to hand" for the band
put a 38 m domed building, a 20 m staircase and a hedge on the edge — three white domes on the board. The
band is now wall families only, and a white patch in a shipped atlas is capped by an albedo ceiling
rather than being mistaken for a missing texture (every GLB on that board had images).

## 4. Dead ends to not repeat

- **Do not derive cover from the prop's bounding box alone.** A wall's box covers both faces; the
  source's `is_cover_directional` and the recorded `basis` are what tell us which face is covered.
- **Do not sample the terrain at nav coordinates.** The terrain is centred on its own 800 m extent;
  sampling at nav coordinates measured a correlation of −0.06 against entity altitude, which reads as
  "the heightfield is unrelated to the ground" and is false.
- **Do not treat `nav.walkable` as 0/1.** Eight byte values exist in layer 0 alone.
- **Do not give a crater a cover *type* the source does not have.** The source has no crater cover; our
  crater is relief plus an edge, and calling it `tp_heavy` would be our word, not the game's.

## 4b. A plot generator in the reference's grammar

**Choice** — the product board is *generated* in the reference's layout grammar: a road network of
8-cell modules (straight, T, court), parcel lots filling the strips either side of it with alleys
between them, continuous building frontages along the lane, cover on the kerb line at the plot type's
measured density, and a paved lane drawn from the shipped decal kit. Tool:
`tools/dow2/generate_plot.py`. **Not rejected** — importing the reference's `.umap` geometry, or
continuing to cut parcels and hope a composition reads as a place.

**Because** — the reference's method is plot → road network → parcel slots → cover/LOS metrics, and we
had none of the first two: measured on the installed SDK, 172 parcel definitions and 443 PCP road
definitions, while our boards were a solver's selection of cuts on open ground. Cutting a good parcel
and placing it well are different problems; the plot layer is the one that makes a board a place.

**Check** — `generate_plot.py` self-reports and refuses on the invariants it can check:
- cover at the plot type's measured target ±2% (Facility 0.39 vs 0.40, CityCenter 0.72 vs 0.73,
  Shanty 2.69 vs 2.70 pieces/100 m², all seven types);
- `sealed 0` — every walkable cell reachable from the lane spine;
- deployment zones on the carriageway, asserted walkable before the file is written;
- longest sightline and long-sightline share reported per board (26 cells, 0.53 share on the 60 m
  plots);
- `frontend/src/three/__tests__/stagedLayouts.test.ts` gates each plot board to its own type's cover
  target within a quarter and to the corpus dispersion band (0.8–2.2);
- `backend/internal/stagedboard` gates every authored board to "no unreachable ground" from its own
  landing zone (22 boards).

**The finding that mattered most: a parcel is a building, and we had none.**

Measured on our own boards, the two ways we were getting it wrong were exact opposites: a plot board was
**77% impassable** — solid lots with a facade pasted on the street side, so the playable space was a thin
lane and no building could be entered — and a cut parcel board was **0% impassable**, a plane with props
on it. Neither is a place. The reference's parcels are enterable: their packages carry interior lights
(`PointLightMovable`, 159 in one CityCenter parcel), blocking volumes and breachable walls
(`ALN_WallDestro`), and their cover pieces are authored inside as well as out.

What a plot board is now: each lot is a **shell** — perimeter cells are walls, the interior is floor, a
door is carved on the street side and a second on the back — with a varied depth (10-22 m), a lot type
(building, walled yard, ruin with breaches), party walls so the frontage is continuous, and walls at
4-7 m for most buildings so the room reads from the tactical camera, with a few 8-14 m pieces for
skyline. Ground is differentiated: paved lane, floor inside, yard dirt in the yards. Measured after:
41% impassable, 47-50 wall modules from 12 distinct kit pieces, 91-117 decals, cover still on the plot
type's target, and `TestParcelBoardCarriesAuthoredPlacements`-style gates extended with a structural one
(`builds its parcels as buildings a squad can walk into`: interior ≥ 75% walkable, perimeter ≥ 60% wall,
for every lot on every plot board).

**Measured, and what it cost to learn:**
- A parcel taller than two storeys is what a street is made of; the first attempt used 2 m wall runs
  and produced a fence around a field, and the second used the arena kit's 40 m platform and produced
  one machine instead of a street. Frontages are now architecture-family pieces, 5–14 m tall, laid
  edge to edge by best fit.
- Cover has to *read*: a piece with a footprint, from the kit's cover family or a crate/barrier name.
  Pale wedges placed as cover looked like markers.
- The lane needs a surface: the decal layer was built only on a ground rebuild, so it landed after the
  board's second build and was discarded — the paved lane never drew until the layer was keyed on the
  decals themselves.

## 5. What is still open

Recorded so the next session does not re-derive it:

- **The upper level is carried in the grid but not visually distinguished.** A raised cell is ground at
  1.4 m; the renderer draws it as ground, not as a walkway with an underside. The data is there
  (`heights > 0`); the cutaway rule is not.
- **A crater's rim is cover by cell, not by edge.** The rules make it directional through the geometry
  (3.2), which is the same thing from the player's side, but the board does not record *which* face of
  the rim is protected, so a crater cannot be authored with an open side.
- **The map's own heightfield is measured and discarded.** It correlates +0.741 with where the map's
  entities stand, and a board does not use it; a mesh that can carry a true heightfield would let the
  board keep the place's real relief instead of a parcel terrace.
- **The reference's own parts are importable now, and only nine of them are in.** `tools/xcom2/import_pieces.py`
  exports a shipped piece with UE Viewer, relinks its DIF albedo in Blender and writes a GLB with the
  reference's cover class and footprint (from its own file names). What is imported is street furniture; the
  buildings and roads are the mass that is still ours.
- **A reference plot's *plan* is not extracted yet.** We reproduce its grammar and its measured numbers,
  but not one of its actual layouts. The SDK ships 122 plots whose module names carry their own
  dimensions (`ARC_CTY_Blvd_Str_16x08`, `ARC_CTY_Blvd_Crn_16x16`, `ARC_24_Periphery_Commercial`), so the
  plan is there to copy; `read_umap.py` parses names and imports but not the SDK package's export table
  (table at 14800, header says 14916; no properties read), which is the blocker.
- **Cover density is ours, not the source's.** Dressing fills bare ground from the map's own kit; the
  count per board (measured 5–48 pieces) is a board decision, not a shipped number.
