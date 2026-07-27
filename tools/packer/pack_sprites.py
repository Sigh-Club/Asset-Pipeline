#!/usr/bin/env python3
"""
pack_sprites.py — Sprite Sheet Packer + JSON Metadata Generator
Packs processed frames into tight atlases with frame metadata.

Usage:
    python pack_sprites.py --source assets/characters/foo/render/processed --output assets/characters/foo/sheets

Outputs per unit:
- <unit>_atlas.png          : Packed sprite sheet image
- <unit>_atlas.json         : Frame metadata (name, x, y, w, h, pivot)
- <unit>_atlas_lod1.png/.json : LOD1 variant (50% downscaled)
- <unit>_atlas_lod2.png/.json : LOD2 variant (25% downscaled)

Atlas packing uses a simple shelf algorithm (sufficient for our frame sizes).
Can be swapped for MaxRects or another algorithm if needed.

Author: Asset-Pipeline Automation
Docs: docs/STYLE_GUIDE.md
"""

import os
import sys
import json
import argparse
from pathlib import Path
from PIL import Image

# =============================================================================
# CONFIGURATION
# =============================================================================

ATLAS_MAX_SIZE = 8192       # Max texture dimension — 384×512 frames need larger atlases
PADDING = 4                 # Pixels between frames (prevent bleeding, larger for 4K frames)

# LOD scales
LODS = {
    "LOD0": 1.0,
    "LOD1": 0.5,
    "LOD2": 0.25,
}


# =============================================================================
# PACKING LOGIC (Shelf Algorithm)
# =============================================================================


def shelf_pack(images: dict, max_width: int = ATLAS_MAX_SIZE, padding: int = PADDING) -> tuple:
    """
    Simple shelf-packing algorithm.
    images: dict of name -> PIL.Image
    Returns (atlas_image, metadata_dict)
    """
    # Sort by height descending for better packing
    items = sorted(images.items(), key=lambda kv: kv[1].height, reverse=True)

    # Current shelf info
    atlas_width = 0
    atlas_height = 0
    current_shelf_y = 0
    current_shelf_height = 0
    current_shelf_x = 0

    placements = {}  # name -> (x, y, w, h)

    for name, img in items:
        w = img.width + padding
        h = img.height + padding

        # If it doesn't fit on current shelf, start new shelf
        if current_shelf_x + w > max_width:
            current_shelf_y += current_shelf_height
            current_shelf_x = 0
            current_shelf_height = 0

        # If starting new shelf exceeds max height, fail (or increase atlas size)
        if current_shelf_y + h > max_width:
            return None, None  # Signal to caller: need larger atlas

        # Place image
        placements[name] = (current_shelf_x, current_shelf_y, img.width, img.height)
        current_shelf_x += w
        current_shelf_height = max(current_shelf_height, h)
        atlas_width = max(atlas_width, current_shelf_x)
        atlas_height = max(atlas_height, current_shelf_y + current_shelf_height)

    # Trim atlas to power-of-two if desired (useful for WebGL/GPU)
    # For IoA's React frontend, exact size is fine.
    atlas_width = (atlas_width + 3) & ~3  # Align to 4 pixels
    atlas_height = (atlas_height + 3) & ~3

    atlas = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))
    metadata = {
        "frames": {},
        "meta": {
            "format": "RGBA8888",
            "size": {"w": atlas_width, "h": atlas_height},
            "scale": 1.0,
        }
    }

    for name, (x, y, w, h) in placements.items():
        img = images[name]
        atlas.paste(img, (x, y), img)
        metadata["frames"][name] = {
            "frame": {"x": x, "y": y, "w": w, "h": h},
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
            "pivot": {"x": 0.5, "y": 1.0},  # Bottom-center origin
        }

    return atlas, metadata


def build_lod_atlas(src_atlas: Image.Image, scale: float) -> Image.Image:
    """Downscale atlas for LOD generation."""
    new_w = int(src_atlas.width * scale)
    new_h = int(src_atlas.height * scale)
    # Use LANCZOS for smooth detail preservation at lower LODs
    return src_atlas.resize((new_w, new_h), Image.LANCZOS)


def pack_unit(source_dir: str, output_dir: str, unit_name: str):
    """Pack all frames from a processed render directory into atlases."""
    src = Path(source_dir)
    images = {}

    print(f"Scanning {src}...")
    for png_file in src.rglob("*.png"):
        rel = png_file.relative_to(src)
        # Name format: anim_dir/frame_XX.png -> anim_dir_frame_XX
        name = str(rel).replace(os.sep, "_").replace(".png", "")
        img = Image.open(png_file)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        images[name] = img

    if not images:
        print(f"  WARNING: No images found in {source_dir}")
        return

    print(f"  Found {len(images)} frames. Packing...")

    # Pack LOD0
    atlas, meta = shelf_pack(images)
    if atlas is None:
        print(f"  ERROR: Could not pack into {ATLAS_MAX_SIZE}x{ATLAS_MAX_SIZE}. Increase limit or split animations.")
        return

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Save LOD0
    atlas_path = out / f"{unit_name}_atlas.png"
    meta_path = out / f"{unit_name}_atlas.json"
    atlas.save(atlas_path, "PNG")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Saved LOD0: {atlas_path} ({atlas.width}x{atlas.height})")

    # Generate LODs
    for lod_label, lod_scale in LODS.items():
        if lod_scale == 1.0:
            continue
        lod_atlas = build_lod_atlas(atlas, lod_scale)
        lod_atlas_path = out / f"{unit_name}_atlas_{lod_label.lower()}.png"
        lod_meta = meta.copy()
        lod_meta["meta"]["scale"] = lod_scale
        lod_meta["meta"]["size"] = {"w": lod_atlas.width, "h": lod_atlas.height}
        # Adjust frame coordinates
        for fname in lod_meta["frames"]:
            frm = lod_meta["frames"][fname]["frame"]
            for k in ["x", "y", "w", "h"]:
                frm[k] = int(frm[k] * lod_scale)
            src_size = lod_meta["frames"][fname]["sourceSize"]
            src_size["w"] = int(src_size["w"] * lod_scale)
            src_size["h"] = int(src_size["h"] * lod_scale)

        lod_atlas.save(lod_atlas_path, "PNG")
        with open(out / f"{unit_name}_atlas_{lod_label.lower()}.json", "w") as f:
            json.dump(lod_meta, f, indent=2)
        print(f"  Saved {lod_label}: {lod_atlas_path} ({lod_atlas.width}x{lod_atlas.height})")


def main():
    parser = argparse.ArgumentParser(description="Pack processed sprites into atlases")
    parser.add_argument("--source", required=True, help="Directory containing processed frame PNGs")
    parser.add_argument("--output", required=True, help="Directory to write atlas PNG + JSON")
    parser.add_argument("--name", required=True, help="Unit/asset name prefix for output files")
    args = parser.parse_args()

    pack_unit(args.source, args.output, args.name)


if __name__ == "__main__":
    main()
