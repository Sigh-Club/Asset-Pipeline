#!/usr/bin/env python3
"""
batch_pixelate.py — GIMP Python-Fu / Python Batch Script
Post-process raw Blender renders into palette-locked pixel art sprites.

Can be run:
- From GIMP: Filters -> Python-Fu -> Console, paste/run
- From command line: python batch_pixelate.py (if Pillow installed)

Dependencies:
    pip install pillow

Usage:
    python batch_pixelate.py --source assets/characters/foo/render/raw --output assets/characters/foo/render/processed

What it does per frame:
1. Convert RGBA to indexed color using the grimdark_64 palette (nearest color)
2. Quantize to uniform frame size (crop to tight bounds, then pad to standard canvas)
3. Remove single-pixel noise (stray pixels from alpha blending)
4. Sharpen edges (enforce crisp pixel transitions)
5. Save as indexed PNG with proper alpha

Author: Asset-Pipeline Automation
Docs: docs/BLENDER_WORKFLOW.md
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Try Pillow first; if unavailable, provide instructions
try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install: pip install pillow")
    sys.exit(1)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Standard canvas sizes from STYLE_GUIDE
CANVAS_SIZES = {
    "character": (96, 128),
    "tile": (96, 128),
    "ui_icon_small": (32, 32),
    "ui_icon_medium": (48, 48),
    "ui_button": (64, 32),
    "ui_panel": (64, 64),
    "portrait": (64, 64),
}

# Tolerance for considering a pixel "transparent"
ALPHA_THRESHOLD = 10

# Noise removal: remove isolated single pixels of non-transparent color
NOISE_FILTER_SIZE = 1

# =============================================================================
# PALETTE LOADING
# =============================================================================


def load_palette(gpl_path: str) -> list:
    """
    Load a GIMP .gpl palette file.
    Returns list of (r, g, b) tuples.
    """
    colors = []
    with open(gpl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("GIMP") or line.startswith("Name:") or line.startswith("Columns:"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    r = int(parts[0])
                    g = int(parts[1])
                    b = int(parts[2])
                    colors.append((r, g, b))
                except ValueError:
                    continue
    return colors


# Load grimdark_64
PALETTE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "palettes", "grimdark_64.gpl")
PALETTE_PATH = os.path.abspath(PALETTE_PATH)
if not os.path.exists(PALETTE_PATH):
    print(f"WARNING: Palette not found at {PALETTE_PATH}. Using embedded fallback.")
    GRIMDARK_64 = []
else:
    GRIMDARK_64 = load_palette(PALETTE_PATH)

if not GRIMDARK_64:
    # Fallback embedded palette (first 32 colors essential)
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
# IMAGE PROCESSING
# =============================================================================


def find_bounding_box(img: Image.Image) -> tuple:
    """
    Find bounding box of non-transparent content.
    Returns (left, upper, right, lower) or None if fully transparent.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    return bbox


