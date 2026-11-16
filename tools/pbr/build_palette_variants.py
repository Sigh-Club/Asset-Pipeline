#!/usr/bin/env python3
"""build_palette_variants.py — band-limit library albedos to the pixel tier's texel
budget.

A 1024 px material tile projected onto a 2 cm texel grid is a 50:1 downscale.
Sampling it at one point per texel does not average: it picks a random sub-texel
value, and the result reads as camouflage (measured on the first barrel: the
metal-trim sheet locked into blue/grey noise). The correct treatment is a mip
level — deliver the material at the resolution the texel grid can actually
represent, with 2x supersampling so the bake itself does not alias.

This writes `<item>/albedo_palette.png` (and `emissive_palette.png`) sized at
`2 * round(tile_m / texel_m)` px, then `build_blender_library.py --pixel` builds
`grimdark_scifi_palette.blend` from them. The AAA library and its maps are
untouched.

Usage:
    python3 tools/pbr/build_palette_variants.py --texel-m 0.02
    python3 tools/pbr/build_palette_variants.py --texel-m 0.02 --only metal_trim
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
MIN_PX = 32
MAX_PX = 512


def variant_size(tile_m: float, texel_m: float, supersample: int) -> int:
    texels = tile_m / texel_m
    return int(np.clip(round(texels * supersample), MIN_PX, MAX_PX) // 2 * 2)


def compress_contrast(a: np.ndarray, keep: float) -> np.ndarray:
    """Pull the pixel variant's contrast toward its own median.

    Even band-limited, a photo-derived material keeps scratch-level contrast
    that reads as noise once box-projected onto a coarse mesh facet by facet.
    The pixel tier wants the material's *identity* (alloy, trim colour, plate
    seams) and not its micro-wear, which is Boltgun's "impression of the object".
    """
    if keep >= 1.0:
        return a
    med = np.median(a.reshape(-1, 3), axis=0)
    return np.clip(med + (a - med) * keep, 0, 255)


def build_item(item_dir: Path, texel_m: float, supersample: int,
               contrast_keep: float = 0.72) -> dict | None:
    meta_path = item_dir / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("kind") == "decal":
        return None
    albedo = item_dir / "albedo.png"
    if not albedo.exists():
        return None
    tile_m = float(meta.get("tile_m") or 1.0)
    size = variant_size(tile_m, texel_m, supersample)
    src = Image.open(albedo).convert("RGBA")
    small = src.resize((size, size), Image.LANCZOS)
    arr = np.asarray(small, dtype=np.float32)
    std_before = float(arr[..., :3].std())
    arr[..., :3] = compress_contrast(arr[..., :3], contrast_keep)
    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")
    out.save(item_dir / "albedo_palette.png")
    written = ["albedo_palette.png"]
    emissive = item_dir / "emissive.png"
    if emissive.exists():
        Image.open(emissive).convert("RGBA").resize((size, size), Image.LANCZOS).save(
            item_dir / "emissive_palette.png")
        written.append("emissive_palette.png")
    report = {"size_px": size, "tile_m": tile_m, "texel_m": texel_m,
              "texels_per_tile": round(tile_m / texel_m, 2),
              "supersample": supersample, "written": written,
              "contrast_keep": contrast_keep,
              "luma_std_before": round(std_before, 2),
              "luma_std_after": round(float(arr[..., :3].std()), 2),
              "source_px": list(src.size)}
    (item_dir / "pixel_variant.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--texel-m", type=float, default=0.02)
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--only", help="only items whose id contains this")
    ap.add_argument("--contrast-keep", type=float, default=0.72,
                    help="0..1 contrast retained; <1 suppresses micro-wear")
    args = ap.parse_args()
    built = 0
    for item_dir in sorted(p for p in LIB.iterdir() if p.is_dir()):
        if args.only and args.only not in item_dir.name:
            continue
        r = build_item(item_dir, args.texel_m, args.supersample, args.contrast_keep)
        if r:
            built += 1
            print(f"  {item_dir.name}: {r['size_px']}px "
                  f"({r['texels_per_tile']} texels/tile)")
    print(f"built {built} pixel variant(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
