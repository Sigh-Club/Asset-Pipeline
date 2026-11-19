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
ATTACH = re.compile(r'attachment\s*=\s*"art[\\/]([^"]+)"', re.IGNORECASE)

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


def entries_outside_chapters(text: str, pattern: re.Pattern) -> list[str]:
    """The `pattern` matches in `text` that are not inside a `chapter_*` block.

    DoW2 duplicates a slot for DLC army-painter variants under `chapter_render_models`,
    `chapter_animator_attachment` and friends — the Ork Freebooterz DLC swaps the warboss's choppa
    for a cutlass, the Imperial Guard Death Korps swaps the head. They are alternatives for the
    SAME slot, so importing them welds two weapons into one hand (measured: the warboss arrived with
    a cutlass it does not carry) or two heads onto one neck. A chapter block opens on a bare
    `chapter_*` line and closes at its matching brace; `chapter_key_name = "..."` is a field, not a
    block, and is ignored as an opener.
    """
    out: list[str] = []
    chapter_depth = None
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if chapter_depth is None and stripped.startswith("chapter_") and "=" not in stripped:
            chapter_depth = depth
        for ch in stripped:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if chapter_depth is not None and depth <= chapter_depth:
                    chapter_depth = None
        if chapter_depth is not None:
            continue
        m = pattern.search(stripped)
        if m:
            out.append(m.group(1).replace("\\", "/"))
    return out


def resolve_attachments(ebps: Path, roots: list[Path]):
    """The unit's `animator_attachments` parts (the head, and any attached kit), resolved.

    A unit's head is not in its wargear: the game attaches it from the unit blueprint's
    `animator_attachments` block (measured: `cadian_trooper` for the guardsmen squad,
    `warboss_01` for the warboss). The chapter variants under `chapter_animator_attachment`
    are cosmetic DLC swaps for the same slot, so they are skipped — including them would weld
    two heads onto one neck.
    """
    text = ebps.read_text(errors="replace")
    raw = entries_outside_chapters(text, ATTACH)
    return _locate(preferred_tier(raw), roots)


def _locate(wanted: list[str], roots: list[Path]):
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


def resolve(wargear: Path, roots: list[Path]):
    text = wargear.read_text(errors="replace")
    raw = entries_outside_chapters(text, ENTRY)
    wanted = preferred_tier(raw)
    if len(raw) != len(wanted):
        print(f"# de-duplicated {len(raw)} render_models to {len(wanted)} logical part(s)",
              file=sys.stderr)
    return _locate(wanted, roots)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--wargear", required=True)
    ap.add_argument("--ebps", action="append", default=[],
                    help="a unit blueprint whose animator_attachments carry the head")
    ap.add_argument("--art", action="append", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    roots = [Path(r) for r in a.art]
    found, missing = resolve(Path(a.wargear), roots)
    for ebps in a.ebps:
        more, lost = resolve_attachments(Path(ebps), roots)
        found.extend(more)
        missing.extend(lost)
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
