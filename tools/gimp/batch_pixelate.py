#!/usr/bin/env python3
"""
batch_pixelate.py — GIMP Python-Fu / Python Batch Script
Post-process raw Blender renders into palette-locked pixel art sprites.

Usage:
    python batch_pixelate.py --source assets/characters/foo/render/raw --output assets/characters/foo/render/processed

FIXED VERSION: Proper nearest-color quantization without alpha bleed.
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

CANVAS_SIZES = {
    "character": (96, 128),
    "tile": (96, 128),
    "ui_icon_small": (32, 32),
    "ui_icon_medium": (48, 48),
    "ui_button": (64, 32),
    "ui_panel": (64, 64),
    "portrait": (64, 64),
}

ALPHA_THRESHOLD = 10

# =============================================================================
# PALETTE LOADING
# =============================================================================


def load_palette(gpl_path: str) -> list:
    """Load GIMP .gpl palette. Returns list of (r, g, b) tuples."""
    colors = []
    with open(gpl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("GIMP") or line.startswith("Name:") or line.startswith("Columns:"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    colors.append((r, g, b))
                except ValueError:
                    continue
    return colors


PALETTE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "palettes", "grimdark_64.gpl")
PALETTE_PATH = os.path.abspath(PALETTE_PATH)
if not os.path.exists(PALETTE_PATH):
    print(f"WARNING: Palette not found at {PALETTE_PATH}")
    GRIMDARK_64 = []
else:
    GRIMDARK_64 = load_palette(PALETTE_PATH)

if not GRIMDARK_64:
    # Fallback embedded first 32
    GRIMDARK_64 = [
        (10, 10, 10), (20, 20, 20), (30, 30, 30), (40, 40, 40),
        (50, 50, 50), (70, 60, 50), (90, 74, 60), (110, 94, 76),
        (139, 45, 45), (166, 58, 58), (193, 71, 71), (212, 160, 36),
        (232, 200, 72), (240, 232, 160), (140, 112, 56), (168, 132, 72),
        (196, 160, 88), (60, 90, 60), (78, 120, 78), (96, 150, 96),
        (42, 42, 60), (60, 60, 84), (78, 78, 108), (92, 64, 52),
        (120, 84, 60), (148, 104, 72), (176, 124, 84), (232, 224, 212),
        (200, 192, 180), (168, 160, 148), (232, 208, 0), (184, 168, 0),
    ]


# =============================================================================
# IMAGE PROCESSING (FIXED)
# =============================================================================


def find_bounding_box(img: Image.Image) -> tuple:
    """Find bounding box of non-transparent content."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    return bbox


def nearest_palette_color(r: int, g: int, b: int, palette: list) -> int:
    """Find nearest color index using Euclidean distance in RGB space."""
    min_dist = float('inf')
    nearest_idx = 0
    for idx, (pr, pg, pb) in enumerate(palette):
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < min_dist:
            min_dist = dist
            nearest_idx = idx
    return nearest_idx


def quantize_to_palette(img: Image.Image, palette: list) -> Image.Image:
    """
    Convert RGBA image to palette-locked RGBA.
    - Transparent pixels stay transparent (alpha < threshold)
    - Opaque pixels snap to nearest palette colour
    - No red filler bleed-through
    
    STRICT: Always snap to nearest palette colour. PBR + Cycles renders
    produce colours close to palette values but may be off by 1-3 due to
    Filmic colour management, denoising, and anti-aliasing. Hard snap
    preserves palette purity for pixel-art style.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    w, h = img.size
    pixels_in = img.load()
    
    # Create output RGBA image
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pixels_out = out.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels_in[x, y]
            if a < ALPHA_THRESHOLD:
                pixels_out[x, y] = (0, 0, 0, 0)
            else:
                # Check if already close to palette (emission render)
                min_dist = float('inf')
                nearest = (0, 0, 0)
                for pr, pg, pb in palette:
                    dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                    if dist < min_dist:
                        min_dist = dist
                        nearest = (pr, pg, pb)
                
                # STRICT: Always snap to nearest palette color.
                # Emission renders should be exact palette hexes, but
                # EEVEE color management + AA may produce off-by-1 colors.
                # Hard snap preserves palette purity for pixel art style.
                pixels_out[x, y] = (*nearest, 255)

    return out


def remove_noise(img: Image.Image) -> Image.Image:
    """Remove isolated single pixels (4-connected neighborhood check)."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()
    out = Image.new("RGBA", img.size)
    out_pixels = out.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                out_pixels[x, y] = (0, 0, 0, 0)
                continue

            same_neighbors = 0
            neighbors = [(x-1,y), (x+1,y), (x,y-1), (x,y+1)]
            for nx, ny in neighbors:
                if 0 <= nx < w and 0 <= ny < h:
                    nr, ng, nb, na = pixels[nx, ny]
                    if na > 0 and (nr, ng, nb) == (r, g, b):
                        same_neighbors += 1

            if same_neighbors == 0:
                out_pixels[x, y] = (0, 0, 0, 0)
            else:
                out_pixels[x, y] = (r, g, b, a)

    return out


