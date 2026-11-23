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

## 3. What has to change in the pipeline

Ordered, each with the gate that proves it:

1. **Stop flattening the board.** The parcel emitter resamples the source heightfield into the board
   grid instead of writing zeros. Gate: for every parcel, the emitted heights match the source window
   within one elevation step, and the props seated on it do not float (measured: median |Δy| < 0.35 m
   between a prop's base and the cell height under it).
2. **Cover edges from shipped objects.** For each cover-bearing prop, derive its footprint, its facing
   normal from the recorded `basis`, and its `cover_type`; write the edges to the board. Gate: a shot
   from behind the prop gets the safety value, a shot from the side gets none, and a prop whose cover
   is disabled gives none.
3. **Layered nav.** Decode nav layers 1–4 into per-cell surface sets; render an upper layer only where
   it exists, with the cutaway rule. Gate: a unit on an upper surface is drawn above, a unit beneath it
   stays visible when the camera is over the upper surface.
4. **Craters.** Author them as relief + rim edges (a small tool over the grid). Gate: a unit in the
   crater centre takes the height penalty and the rim cover applies to the rim side only.
5. **Abilities read and write cover state.** Disable/enable cover, cover-based healing and damage
   buffs ride the existing ability bridge. Gate: a cover-disabling ability measurably removes the
   bonus for the rest of the turn.

### 3.1 Measured on the first emitted board, and the open question

The four `parcel_6p_whitewallsofcalderis_*` boards carry **39.5-40.0 m of relief** over 36 x 36 cells
(elevation steps -70 to +43), because the source place is a fortress cut into a canyon and the emitter
keeps the terrain as it is. Nothing is wrong with the number -- it is what the map holds -- but a
tactical board whose cover ladder reasons in 0.64/0.96/1.6 m cannot treat a 24 m drop as "cover": it is
a cliff, and line of sight across it is all-or-nothing.

So a **relief budget** is the next decision, and it has three defensible shapes: keep the real relief
(the board is the place, and the rules learn about cliffs), clamp the board to a playable band (a
tactical vignette, at the cost of the place's drama), or quantise the *gameplay* relief while the mesh
keeps the true height. The third is the one this document recommends, because it preserves both, and it
is the reason `heights` is written as elevation steps rather than metres.

## 4. Dead ends to not repeat

- **Do not derive cover from the prop's bounding box alone.** A wall's box covers both faces; the
  source's `is_cover_directional` and the recorded `basis` are what tell us which face is covered.
- **Do not sample the terrain at nav coordinates.** The terrain is centred on its own 800 m extent;
  sampling at nav coordinates measured a correlation of −0.06 against entity altitude, which reads as
  "the heightfield is unrelated to the ground" and is false.
- **Do not treat `nav.walkable` as 0/1.** Eight byte values exist in layer 0 alone.
- **Do not give a crater a cover *type* the source does not have.** The source has no crater cover; our
  crater is relief plus an edge, and calling it `tp_heavy` would be our word, not the game's.
