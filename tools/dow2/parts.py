#!/usr/bin/env python3
"""parts.py — resolve a DoW2 unit's part list from its wargear blueprint.

A DoW2 unit is NOT one model. The shipped wargear data lists the parts that make it up, e.g.

    render_model = "art\\race_chaos\\troops_wargear\\armour\\chaos_sorcerer_common\\chaos_sorcerer_common"
    render_model = "art\\race_chaos\\troops_wargear\\heads\\chaos_sorcerer_epic\\chaos_sorcerer_head_epic"
    render_model = "art\\race_chaos\\troops_wargear\\accessories\\chaos_sorcerer_bacpack_common\\..."

(2,694 such entries across the shipped wargear data). Building a single part is why a "unit" came out
as a chest plate with no head or arms. This resolves the list to files on disk so the build can
assemble the unit the way the game does.

Usage:
  python3 tools/dow2/parts.py --wargear <wargear.txt> --art <sga_art root> [--art <root2>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENTRY = re.compile(r'render_model\s*=\s*"art[\\/]([^"]+)"', re.IGNORECASE)

# DoW2 lists the SAME logical part at several quality tiers in one `render_models` block — e.g.
# `ig_armour_epic` and `ig_armour` are one body at epic and common quality, not two parts to weld
# together. Building both puts two copies of the body in the same space, which reads as a jumble of
# shards no matter how good the rig is. The game picks one tier by quality; so do we.
VARIANT_SUFFIXES = ("_common", "_epic", "_rare", "_glow", "_alpha", "_carnage", "_campaign")
TIER_ORDER = ("_epic", "_rare", "_common", "")


def canonical_part(rel: str) -> str:
    """The logical part a model path belongs to, with its quality tier stripped."""
    name = rel.split("/")[-1]
    for suffix in VARIANT_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def preferred_tier(paths: list[str]) -> list[str]:
    """Keep one model per logical part, preferring the highest quality tier present."""
    groups: dict[str, list[str]] = {}
    for rel in paths:
        groups.setdefault(canonical_part(rel), []).append(rel)
    out = []
    for _part, variants in groups.items():
        chosen = None
        for tier in TIER_ORDER:
            for rel in variants:
                if rel.split("/")[-1].endswith(tier) or tier == "":
                    chosen = rel
                    break
            if chosen:
                break
        out.append(chosen or variants[0])
    return out


def resolve(wargear: Path, roots: list[Path]):
    text = wargear.read_text(errors="replace")
    raw = [m.group(1).replace("\\", "/") for m in ENTRY.finditer(text)]
    wanted = preferred_tier(raw)
    if len(raw) != len(wanted):
        print(f"# de-duplicated {len(raw)} render_models to {len(wanted)} logical part(s)",
              file=sys.stderr)
    found, missing = [], []
    for rel in wanted:
        rel = re.sub(r"\.model$", "", rel, flags=re.IGNORECASE)
        name = rel.split("/")[-1]
        hit = None
        for root in roots:
            for cand in root.rglob(f"{name}.model"):
                if str(cand).replace("\\", "/").endswith(f"{rel}.model"):
                    hit = cand
                    break
            if hit:
                break
        if hit:
            found.append(hit)
        else:
            missing.append(rel)
    return found, missing


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--wargear", required=True)
    ap.add_argument("--art", action="append", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    roots = [Path(r) for r in a.art]
    found, missing = resolve(Path(a.wargear), roots)
    if a.json:
        import json
        print(json.dumps({"parts": [str(p) for p in found], "missing": missing}))
    else:
        for p in found:
            print(p)
        for m in missing:
            print(f"# MISSING {m}", file=sys.stderr)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
