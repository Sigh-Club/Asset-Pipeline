#!/usr/bin/env python3
"""check_unit_heads.py — a unit built from an armour attachment must declare its head.

The shipped art separates a unit's *animator* model (the body, which carries the head) from its
*armour* attachments. Building an armour attachment as if it were the body produces a headless unit:
measured, `dow_ig_commissar` shipped as `general_armour_epic.model` with no head (a headless lord
general on the board) and `dow_ig_inquisitor` as `witchhunter_armour_epic.model` the same way.

The rule this gate enforces is the layout's own: a body under `troops_wargear/armour/` is an attachment,
so the spec must declare a `head` as well (or use the animator model under `troops/` instead).

Usage:
    python3 tools/dow2/check_unit_heads.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Units whose head is part of the body model itself, so there is no head attachment to declare: a
# space marine's helmet, an eldar's helm and a tyranid's skull are modelled into the body. Each entry
# carries why, because the list is the only place the rule is relaxed.
HEAD_IN_BODY = {
    "dow_chaos_champion": "aspiring champion wears a helmet modelled into the armour",
    "dow_chaos_havoc": "havoc helmet is part of the chaos marine body",
    "dow_chaos_heretic": "cultist body model includes the head",
    "dow_chaos_marine": "space marine helmet is part of the body",
    "dow_eldar_banshee": "banshee helm is part of the armour",
    "dow_eldar_guardian": "guardian helm is part of the body",
    "dow_eldar_ranger": "ranger helm is part of the armour",
    "dow_tyr_carnifex": "creature skull is part of the body model",
    "dow_tyr_hive_tyrant": "creature skull is part of the body model",
    "dow_tyr_hormagaunt": "creature skull is part of the body model",
    "dow_tyr_termagaunt": "creature skull is part of the body model",
    "dow_tyr_warrior": "creature skull is part of the body model",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specs", type=Path, default=ROOT / "output/source_lab/roster_specs.json")
    a = ap.parse_args(argv)

    specs = json.loads(a.specs.read_text())
    failures = []
    for unit, spec in sorted(specs.items()):
        body = (spec.get("body") or "").replace("\\", "/")
        head = spec.get("head") or ""
        if "troops_wargear/armour/" in body and not head and unit not in HEAD_IN_BODY:
            failures.append((unit, body.split("/")[-1]))

    print(f"{len(specs)} units checked")
    if failures:
        print(f"FAIL: {len(failures)} unit(s) built from an armour attachment with no head")
        for unit, body in failures:
            print(f"  {unit}: body={body} — add a head or build from the animator model")
        return 1
    print("PASS: every armour-built unit declares its head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
