# Unit kit methodology — authoring IoA units instead of importing them

> Status: **adopted 2026-11-17**, implementation not started. Supersedes "import a shipped mesh and
> recolour it" as the unit route. Owner: asset pipeline. Related: `CHARACTER_PIPELINE.md` (rig and
> certification standard), `Imperium-of-Ash/docs/game-design/FACTION_IDENTITY.md` (design authority).

## 1. Why this exists

The first pass of faction models imported whole DoW2 meshes and changed the palette. They animate
and certify, but they read as copy-and-paste: the silhouette, the part breakdown and the detail
language are still Relic's. `FACTION_IDENTITY.md` rule 4 already forbids that ("copied names,
symbols and model silhouettes are not [welcome]"). We learned *what* the source models look like,
not *how* they were built.

This document records how they were built, measured from the extracted art we have on disk, and the
route we will use to build our own.

## 2. What the reference games actually do (measured)

Counted from `Projects/Decompilor/work/dow2-retribution/sga` with `tools/dow2/chunky_mesh.py`:

| Faction | `.model` files | tier-tagged variants | armour parts | heads | packs | weapons |
|---|---|---|---|---|---|---|
| Space Marines | 368 | 71 | 31 | 19 | 8 | 13 guns / 15 swords |
| Chaos | 163 | 64 | 2 | 13 | 9 | 4 guns / 9 swords |
| Eldar | 146 | 60 | 38 | 29 | — | 1 gun / 7 swords |
| Tyranid | 115 | 54 | 41 (chitin/body) | — | — | 9 claws |
| Imperial Guard | 232 | 29 | 24 | 4 | — | 26 guns |

Per-part triangle budgets (marine parts, sorted):

| Slot | parts | min | median | max |
|---|---|---|---|---|
| armour | 31 | 32 | 2,486 | 5,590 |
| head | 19 | 222 | 948 | 2,248 |
| backpack | 8 | 254 | 308 | 910 |
| gun | 13 | 136 | 190 | 432 |
| sword | 15 | 125 | 264 | 569 |

Conclusions that drive our route:

1. **A unit is a kit, not a mesh.** ~10 unit identities are assembled from ~90 parts, and the same
   part reappears across units.
2. **Gear has a tier ladder** (`_common`, `_rare`, `_epic`, `_glow`): the same silhouette re-detailed
   per tier. This maps directly onto our R0–R7 promotion ladder.
3. **Budgets are per slot, not per unit.** The detail is spent where the player looks (armour, head);
   weapons and packs are cheap.
4. **Parts attach at markers** (`DATAMRKS`): gear swaps are data, not new meshes.
5. **Materials are per draw call**, declared once per model and referenced by name.

XCOM reaches the same place from the other direction: a modular soldier assembled from body parts,
materials and decals. The industry term for the concept is kitbashing; the discipline that keeps it
readable is silhouette-first design ("fill it black" readability).

## 3. What we will build instead

**Derive and reshape.** Take a reference part, then run a fixed set of operations that make it ours.
Every operation is recorded and repeatable; none is an eyeball tweak.

| Operation | Purpose | Example |
|---|---|---|
| `proportion` | move the part into the IoA body-class proportions | Corsair limbs +12% length, −18% mass |
| `silhouette` | change the outline, not the surface | Directorate pennant rack, Cinder asymmetric plate, Corsair swept fin |
| `strip` | remove 40K iconography | aquilas, skulls, purity seals, gothic arches |
| `add` | apply IoA vocabulary | rails, vents, brands, spore bulbs, hard-light edges |
| `respec` | material and palette per faction | rust-orange scrap vs pale hard-light |

The output must be **measurably different from the source**, not merely recoloured.

### Body classes (directive 2026-11-17)

95% of units are **human scale**. Only the highest tier — the units with the most HP, the most armour
and the best weapons — use the super-human frame.

| Body class | Height | Used by |
|---|---|---|
| human | 1.75–1.90 m | the mass of every faction: line troops, specialists, support, most commanders |
| elite | 2.05–2.20 m | one or two units per faction at the top of the ladder |
| corsair | 1.90–2.00 m, slim | Void Corsairs (long limbs, low mass) |
| bulk | 2.10–2.40 m, wide | Wreckstorm heavy units |
| bloom | varies, organic | Parasitic Bloom creatures |

Assignment is per **unit**, never per faction. The Iron Directorate's line infantry is human; only
its highest-HP/armour/weapon unit is elite-scale.

## 4. Faction part language

The silhouette rules from `FACTION_IDENTITY.md`, made concrete enough to model against:

