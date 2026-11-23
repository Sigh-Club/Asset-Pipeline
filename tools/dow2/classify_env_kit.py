#!/usr/bin/env python3
"""classify_env_kit.py — split the shipped environment kit into building families.

The kit is a flat list of 435 props. A building cannot be assembled from a flat list, because the
list does not say which piece is a wall and which is a crate, and picking a barrier as a wall is what
made every mass read as a box with a plate on it. This classifies every prop into the family the
prefab builder is allowed to use it for, and records the measurements the builder needs:

  * the piece's real footprint and height (from the exported model, not from the name);
  * whether that footprint can sit on our 2 m grid without being stretched. Skyrim's GDC 2013 kit
    rules are explicit that footprints must be multiples of each other, and that a piece which does
    not divide will eventually create gaps: so a wall is only usable when its length is within 12% of
    a whole number of cells;
  * the cover tier it can grant, from the shipped ladder (0.64 / 0.96 / 1.6 m), so cover is a height
    and never a guess;
  * whether the piece is faction architecture (army model, needs a plinth) or map dressing.

Usage:
    python3 tools/dow2/classify_env_kit.py --kit <path>/env_kit.json --out <path>/env_families.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Our gameplay grid, from three/gridMath.ts. A piece is grid-usable when its run length divides the
# cell size to within this tolerance; beyond it the piece is scaled, and a scaled shipped wall is a
# stretched texture.
CELL_M = 2.0
GRID_TOLERANCE = 0.12
# The shipped cover ladder (XComWorldData.uc): a prop grants cover only up to its own height.
COVER_TIERS = (("low", 0.64), ("high", 0.96), ("climb", 1.6))

# Family rules. Name evidence comes first, geometry only breaks ties, because geometry alone called a
# burned Predator a wall (13.8 m tall, 6.6 m long, thin) and a basalt column a wall as well. A wall has
# to be named as one or be a building-like slab; natural rock and vehicles are their own families.
NATURAL = r"rock|cliff|boulder|stone|mussel|dune|stalag|volcanic|ice_|crystal"
VEHICLE = r"vehicle|wreck|tank(?!trap)|predator|lemun|chimera|sentin"
STACK = r"stack|smokestack|chimney|silo|tower"
WALL_NAMED = r"(^|_)walls?(_|$)|fascade|facade|spine|supportwall|_wall_|wall_"
DOORWAY = r"arch(ed)?_?(way|01|02)|doorway|_gate|gate_"
COVER = r"barricade|sandbag|crate|tank_?trap|dragon|barrel|container|rubble|debris|junk|pile"
DRESSING = r"lamp|light|banner|pipe|wire|sign|skull|bone|antler|pole|cable|antenna|vent|chain"
FLORA = r"vine|tree|bush|fern|grass|flora|root|moss|plant|hedge"


def family_of(name: str, biome: str, size: list[float]) -> str:
    low = name.lower()
    height = size[1] if len(size) > 1 else 0.0
    footprint = max(size[0], size[2]) if len(size) > 2 else 0.0
    thin = min(size[0], size[2]) if len(size) > 2 else 0.0
    if biome.startswith("structure_"):
        return "faction"
    if re.search(NATURAL, low):
        return "natural"
    if re.search(VEHICLE, low):
        return "vehicle"
    if re.search(DOORWAY, low):
        return "doorway"
    if re.search(WALL_NAMED, low):
        if "corner" in low:
            return "wall_corner"
        return "wall_barrier" if height < 2.4 else "wall_run"
    if re.search(r"stair|steps?_|_ramp|ramp_", low):
        return "stair"
    if re.search(r"roof|canopy|awning|ceiling", low):
        return "roof"
    if re.search(r"floor|platform|catwalk|grate|deck|walkway", low):
        return "floor"
    if re.search(r"pillar|column|buttress|post_|_post", low):
        return "pillar"
    if re.search(STACK, low):
        return "pillar"
    if re.search(COVER, low):
        return "cover"
    if re.search(DRESSING, low):
        return "dressing"
    if re.search(FLORA, low):
        return "flora"
    # geometry decides only when the name says nothing: a long thin tall slab is a wall, a tall square
    # mass is a pier, a low object is cover.
    if height >= 2.4 and footprint >= 3.0 and thin <= 3.5:
        return "wall_run"
    if height >= 4.0:
        return "pillar"
    if height <= 2.4:
        return "cover" if height >= 0.4 else "dressing"
    return "prop"


def grid_fit(length: float) -> dict:
    """How a run length sits on the 2 m grid: whole cells, the error, and whether it is usable."""
    cells = max(1, round(length / CELL_M))
    error = abs(length - cells * CELL_M) / (cells * CELL_M)
    return {
        "cells": int(cells),
        "error": round(error, 3),
        "usable": bool(error <= GRID_TOLERANCE),
    }


def cover_tier(height: float) -> str | None:
    tier = None
    for name, h in COVER_TIERS:
        if height + 1e-6 >= h:
            tier = name
    return tier


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=str(ROOT / "output/source_lab/env_kit.json"))
    ap.add_argument("--out", default=str(ROOT / "output/source_lab/env_families.json"))
    args = ap.parse_args()
    kit_path = Path(args.kit)
    if not kit_path.exists():
        # the published kit lives in the game repo; accept that path too
        alt = ROOT.parent / "Imperium-of-Ash/frontend/public/assets/models/env/env_kit.json"
        kit_path = alt if alt.exists() else kit_path
    props = json.loads(kit_path.read_text())["props"]

    out, families = [], Counter()
    by_family: dict[str, list[dict]] = defaultdict(list)
    for p in props:
        size = [float(v) for v in (p.get("size") or [0, 0, 0])]
        fam = family_of(p["name"], p.get("biome") or "", size)
        families[fam] += 1
        run_len = max(size[0], size[2])
        entry = {
            "name": p["name"],
            "biome": p.get("biome"),
            "family": fam,
            "size": size,
            "height": round(size[1], 2),
            "tris": p.get("tris"),
            "placements": p.get("placements", 0),
            "textured": bool(p.get("textured", True)),
            "grid": grid_fit(run_len) if fam in ("wall_run", "wall_barrier", "wall_corner") else None,
            "cover": cover_tier(size[1]),
            "url": p.get("url"),
        }
        out.append(entry)
        by_family[fam].append(entry)

    doc = {
        "generated_by": "tools/dow2/classify_env_kit.py",
        "cell_m": CELL_M,
        "grid_tolerance": GRID_TOLERANCE,
        "cover_tiers": {name: h for name, h in COVER_TIERS},
        "families": dict(sorted(families.items())),
        "pieces": sorted(out, key=lambda e: (e["family"], -e["height"])),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=1))

    print(f"classified {len(out)} props into {len(families)} families")
    for fam, count in families.most_common():
        usable = sum(1 for e in by_family[fam] if (e["grid"] or {}).get("usable"))
        extra = f" | grid-usable {usable}" if fam.startswith("wall") else ""
        print(f"  {fam:14s} {count:4d}{extra}")
    walls = [e for e in out if e["family"] == "wall_run"]
    tall = sorted(walls, key=lambda e: -e["height"])[:10]
    print("\narchitectural wall family, tallest first (the pieces a building must be made of):")
    for e in tall:
        g = e["grid"]
        print(f"  {e['name'][:40]:42s} {e['height']:5.2f} m  run {max(e['size'][0], e['size'][2]):5.2f} m "
              f"grid {g['cells']} cells err {g['error']:.2f} {'OK' if g['usable'] else 'STRETCH'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
