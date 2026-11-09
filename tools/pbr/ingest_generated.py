#!/usr/bin/env python3
"""ingest_generated.py — turn adapter output into library-ready PBR material sets.

This is the missing link between `tools/train/generate.py` and the material
library: it takes generated albedo tiles plus their provenance meta, applies the
production treatment (flatten lighting, repair only a broken seam) and derives
normal/roughness/metallic with `derive_maps.py`. The result is the same item
layout the library builder and Blender expect, so a generated tile can be put on
a real mesh and reviewed.

Usage:
    python3 tools/pbr/ingest_generated.py \
        --gen output/gen/iron_directorate \
        --library assets/materials/grimdark_scifi \
        --out output/gen/adapted_library \
        --items iron_directorate__armour_primary,iron_directorate__armour_secondary,iron_directorate__underlayer,iron_directorate__metal_trim

Each generated row is matched to a library item by prompt id (see
`tools/train/prompts/eval_materials.json`); only the first seed is ingested.
Metalness comes from the owning item's meta, never from the image model.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT_SIZE = 1024


def load_derive_maps():
    spec = importlib.util.spec_from_file_location(
        "derive_maps", ROOT / "tools" / "pbr" / "derive_maps.py")
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    return dm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True, help="dir written by tools/train/generate.py")
    ap.add_argument("--library", default=str(ROOT / "assets/materials/grimdark_scifi"))
    ap.add_argument("--out", required=True, help="library tree to write (copy-on-first-use)")
    ap.add_argument("--items", required=True,
                    help="comma-separated library item ids to replace")
    ap.add_argument("--keep", action="store_true",
                    help="keep the existing out tree instead of copying the source library")
    args = ap.parse_args()

    gen = Path(args.gen)
    src_lib = Path(args.library)
    out = Path(args.out)
    dm = load_derive_maps()

    rows = [json.loads(line) for line in (gen / "meta.jsonl").read_text().splitlines() if line.strip()]
    by_id: dict[str, dict] = {}
    for r in rows:
        by_id.setdefault(r["id"], r)  # first seed wins

    if not args.keep:
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(src_lib, out)

    ingested = []
    for item_id in [i.strip() for i in args.items.split(",") if i.strip()]:
        if item_id not in by_id:
            print(f"skip {item_id}: no generated tile with that id", file=sys.stderr)
            continue
        row = by_id[item_id]
        item_dir = out / item_id
        base_meta = {}
        src_meta = src_lib / item_id / "meta.json"
        if src_meta.exists():
            base_meta = json.loads(src_meta.read_text())

        arr = np.asarray(Image.open(gen / row["file"]).convert("RGB"), dtype=np.float32)
        before = dm.seam_score(arr)
        before_ratio = dm.seam_ratio(arr)
        arr = dm.flatten_lighting(arr)
        if before_ratio > 1.5:
            arr = dm.seamless(arr)
        albedo = np.asarray(
            Image.fromarray(arr.clip(0, 255).astype(np.uint8)).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS),
            dtype=np.float32)

        item_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(albedo.astype(np.uint8)).save(item_dir / "albedo.png")
        emissive = bool(base_meta.get("emissive"))
        metal = float(base_meta.get("metallic_constant", 0.0))
        Image.fromarray(dm.normal_map(albedo, 1.0 if emissive else 1.3)).save(item_dir / "normal.png")
        Image.fromarray(dm.roughness_map(albedo, metal, emissive)).save(item_dir / "roughness.png")
        Image.fromarray(np.full((OUT_SIZE, OUT_SIZE), int(metal * 255), dtype=np.uint8)).save(
            item_dir / "metallic.png")
        if emissive:
            Image.fromarray(dm.emissive_map(albedo)).save(item_dir / "emissive.png")

        meta = dict(base_meta)
        meta.update({
            "id": item_id,
            "source": "adapter",
            "adapter": row.get("adapter"),
            "adapter_sha256_16": row.get("adapter_sha256_16"),
            "prompt": row.get("prompt"),
            "seed": row.get("seed"),
            "tileable_before": round(before, 4),
            "tileable_after": round(dm.seam_score(arr), 4),
            "tileable_ratio_before": round(before_ratio, 3),
            "tileable_ratio_after": round(dm.seam_ratio(arr), 3),
            "derived": "normal/roughness from albedo (tools/pbr/derive_maps.py); not model-generated",
        })
        (item_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        ingested.append(item_id)
        print(f"ingested {item_id} from {row['file']} (seam {before:.3f} -> {meta['tileable_after']:.3f})")

    print(f"{len(ingested)} item(s) -> {out}")
    return 0 if ingested else 1


if __name__ == "__main__":
    sys.exit(main())
