#!/usr/bin/env python3
"""emit_unit_roster.py — publish the unit classification the game reads.

`roster.json` is the pipeline's own record (which DoW2 model maps to which archetype). The game needs
one thing from it: which units a player squad may field. That is `class: infantry` — vehicles, walkers,
drones and monstrous creatures are enemy heavies only (decision 2026-11-21, docs/UNIT_ROSTER.md).

This writes the game-side asset so the squad picker reads the decision instead of guessing from a name
or a height.

Usage:
    python3 tools/dow2/emit_unit_roster.py --out ../Imperium-of-Ash/frontend/public/assets/units
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roster", type=Path, default=ROOT / "tools/dow2/roster.json")
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/units")
    a = ap.parse_args(argv)

    roster = json.loads(a.roster.read_text())
    units = {}
    for unit, spec in sorted(roster.items()):
        klass = spec.get("class")
        if klass not in {"infantry", "heavy"}:
            raise SystemExit(f"{unit}: no class recorded (infantry|heavy)")
        units[unit] = {
            "class": klass,
            "player_eligible": bool(spec.get("player_eligible")),
            "faction": spec.get("faction", ""),
            "archetypes": spec.get("archetypes", []),
        }
    # an archetype is player-eligible only when every unit carrying it is infantry: one heavy on an
    # archetype makes that archetype a heavy archetype
    by_archetype: dict[str, bool] = {}
    for unit in units.values():
        for archetype in unit["archetypes"]:
            by_archetype[archetype] = by_archetype.get(archetype, True) and unit["player_eligible"]

    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / "unit_roster.json"
    dest.write_text(json.dumps({
        "generated_by": "asset-pipeline/tools/dow2/emit_unit_roster.py",
        "note": ("Player squads field infantry only (docs/UNIT_ROSTER.md). Vehicles, walkers, drones and "
                 "monstrous creatures are enemy heavies: bosses and elites the squad meets, never player "
                 "units. `player_archetypes` is derived, not authored: an archetype is player-eligible "
                 "only when every unit carrying it is infantry."),
        "units": units,
        "player_archetypes": sorted(k for k, v in by_archetype.items() if v),
        "heavy_archetypes": sorted(k for k, v in by_archetype.items() if not v),
    }, indent=1) + "\n")
    infantry = sum(1 for u in units.values() if u["player_eligible"])
    print(f"{len(units)} units -> {dest} ({infantry} player-eligible infantry, "
          f"{len(units) - infantry} heavy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
