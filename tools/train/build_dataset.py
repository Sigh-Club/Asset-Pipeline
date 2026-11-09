#!/usr/bin/env python3
"""build_dataset.py — manufacture a training corpus from the built material library.

The corpus is a build artefact, not a scrape: every image comes from a generated
sheet whose prompt, faction and slot are known exactly, so captions are exact and
the split can hold out an entire style.

Output (default `datasets/materials_v1/`):
    train/<id>_<k>.png + .txt      training image and caption
    eval/<id>.png + .txt           held-out style (never trained on)
    manifest.json                  provenance, split rule, counts, hashes

Usage:
    python3 tools/train/build_dataset.py --holdout void_corsairs,wreckstorm_clans
    python3 tools/train/build_dataset.py --size 512 --per-item 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
OUT = ROOT / "datasets" / "materials_v1"
CAPTION_PREFIX = "grimdark science-fiction material, seamless tileable texture"


def crops_for(img: Image.Image, size: int, per_item: int, rng: random.Random):
    """Random square crops. Several crops per tile give the model scale invariance
    without inventing content."""
    w, h = img.size
    out = []
    for i in range(per_item):
        side = int(min(w, h) * (0.62 if i == 0 else 0.5))
        side = min(side, min(w, h))
        x = rng.randint(0, w - side)
        y = rng.randint(0, h - side)
        out.append(img.crop((x, y, x + side, y + side)).resize((size, size), Image.LANCZOS))
    return out


def caption_for(meta: dict) -> str:
    bits = [CAPTION_PREFIX]
    slot = (meta.get("slot") or "surface").replace("_", " ")
    bits.append(f"{slot} of {meta.get('faction', 'shared').replace('_', ' ')}")
    prompt = (meta.get("prompt") or "").strip().rstrip(".")
    if prompt:
        bits.append(prompt)
    if meta.get("emissive"):
        bits.append("emissive glow, unlit albedo")
    return ", ".join(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", default="void_corsairs,wreckstorm_clans",
                    help="comma-separated factions whose assets are eval-only")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--per-item", type=int, default=2)
    ap.add_argument("--exclude-kinds", default="decal,pattern",
                    help="material-like kinds only; trim sheets teach graphic motifs, "
                         "not surface character")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    holdout = {f.strip() for f in args.holdout.split(",") if f.strip()}
    excluded = {k.strip() for k in args.exclude_kinds.split(",") if k.strip()}
    out = Path(args.out)
    for sub in ("train", "eval"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    manifest = {"seed": args.seed, "size": args.size, "per_item": args.per_item,
                "holdout_factions": sorted(holdout), "excluded_kinds": sorted(excluded),
                "source_library": str(LIB),
                "caption_prefix": CAPTION_PREFIX, "items": []}
    counts = {"train": 0, "eval": 0}

    # Decals are not tileable and trim-sheet patterns carry graphic motifs
    # (chevrons, glyphs, big triangles). Both teach "picture", not "surface", so
    # the material corpus excludes them by default. Measured 2026-11-09: a corpus
    # containing 28 pattern tiles made the adapter draw chevrons onto rust.
    for item_dir in sorted(p for p in LIB.iterdir() if p.is_dir()):
        meta_path = item_dir / "meta.json"
        albedo = item_dir / "albedo.png"
        if not meta_path.exists() or not albedo.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("kind") in excluded:
            continue
        faction = meta.get("faction", "shared")
        split = "eval" if faction in holdout else "train"
        img = Image.open(albedo).convert("RGB")
        n = 1 if split == "eval" else args.per_item
        for i, crop in enumerate(crops_for(img, args.size, n, rng)):
            name = f"{item_dir.name}_{i}" if n > 1 else item_dir.name
            crop.save(out / split / f"{name}.png")
            (out / split / f"{name}.txt").write_text(caption_for(meta) + "\n")
            counts[split] += 1
            manifest["items"].append({
                "file": f"{split}/{name}.png", "split": split, "id": item_dir.name,
                "faction": faction, "slot": meta.get("slot"), "kind": meta.get("kind"),
                "tile_m": meta.get("tile_m"),
                "sha256": hashlib.sha256((out / split / f"{name}.png").read_bytes()).hexdigest()[:16],
            })

    manifest["counts"] = counts
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"train {counts['train']} / eval {counts['eval']} -> {out}")
    print(f"held out: {', '.join(sorted(holdout)) or 'none'}")


if __name__ == "__main__":
    main()