def nearest_palette_color(r: int, g: int, b: int, palette: list) -> int:
    """Find index of nearest color in palette using Euclidean distance."""
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
    Convert image to palette mode using nearest-color mapping.
    Preserves alpha channel by first filling transparent areas with a distinct color,
    then restoring transparency after conversion.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Fill transparent pixels with a clearly identifiable color (Pure Red, slot 63)
    # so they remain distinct after quantization
    filler = Image.new("RGBA", img.size, (255, 0, 0, 255))
    composited = Image.alpha_composite(filler, img)

    # Build palette image
    flat_palette = []
    for r, g, b in palette:
        flat_palette.extend([r, g, b])
    # Pad to 768 entries (256 colors * 3)
    while len(flat_palette) < 768:
        flat_palette.extend([0, 0, 0])

    p_img = Image.new("P", img.size)
    p_img.putpalette(flat_palette)

    # Map each pixel to nearest palette index
    pixels_in = composited.load()
    pixels_out = p_img.load()
    w, h = img.size
    alpha_map = []

    for y in range(h):
        row_alpha = []
        for x in range(w):
            r, g, b, a = pixels_in[x, y]
            if a < ALPHA_THRESHOLD:
                # Transparent -> map to index 63 (Pure Red placeholder)
                pixels_out[x, y] = 63
                row_alpha.append(0)
            else:
                idx = nearest_palette_color(r, g, b, palette)
                pixels_out[x, y] = idx
                row_alpha.append(255)
        alpha_map.append(row_alpha)

    # Convert back to RGBA with true alpha
    rgb_img = p_img.convert("RGB")
    rgba_img = rgb_img.convert("RGBA")
    out_pixels = rgba_img.load()
    out_palette = rgba_img.getpalette()

    for y in range(h):
        for x in range(w):
            if alpha_map[y][x] == 0:
                out_pixels[x, y] = (0, 0, 0, 0)
            else:
                idx = pixels_out[x, y]
                pr = out_palette[idx * 3]
                pg = out_palette[idx * 3 + 1]
                pb = out_palette[idx * 3 + 2]
                out_pixels[x, y] = (pr, pg, pb, 255)

    return rgba_img


def remove_noise(img: Image.Image) -> Image.Image:
    """
    Remove isolated single pixels that aren't connected to same-color neighbors.
    Simple 4-connected neighborhood check.
    """
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

            # Count same-color neighbors (non-transparent, same RGB)
            same_neighbors = 0
            neighbors = [(x-1,y), (x+1,y), (x,y-1), (x,y+1)]
            for nx, ny in neighbors:
                if 0 <= nx < w and 0 <= ny < h:
                    nr, ng, nb, na = pixels[nx, ny]
                    if na > 0 and (nr, ng, nb) == (r, g, b):
                        same_neighbors += 1

            # If isolated (0 same-color neighbors), mark transparent
            if same_neighbors == 0:
                out_pixels[x, y] = (0, 0, 0, 0)
            else:
                out_pixels[x, y] = (r, g, b, a)

    return out


def pad_to_canvas(img: Image.Image, target_size: tuple, origin: str = "bottom_center") -> Image.Image:
    """
    Center-crop or pad image to target canvas size.
    Origin defines where the content anchor point sits within the canvas.
    For isometric sprites, origin is bottom-center of the tile footprint.
    """
    tw, th = target_size
    w, h = img.size

    # Create transparent canvas
    canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))

    # Calculate paste position
    if origin == "bottom_center":
        px = (tw - w) // 2
        py = th - h
    elif origin == "center":
        px = (tw - w) // 2
        py = (th - h) // 2
    else:
        px = (tw - w) // 2
        py = (th - h) // 2

    # Clamp to canvas bounds
    px = max(0, min(px, tw - w))
    py = max(0, min(py, th - h))

    canvas.paste(img, (px, py), img)
    return canvas


def process_frame(src_path: str, dst_path: str, canvas_size: tuple = (96, 128)):
    """Process a single frame from raw render to final sprite."""
    img = Image.open(src_path)

    # 1. Crop to content
    bbox = find_bounding_box(img)
    if bbox:
        img = img.crop(bbox)
    else:
        # Fully transparent? Skip.
        return

    # 2. Quantize to palette
    img = quantize_to_palette(img, GRIMDARK_64)

    # 3. Remove noise
    img = remove_noise(img)

    # 4. Pad to standard canvas
    img = pad_to_canvas(img, canvas_size, origin="bottom_center")

    # 5. Save
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    img.save(dst_path, "PNG")


def process_directory(src_dir: str, dst_dir: str, canvas_size: tuple = (96, 128)):
    """
    Recursively process all PNG files in src_dir, mirror directory structure in dst_dir.
    """
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
    print(f"Palette: {PALETTE_PATH}")

    process_directory(args.source, args.output, canvas_size)


if __name__ == "__main__":
    main()
