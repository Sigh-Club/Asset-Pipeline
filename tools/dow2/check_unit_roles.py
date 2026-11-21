#!/usr/bin/env python3
"""check_unit_roles.py — every infantry unit has a role, and every ability it unlocks exists.

The role table is authored (which faction fields which role is a design decision), but the ability ids
are not: they must exist in the backend's own catalogue (`internal/domain/ability_data.go`), or a
promotion silently unlocks nothing. This gate also refuses a heavy in the role table — vehicles and
monsters are enemy heavies and have no promotion ladder.

Usage:
    python3 tools/dow2/check_unit_roles.py
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ability_ids(game_root: Path) -> set[str]:
    source = (game_root / "backend/internal/domain/ability_data.go").read_text()
    return set(re.findall(r'^\s*"([a-z0-9_]+)":\s*\{', source, re.M))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roles", type=Path, default=ROOT / "tools/dow2/unit_roles.json")
    ap.add_argument("--roster", type=Path, default=ROOT / "tools/dow2/roster.json")
    ap.add_argument("--game", type=Path, default=ROOT.parent / "Imperium-of-Ash")
    a = ap.parse_args(argv)

    roles = json.loads(a.roles.read_text())["roles"]
    roster = json.loads(a.roster.read_text())
    known = ability_ids(a.game)

    failures = []
    for unit, spec in sorted(roles.items()):
        entry = roster.get(unit)
        if not entry:
            failures.append(f"{unit}: not in the roster")
            continue
        if entry.get("class") != "infantry":
            failures.append(f"{unit}: has a promotion ladder but is class={entry.get('class')}")
        if not spec.get("promotions"):
            failures.append(f"{unit}: no promotion ladder")
            continue
        ranks = [tier["rank"] for tier in spec["promotions"]]
        if ranks != sorted(ranks) or ranks[0] != 1:
            failures.append(f"{unit}: promotion ranks {ranks} are not ascending from 1")
        for tier in spec["promotions"]:
            if not tier.get("abilities"):
                failures.append(f"{unit}: rank {tier['rank']} unlocks nothing")
            for ability in tier.get("abilities", []):
                if ability not in known:
                    failures.append(f"{unit}: rank {tier['rank']} unlocks unknown ability {ability!r}")

    infantry = {u for u, s in roster.items() if s.get("class") == "infantry"}
    for unit in sorted(infantry - set(roles)):
        failures.append(f"{unit}: infantry with no role")

    print(f"{len(roles)} roles, {len(known)} known ability ids, {len(infantry)} infantry units")
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures[:20]:
            print("  " + f)
        return 1
    print("PASS: every infantry unit has a role and every unlocked ability exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