| Faction | Silhouette idea | Part vocabulary to add | To strip | Palette |
|---|---|---|---|---|
| Iron Directorate | upright ranks, pennants, industrial | rail/laser barrels, drum magazines, pennant racks, drone packs, plate seams | gothic arches, purity seals | gold/blue industrial |
| Sons of Cinder | asymmetric branded plates, smoke | brands, brazier packs, chain/ember weapons, warped plate edges, ash vents | aquilas, clean edges | cinder grey + purple/pink witchfire |
| Void Corsairs | swept fins, hard-light | swept fin crests, hard-light blades, smooth curved plates, holo-projectors | bulk, rivets, heavy boots | pale hull + cyan |
| Wreckstorm Clans | stacked scrap, ram-shapes | bolted plates, ram prows, exposed pistons, welded scrap, loud barrels | symmetry, clean seams | rust orange + soot |
| Parasitic Bloom | bulbed organic curves | spore bulbs, thorn limbs, coral-bone ridges, membrane | all metal, hard edges | coral bone + spore green |
| Radiant Concord | perfect geometry | chrome planes, drone pods, targeting arrays | grime, asymmetry | white chrome + cyan |
| Chrono Revenants | monolith slabs | slab plates, gauss rods, stasis rings | organic curves | green-black |

## 5. The plan

Each phase ends in a check. A phase is not done until the check passes.

**P0 — Design specs as data.** Encode the table above plus proportions and per-slot budgets as
machine-readable rules. *Check:* every faction has silhouette, proportions, vocabulary, strip list,
palette; no two factions share a silhouette descriptor.

**P1 — Part taxonomy.** Catalogue the reference parts per race with measurements, and map every unit
in `UNIT_ROSTER.md` to a body class + part list. *Check:* no unit without a body class; every part
has a measured budget.

**P2 — Derivation toolkit.** Implement the five operations against a part, with the operation list
recorded per part. *Check:* a part can be re-derived from its source reproducibly.

**P3 — Author the IoA part library**, faction by faction, starting with Iron Directorate (human line,
then the elite), then Sons of Cinder, then Void Corsairs. Extract `race_ork` first — it is not in the
extracted tree yet. *Check:* per-slot budgets met (armour ≤2,500, head ≤1,000, pack ≤300,
weapon ≤500 tris).

**P4 — Kit assembler and unit definitions.** Units become data: parts + sockets + palette + body
class + tier. *Check:* every roster unit assembles from the library with no unique mesh.

**P5 — Rig per body class**, parts bound rigidly to sockets. *Check:* `audit_rig.py` passes for every
assembled unit.

**P6 — Certification, including distinctiveness.** Existing gates plus:
- silhouette IoU against the source part **< 0.75** in the 8-direction masks;
- silhouette-only faction classification (the black shape must be attributable);
- kit completeness (every required slot present) and per-slot budget.

**P7 — Rollout:** Iron Directorate line → Iron Directorate elite → Sons of Cinder → Void Corsairs →
Wreckstorm (after ork extraction) → Parasitic Bloom.

## 6. Decisions

