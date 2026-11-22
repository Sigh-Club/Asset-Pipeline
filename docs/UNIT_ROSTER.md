# Unit roster — what is playable, and why

The game is DoW2 art over XCOM mechanics: a small **infantry squad with faction roles, abilities and
promotions**, fighting PvE missions. Vehicles and monstrous creatures are **enemy heavies** — bosses and
elites the squad meets — never player units.

`tools/dow2/roster.json` carries the classification per unit:

| field | meaning |
|---|---|
| `class: infantry` | humanoid, 1.4–3.0 m, rigged with a full action set. **Player-eligible.** |
| `class: heavy` | vehicle, walker, drone or monstrous creature. **Enemy-only** (bosses/elites). |
| `player_eligible` | `true` only for infantry; the squad picker must read this, not a height guess. |

Measured split: **29 infantry, 16 heavy** (Chimera, Banewolf, Manticore, Baneblade, Sentinel, Wartrukk,
Battlewagon, Deff Dread, Dreadnought, Juggernaut, three Tau drones, Carnifex, Hive Tyrant, Night
Bringer).

## Scale is a gate, not a table

`tools/dow2/check_unit_scale.py` measures every shipped unit against its declared height and fails on a
mismatch beyond 0.25 m. It exists because the roster shipped wrong: measured 2026-11-21, 19 of 45 units
disagreed with their declared height by up to 2 m (a 1.50 m hormagaunt at 3.51 m, a 5.00 m Night Bringer
at 7.01 m). The cause was the scale step measuring an armature-deformed mesh's *undeformed* bounds, so
the factor was computed from the wrong height.

The fix is a closed loop on the artefact: apply the factor, export, measure **the exported file**, and
correct the residual until it matches — because Blender's own scene query and the exporter disagree
(measured on the hormagaunt: scene 1.500 m, export 3.508 m). All 45 units now pass at 45/45.

In a tabletop cover game the silhouette height *is* the tactical read, so a unit that ships at the wrong
height makes every cover decision wrong.

## Archetype leak, fixed

Deriving `player_archetypes` exposed the actual drift: three of the seven purchasable player squad
archetypes were modelled by vehicles.

| Player squad archetype | Was modelled by | Now |
|---|---|---|
| `pathfinder_scouts` (recon) | `ig_sentinel` — a walker | `ig_guardsman` (scoped line) |
| `aegis_artillery` (indirect fire) | `ig_manticore` — a tank | `ig_heavy_weapons` |
| `ashen_reavers` (elite melee) | `chaos_dreadnought` — a walker | `chaos_champion` |

The heavies keep their own identities instead (`sentinel`, `walker`, `tank_artillery`, `hellbrute`).
Two gates enforce it: `backend/internal/unitroster` fails if any `SquadArchetypeTemplates` key is not
player-eligible, and `frontend/src/data/__tests__/unitRoster.test.ts` fails if a heavy is marked
player-eligible or a squad archetype is missing from `player_archetypes`.

## Cover is a height, not a box

`stagedboard.CoverTierForHeight` and `frontend/src/three/coverTiers.ts` use the shipped ladder (XCOM's
own `Cover_LowCoverHeight` 0.64 m, `Cover_HighCoverHeight` 0.96 m, `Cover_MinClimbOverHeight` 1.6 m).
The previous rule read the *cover volume* the kit records per prop and used its y-extent as a height —
which is not the prop's height: measured, a 0.64 m sandbag pile carried a 2.32 m cover box (classified
heavy) and a 3.74 m wall an 0.86 m box (classified light). Staging now writes each board's derived
cover, the backend derives the same tiers, and the demo board reads them instead of hard-coding
`coverValue: 0` (measured on the live board: 72 cover cells, up from 15).

## Roles and promotions (player infantry)

`tools/dow2/unit_roles.json` gives every player-eligible infantry unit a faction, a role, a weapon and a
three-tier promotion ladder (ranks 1/3/5). The split across the 29 infantry:

| Role | Units | Ladder (rank 1 → 3 → 5) |
|---|---|---|
| Line trooper | 5 | rapid fire → brace overwatch → inspire volley |
| Squad leader | 5 | command → rallying cry → for the emperor |
| Gunner | 4 | suppressive barrage → kinetic brace → devastator round |
| Psyker | 4 | mind shock → warp surge grenade → synapse |
| Breacher | 3 | charge → rend → brutal |
| Duelist | 3 | backstab → blood cleave → tough as nails |
| Support | 3 | field repair → smoke grenade → guardian node |
| Marksman | 2 | stealth recon → target lock → long range |

`tools/dow2/check_unit_roles.py` gates it: every infantry unit has a role, every rank unlocks something,
ranks ascend from 1, no heavy carries a promotion ladder, and **every ability id exists in the backend's
own catalogue** (`internal/domain/ability_data.go`, 81 ids) — otherwise a promotion silently unlocks
nothing.

Not done yet: the promotion ladder is data, not wired into squad progression (the backend still resolves
stats through `TemplateForSquadArchetype`). Wiring it is the next step, and this table is what it reads.

## Cover placement: recorded, not yet changed

The tier now comes from the prop's real height (fixed). **Where** the tier lands is still the old
placement, and that is a known mismatch worth naming:

- the combat rules read cover from the eight cells *around* a unit (`coverNeighbours` in
  `combat_cover_exposure.go`, XCOM's own cover-point set) — a soldier stands beside a crate, not in it;
- our derivation puts the tier on the prop's own cell (plus a light ring), so a soldier beside a
  barricade is not seen as covered by the rules that decide flanking.

Measured cover density for each candidate placement, against the authored 24–36% band the composition
model recorded: prop cell + cardinals 12.6%, cardinals only 10.7%, eight neighbours 19.3%, own cell +
eight 22.5%.

A board-level harness now exists (`backend/internal/service/board_balance_test.go`): it plays a mission
across many mission ids — which land on different staged boards — and reports the outcome distribution.
On the committed placement that is **10 player victories, 2 enemy victories, 0 undecided, median 10
turns over 12 distinct boards**.

The rules-consistent placement was then tested properly, and the result is worth recording precisely:
it still passed the harness on eliminate-all missions, but failed the campaign ladder on **0 of 80
seeds**. The ladder's objective stages (defend, escort, sabotage) stall when cover is available
everywhere — the reference policy holds cover instead of pushing the objective. That is a **policy**
finding, not a cover-strength finding, so the placement change is parked until the reference policy
prioritises objectives; changing it now would be fitting the game to a thin test bot.
