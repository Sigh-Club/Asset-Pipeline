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