- **Choice:** the line trooper carries the **pennant rack** and not the drone pack. **Rejected:**
  both on one unit (464 tris in a 300 budget) and neither (loses the faction's upright-ranks read).
  **Because:** the pack slot budget is the constraint that forces a per-unit choice, which is the
  point of a part library — vocabulary is a menu, not a checklist. **Check:** `--report` pack slot
  ≤300. **Revisit when:** the pack budget is revised with a measured argument.
- **Choice:** the rail weapon is its own lean part list. **Rejected:** decorating the generic rifle.
  **Because:** the generic rifle alone measured 576 tris against a 500 budget; a variant built on top
  of it cannot fit. **Check:** `--report` weapon slot ≤500. **Revisit when:** the weapon budget is
  raised by a measurement.
- **Choice:** flat per-faction colours for the three large-coverage slots. **Rejected:** the textured
  per-faction library materials. **Because:** at the 2 cm texel grid on curved organic surfaces they
  palette-lock to a static speckle; the flat colour is what makes the armour plates read. **Check:**
  the 8-direction palette-lock frames (off-palette 0) plus a human look at the contact sheet.
  **Revisit when:** the texel grid is fine enough for the woven textures to resolve.

- **Choice:** derive-and-reshape kits. **Rejected:** importing whole meshes (copy-paste, no part
  vocabulary); from-scratch sculpting (months before the first unit, kept as a later upgrade for hero
  units). **Because:** the reference games are kits; derivation keeps the anatomy and rig quality
  while the silhouette edits make the design ours. **Check:** silhouette IoU < 0.75 and faction
  classification on the masks. **Revisit when:** a faction's silhouette cannot be reached by
  reshaping (then sculpt that faction's body class from scratch).
- **Choice:** human-scale for 95% of units; elite frame only for the top HP/armour/weapon tier.
  **Rejected:** elite scale for whole factions. **Because:** the user directive of 2026-11-17; scale
  is a rank signal, not a faction signal. **Check:** roster audit — count of elite-scale units per
  faction ≤ 2 and only at the top of the ladder.
- **Choice:** per-slot triangle budgets from the measured DoW2 parts. **Rejected:** a single unit
  budget. **Because:** budgets spent per slot keep the silhouette detail where it reads.
  **Check:** the per-slot table in P3.

## 7. Current status (2026-11-17, implementation started)

**P0 — done.** `configs/factions/*.json` for all seven factions: silhouette and shape words,
proportion bands, body classes, the elite rule, add/strip vocabulary, palette ramps and per-slot
budgets.

**P1 — done.** `tools/dow2/part_catalogue.py` measures the extracted library into
`output/part_catalogue.json`: marine armour 31 / head 19 / pack 8 / gun 13 / sword 15; chaos 2 / 13 /
9 / 4 / 9; eldar 38 / 29; tyranid 41 / claws 9; guard 24 / head 4 / gun 26. Orks are still not
extracted (0 models) — required before Wreckstorm.

**P3 — Iron Directorate line trooper done (2026-11-19).** The kit vocabulary in the faction spec
(`add` list) is now authored geometry, measured per slot:

| Slot | Measured | Budget | Verdict |
|---|---|---|---|
| armour (pauldrons, apron plates, seams, insignia) | 1,257 | 2,500 | PASS |
| head (helm, visor, crest, breather, neck ring) | 280 | 1,000 | PASS |
| pack (mount + 2-pole pennant rack) | 152 | 300 | PASS |
| weapon (rail emitter, drum magazine, rails, fins) | 488 | 500 | PASS |

- `tools/blender/base_unit_build.py` gained the vocabulary behind flags: `--weapon rail_rifle`
  (own lean part list — the generic rifle alone measured **576**, over the 500 budget, so decorating
  it was never going to fit), `--pennants` (the rack replaces the bulky pack contents; a standard
  bearer carries the rack, not a rucksack), `--seams` (inset plate seams + the industrial apron), and
  `--back drone` (a lean drone pack, 2 micro-drones, in the library for specialist variants).
- `--report` is the P3 check: it classifies every authored object into its slot and prints measured
  tris against `configs/factions/<faction>.json` budgets, largest offenders included. It is the gate
  that caught the generic rifle's pre-existing overspend.
- **Palette defect found and fixed while shipping.** The faction-agnostic material map baked
  `armour_primary` to the library's blue-grey `flat_armour_primary`, so a Directorate trooper shipped
  blue while every gate passed (off-palette 0). `tools/add_flat_faction_materials.py` derives
  `IOA_flat_<faction>_<slot>` from the faction spec's own palette, and
  `configs/materials/base_unit_material_map_iron_directorate.json` maps the three large-coverage slots
  to it. Trap recorded: a copied material has no users and Blender **drops it on save** — the first run
  printed the colours and saved nothing until `use_fake_user` was set.
- Shipped as `iron_directorate_ig_human_pixel.glb` (line infantry), `UNIT_ASSET_REV 20261119`:
  512² atlas, 41-45 colours per frame, off-palette 0, 8 directions with one connected component each,
  GLB contract pass, guards 61/61 + 61/61 + 0, Jest 628/628, E2E 6/6. Verified in-engine (screenshot:
  gold armour, pennant rack, rail weapon, AMMO 8/8 dock readout).
- Next in P3: the Directorate elite (elite frame), then Sons of Cinder, then Void Corsairs. Extract
  `race_ork` before any Wreckstorm work.

**P2 — started.** `tools/blender/derive_head.py` implements the first derivation: strip the source
head above the neck line, then add our vocabulary (dome, visor, crest, breather, neck ring) in the
body's own contract material slot. Derived `ig_human_v2` runs the full chain — rig (35 bones),
9 clips, `audit_rig` PASS, pixel pipeline OK.

**Measured result, and the honest reading:** the head-only derivation gives a mean silhouette IoU of
**0.95** against the source base (8 views, like-for-like unposed). A head is roughly 5% of a
silhouette, so this is expected — it proves the loop, not the distinctiveness. Reaching the < 0.75
target needs the torso, pauldrons, coat/limb mass and the weapon changed as well, which is P3.

**Visual gate — built.** `tools/visual_check.py` renders 8 views, measures coverage, components and
largest-piece fraction, compares against a `--source` with per-view IoU, and writes a contact sheet
for human review. It is the check that would have caught the rigged-building and the jumbled-mesh
defects that every numeric gate passed.

Two measurement caveats recorded for P6:
1. IoU must compare **like-for-like poses** (base vs base). Comparing a posed pixel asset against an
   unposed base produced a misleading 0.74 for the same head-only change.
2. A multi-material asset needs per-primitive index offsets in any geometry metric; a shared vertex
   array produced a false 1.48 m edge until the check was fixed.