def pad_to_canvas(img: Image.Image, target_size: tuple, origin: str = "bottom_center") -> Image.Image:
    """Center-crop or pad image to target canvas size."""
    tw, th = target_size
    w, h = img.size

    canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))

    if origin == "bottom_center":
        px = (tw - w) // 2
        py = th - h
    elif origin == "center":
        px = (tw - w) // 2
        py = (th - h) // 2
    else:
        px = (tw - w) // 2
        py = (th - h) // 2

    px = max(0, min(px, tw - w))
    py = max(0, min(py, th - h))

    canvas.paste(img, (px, py), img)
    return canvas


def process_frame(src_path: str, dst_path: str, canvas_size: tuple = (96, 128)):
    """Process a single frame from raw render to final sprite.
    
    Handles both:
       Direct 96x128 renders (v1 pipeline)
       4x supersampled renders (384x512, v2 pipeline) downscales before quantization
    """
    img = Image.open(src_path)

    # 1. If image is larger than target, downscale with nearest-neighbor FIRST
    #    This preserves hard edges from the high-res render before palette quantization
    target_w, target_h = canvas_size
    if img.size[0] > target_w or img.size[1] > target_h:
        img = img.resize((target_w, target_h), Image.NEAREST)

    # 2. Crop to content
    bbox = find_bounding_box(img)
    if bbox:
        img = img.crop(bbox)
    else:
        return

    # 3. Quantize to palette
    img = quantize_to_palette(img, GRIMDARK_64)

    # 4. Remove noise
    img = remove_noise(img)

    # 5. Pad to standard canvas
    img = pad_to_canvas(img, canvas_size, origin="bottom_center")

    # 6. Save
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    img.save(dst_path, "PNG")


def process_directory(src_dir: str, dst_dir: str, canvas_size: tuple = (96, 128)):
    """Recursively process all PNGs in src_dir."""
    src_path = Path(src_dir)
    dst_path = Path(dst_dir)
    processed = 0
    skipped = 0

    for src_file in src_path.rglob("*.png"):
        rel = src_file.relative_to(src_path)
        dst_file = dst_path / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            process_frame(str(src_file), str(dst_file), canvas_size)
            processed += 1
            if processed % 100 == 0:
                print(f"  Processed {processed} frames...")
        except Exception as e:
            print(f"  ERROR processing {src_file}: {e}")
            skipped += 1

    print(f"Done. Processed {processed}, Skipped {skipped}")


def main():
    parser = argparse.ArgumentParser(description="Batch pixelate Blender renders")
    parser.add_argument("--source", required=True, help="Source directory of raw renders")
    parser.add_argument("--output", required=True, help="Destination directory for processed sprites")
    parser.add_argument("--type", default="character", choices=list(CANVAS_SIZES.keys()), help="Asset type for canvas size")
    args = parser.parse_args()

    canvas_size = CANVAS_SIZES.get(args.type, (96, 128))
    print(f"Batch pixelating: {args.source}")
    print(f"Output: {args.output}")
    print(f"Canvas size: {canvas_size}")
    print(f"Palette: {PALETTE_PATH} ({len(GRIMDARK_64)} colors)")

    process_directory(args.source, args.output, canvas_size)


if __name__ == "__main__":
    main()
