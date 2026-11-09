#!/usr/bin/env python3
"""build_material_manifest.py — turn the material spec into a production plan.

Reads configs/materials/families.json (the demand: faction families, shared
surfaces, patterns, decals) and emits:

  assets/materials/grimdark_scifi/manifest.json   machine plan (items + batches)
  assets/materials/grimdark_scifi/PROMPTS.md      human/agent review sheet
  assets/materials/grimdark_scifi/generate.sh     ready-to-run gemini-img batches

One image generation yields a N-up sheet (default 2x2), so item count != generation
count. The script prints both, which is the honest budget answer.

Usage:
    python3 tools/pbr/build_material_manifest.py            # write plan + report
    python3 tools/pbr/build_material_manifest.py --batch 1  # print one batch's commands
    python3 tools/pbr/build_material_manifest.py --check    # which items already exist
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "configs" / "materials" / "families.json"
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
SHEET_DIR = LIB / "sheets"

NEGATIVE = (
    "no perspective, no vignette, no cast shadows, no baked lighting, no bloom, "
    "no text, no watermark, no objects, no background scene, flat even illumination, "
    "photographic material reference"
)


def tile_prompt(item, kind):
    if kind == "decal":
        shape = ("single flat vector-style graphic centred on exactly #FFFFFF pure white background, no gradient, no vignette, no drop shadow, no card edge, no checkerboard, crisp edges, the graphic is the only non-white content")
    else:
        shape = "seamless tileable texture, filling the entire quadrant edge to edge"
    bits = [
        f"{item['prompt']}",
        shape,
        "grimdark science-fiction material reference, 40k-adjacent industrial grim tone",
        f"neutral albedo colour, base colour only, {NEGATIVE}",
    ]
    if item.get("emissive"):
        bits.append("emissive areas bright and saturated but unbloomed")
    return ", ".join(bits)


def sheet_prompt(items, kind):
    n = len(items)
    lines = [f"A {2}x{2} grid of {n} separate material tiles on a pure black background, "
             f"each quadrant a distinct tile, separated by a 24 pixel black gutter.",
             "Quadrants: top-left, top-right, bottom-left, bottom-right."]
    for i, it in enumerate(items):
        q = ["top-left", "top-right", "bottom-left", "bottom-right"][i]
        lines.append(f"{q}: {tile_prompt(it, kind)}")
    return "\n".join(lines)


def build():
    spec = json.loads(SPEC.read_text())
    items = []
    for faction in spec["factions"]:
        for fam in faction["families"]:
            items.append({
                "id": f"{faction['id']}__{fam['slot']}",
                "kind": "material",
                "faction": faction["id"],
                "slot": fam["slot"],
                "prompt": fam["prompt"],
                "metal": fam.get("metal", 0.0),
                "tile_m": spec.get("slot_tile_m", {}).get(fam["slot"], 1.0),
                "emissive": bool(fam.get("emissive")),
                "palette": faction["palette"],
            })
    for mat in spec["shared_materials"]:
        items.append({"id": mat["id"], "kind": "material", "faction": "shared",
                      "slot": "shared", "prompt": mat["prompt"],
                      "metal": mat.get("metal", 0.0),
                      "tile_m": mat.get("tile_m", 1.0), "emissive": False})
    for pat in spec.get("patterns", []):
        items.append({"id": pat["id"], "kind": "pattern", "faction": pat.get("faction", "shared"),
                      "slot": "pattern", "prompt": pat["prompt"],
                      "metal": pat.get("metal", 0.0), "emissive": False,
                      "scale_m": pat.get("scale_m", 1.0),
                      "tile_m": pat.get("scale_m", 1.0)})
    for dec in spec["decals"]:
        items.append({"id": dec["id"], "kind": "decal", "faction": "shared",
                      "slot": "decal", "prompt": dec["prompt"], "metal": 0.0,
                      "tile_m": 1.0, "emissive": False,
                      "full_bleed": bool(dec.get("full_bleed"))})

    size = spec["sheet"]["size"]
    per_sheet = spec["sheet"]["cols"] * spec["sheet"]["rows"]

    # Group by kind first, then pack sequentially. Materials grouped so a sheet
    # stays one faction where possible (colour harmony), else shared families.
    order = {"material": 0, "pattern": 1, "decal": 2}

    def material_groups():
        """Group so a sheet holds one faction's coherent kit, never a mix of
        factions: 4 non-accent families per sheet, then all accent/emissive
        sheets together (they are pure glow and read as a set)."""
        mats = [i for i in items if i["kind"] == "material"]
        accents = [i for i in mats if i["slot"] == "accent_emissive"]
        body = [i for i in mats if i["slot"] != "accent_emissive" and i["faction"] != "shared"]
        shared = [i for i in mats if i["faction"] == "shared"]
        groups = []
        for fac in sorted({i["faction"] for i in body}):
            groups.append([i for i in body if i["faction"] == fac])
        groups.append(accents)
        groups.append(shared)
        return groups

    batches = []

    def add_batch(kind, chunk):
        idx = len(batches) + 1
        batches.append({
            "batch": idx,
            "kind": kind,
            "items": [i["id"] for i in chunk],
            "sheet": str(SHEET_DIR / f"batch_{idx:02d}_{kind}.png"),
            "prompt": sheet_prompt(chunk, kind),
        })

    for group in material_groups():
        for n in range(0, len(group), per_sheet):
            add_batch("material", group[n:n + per_sheet])
    for kind in ("pattern", "decal"):
        pool = sorted([i for i in items if i["kind"] == kind], key=lambda i: i["id"])
        for n in range(0, len(pool), per_sheet):
            add_batch(kind, pool[n:n + per_sheet])

    manifest = {
        "library": "grimdark_scifi",
        "root": str(LIB),
        "sheet_size": size,
        "per_sheet": per_sheet,
        "generation_estimate": len(batches),
        "counts": {
            "items": len(items),
            "materials": sum(1 for i in items if i["kind"] == "material"),
            "patterns": sum(1 for i in items if i["kind"] == "pattern"),
            "decals": sum(1 for i in items if i["kind"] == "decal"),
            "factions": len(spec["factions"]),
        },
        "items": items,
        "batches": batches,
    }
    LIB.mkdir(parents=True, exist_ok=True)
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    (LIB / "manifest.json").write_text(json.dumps(manifest, indent=2))

    md = [f"# Grimdark sci-fi material library — generation plan\n",
          f"Items: {manifest['counts']['items']} "
          f"({manifest['counts']['materials']} materials, {manifest['counts']['patterns']} patterns, "
          f"{manifest['counts']['decals']} decals) across {manifest['counts']['factions']} factions.\n",
          f"Generations needed: **{len(batches)}** sheets at {per_sheet}-up, {size}px.\n",
          "Derived maps (normal/roughness/metallic) are computed locally from albedo — "
          "never generated by the image model.\n"]
    for b in batches:
        md.append(f"## Batch {b['batch']} — {b['kind']} — {', '.join(b['items'])}\n")
        md.append("```\n" + b["prompt"] + "\n```\n")
    (LIB / "PROMPTS.md").write_text("\n".join(md))

    sh = ["#!/usr/bin/env bash", "set -euo pipefail",
          f"cd {shlex.quote(str(ROOT))}",
          "# Generated by tools/pbr/build_material_manifest.py — run one batch per generation.",
          "# After generating: python3 tools/pbr/derive_maps.py --batch N",
          ""]
    prompt_dir = LIB / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    for b in batches:
        pf = prompt_dir / f"batch_{b['batch']:02d}_{b['kind']}.txt"
        pf.write_text(b["prompt"] + "\n")
        sh.append(f"# batch {b['batch']}: {', '.join(b['items'])}")
        sh.append(f"gemini-img \"$(cat {shlex.quote(str(pf))})\" \\")
        sh.append(f"  --out {shlex.quote(str(SHEET_DIR))} --name batch_{b['batch']:02d}_{b['kind']}")
        sh.append("")
    (LIB / "generate.sh").write_text("\n".join(sh))
    (LIB / "generate.sh").chmod(0o755)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, help="print commands for one batch")
    ap.add_argument("--check", action="store_true", help="report which items already have output")
    args = ap.parse_args()

    m = build()
    if args.batch:
        b = next((x for x in m["batches"] if x["batch"] == args.batch), None)
        if not b:
            print(f"no batch {args.batch}", file=sys.stderr)
            return 2
        pf = LIB / "prompts" / f"batch_{b['batch']:02d}_{b['kind']}.txt"
        print(b["prompt"])
        print()
        print(f"gemini-img \"$(cat {pf})\" --out {SHEET_DIR} --name batch_{b['batch']:02d}_{b['kind']}")
        return 0

    if args.check:
        done = [i for i in m["items"] if (LIB / i["id"] / "albedo.png").exists()]
        print(f"{len(done)}/{len(m['items'])} items built")
        for i in m["items"]:
            print(("  ok   " if i in done else "  todo ") + i["id"])
        return 0

    c = m["counts"]
    print(f"saved {LIB}/manifest.json")
    print(f"items: {c['items']} (materials {c['materials']}, patterns {c['patterns']}, decals {c['decals']})")
    print(f"image generations needed: {m['generation_estimate']} "
          f"({m['per_sheet']} items per {m['sheet_size']}px sheet)")
    print(f"prompts: {LIB}/PROMPTS.md   commands: {LIB}/generate.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
