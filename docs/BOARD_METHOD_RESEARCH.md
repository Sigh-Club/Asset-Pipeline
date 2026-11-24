# How tactical boards are actually built — research before the next step

The question this answers: **is cutting parcels out of shipped maps and assembling them with a solver the
right method for this kind of game, or are we inventing a method that fights the genre?** The answer is
below, with sources, and it is not a comfortable one: the method is right in its parts and missing the
part that makes the reference work.

## Sources

- **Primary — Firaxis, GDC 2018, "Plot and Parcel: Procedural Level Design in XCOM 2"** (Brian Hess, Lead
  Level Designer), slides:
  `https://media.gdcvault.com/gdc2018/presentations/Hess_Brian_PlotAndParcel.pdf`. Read directly, not
  summarised by a third party.
- **Primary — Splash Damage, Gears Tactics level design** (Sean Noonan, Lead Level Designer), portfolio
  write-up: `https://noonan.design/portfolio/gears-tactics/`.
- **Our own reading of the shipped reference data** — `docs/REFERENCE_SOURCE_REVIEW.md` (parcel/PCP/plot
  structs, cover tiers, budgets), and the XCOM 2 SDK config and content counts already recorded there.

## What the reference actually builds

From the GDC slides, in their own terms:

- "Components of an XCOM Level: **The Grid. Cover. Fog of War.**"
- "What makes a good XCOM level? **Object Spacing. Cover Density. Line of Sight.**"
- The system is **plots + parcels + PCPs**:
  - a **plot** is a master layout map that defines where buildings go and how the map reads;
  - **parcels** are streamed-in buildings, bucketed by size — **small 12x12, medium 12x24, large 24x24
    tiles** (at the shipped 1.5 m step: 18 m, 18x36 m, 36x36 m), with **facings**, **driveways** and
    **zones**;
  - **PCPs (Plot Cover Parcels)** are **road networks converted into sets**, each piece with multiple
    variants chosen on load.
- **Biome is an asset swap, not a different layout**: "all outdoor maps created as temperate; assets and
  materials would swap if map loaded into arid or tundra".
- Stated costs of the method: "limited artistic agency", "cinematic unpredictability", "decreased
  opportunities for visual storytelling".
- Shipped scale: **80 plots, 200+ parcels, 450 PCPs**.

From Gears Tactics (a different studio, same genre):

- Level production is driven by **metrics** defined early and used to guide the whole team.
- A level is a **sequence of beats with themes** — "close quarters, long range, rush" — created through
  architecture, enemy placement and a curated archetype mix.
- **Verticality is deliberate**: vantage points for the player's sniper, commanding positions for enemy
  archetypes.
- **Pacing**: "guitar strings" — downtime between encounters to regroup.
- **"Remix maps"** exist specifically to test the semi-procedural system.
- And the one that matters most for us: with an **elevated camera, multiple overlapping floors should
  generally be discouraged**.

## What we do that matches

- **Parcels are real geometry**, cut from shipped places rather than generated — the same principle as
  streamed-in parcel buildings.
- **Cover is a height on the shipped ladder** and is measured, not painted: the reference's own
  "cover density" criterion is something we can compute.
- **Object spacing** is measured and repaired into a corpus band (`docs/MAP_COMPOSITION.md`).
- **Biome comes from the source map's own kit**, which is the reference's asset-swap idea in its cheapest
  form: one layout family per place, and the place is the map.
- **Boards are assembled by a solver with constraints** (seam legality, reachability, bare-middle and
  module-dominance measures), which is the "parcel slots" idea without the plot.

## Where we diverge — and this is the flaw the review felt

1. **We have no plot.** The reference's plot is an *authored master layout*: it decides where the road
   runs, where the buildings sit, where the open lanes are, and which mission fits. We assemble parcels
   into a bare lattice and hope the pieces make a place. That is why a board reads as "a flat plane with
   one asset": a lattice has no road, no lane, no beat — the things a plot exists to provide.
2. **We have no PCP layer.** Roads are what make a tactical map legible: they are the lanes, the long
   sightlines, the reason cover sits where it sits. The reference converts road networks into variant
   sets. We have nothing that draws a road.
3. **We do not measure line of sight.** The reference names it as one of three quality criteria; we
   measure density and spacing only. A board can pass every gate we have and still have no interesting
   sightlines.
4. **Parcel size mix.** The reference buckets 18 m / 18x36 m / 36x36 m and gives plots slots for each. We
   cut 24 m squares and one 72 m arena. The mix is what produces the variety of enclosure the reference
   relies on.
5. **Verticality.** Our raised level came from the source's upper passability and produced "a raised
   plate with no way down" — exactly the failure the Gears Tactics lead warns about for an elevated
   camera. Flat boards until the camera and the movement rules can carry a step is the right call, and it
   is now recorded in `docs/BOARD_3D_GRID.md`.

## Verdict

**The method is not wrong; it is incomplete in the one place that matters.** Cutting authored places and
assembling them is what the reference does. What the reference has and we lack is the **plot**: an
authored structure that says "here is the road, here are the lanes, here is where the buildings go, here
is what this place is for". Without it, a solver can only make a well-spaced lattice.

## What to do next, in order, each with a check

1. **Author a plot layer.** For each source map, derive a plot from its own road network: the map's
   ground splats already include `nm_roads` (`docs/REFERENCE_SOURCE_REVIEW.md` records the ground layer
   names). A plot = road polyline + parcel slots along it + the open lanes it creates.
   *Check*: every board has at least one road segment crossing it, and every parcel slot touches a road
   or a lane.
2. **Draw the PCP layer.** Convert those roads into a small set of tiles with variants (the reference's
   method), placed as authored props at 1:1.
   *Check*: the road is continuous across parcel seams (no gap where two parcels meet).
3. **Add a line-of-sight metric** to the solver, alongside density and spacing: the longest unbroken
   sightline on the board, and the share of cells with a sightline longer than a weapon's range.
   *Check*: the board reports both, and a board with no long sightline and no short one is rejected.
4. **Parcel size mix**: allow 18 m and 36 m pieces in the same board with a plot that has slots for them.
   *Check*: a board reports its size mix, and the solver places at least two sizes.
5. **Then** revisit verticality with ramps, once the camera and movement rules support a step.

## What this does not change

The authored-parcel direction, the cover model, the relief/terrace decision, the density and spacing
measures, and the one-board-everywhere plumbing all stand. The research confirms the parts and names the
missing one.
