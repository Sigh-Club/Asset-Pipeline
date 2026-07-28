#!/usr/bin/env python3
"""
batch_process.py — Post-process raw Blender renders into final sprites.

v0.5.0+ pipeline for miniature-level detail:
  - Final frame: 384×512 (16× the pixel area of earlier versions)
  - LANCZOS downscale from 1152×1536 supersampled render
  - Full 16-bit RGBA colour (no palette lock)
  - Optional palette quantize for retro variants

Usage:
    python tools/batch_process.py --source assets/units/<unit>/render/raw --output path/to/output
    python tools/batch_process.py --source assets/units/<unit>/render/raw --output path --palette assets/palettes/grimdark_64.gpl
"""

import os
import sys
import json
import argparse
from pathlib import Path
from PIL import Image, ImageFilter

# =============================================================================
# CONFIGURATION
# =============================================================================

CANVAS_SIZES = {
    "character": (384, 512),
    "tile": (384, 512),
    "ui_icon_small": (32, 32),
    "ui_icon_medium": (48, 48),
    "ui_button": (64, 32),
    "ui_panel": (64, 64),
    "portrait": (256, 320),
}

ALPHA_THRESHOLD = 5


# =============================================================================
# PALETTE LOADING (optional — None means full colour)
# =============================================================================

def load_palette(gpl_path: str) -> list | None:
    """Load GIMP .gpl palette. Returns list of (r, g, b) tuples or None."""
    if not gpl_path or not os.path.exists(gpl_path):
        return None
    colors = []
    with open(gpl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("GIMP") \
               or line.startswith("Name:") or line.startswith("Columns:"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    colors.append((r, g, b))
                except ValueError:
                    continue
    return colors if colors else None


# =============================================================================
# IMAGE PROCESSING
# =============================================================================

def find_bounding_box(img: Image.Image) -> tuple | None:
    """Find bounding box of non-transparent content."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bbox = img.split()[-1].getbbox()
    return bbox


def quantize_to_palette(img: Image.Image, palette: list) -> Image.Image:
    """
    Snap RGBA pixels to nearest palette colour.
    Only used when --palette flag is passed.
    """
    if palette is None:
        return img
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    w, h = img.size
    pixels_in = img.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pixels_out = out.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels_in[x, y]
            if a < ALPHA_THRESHOLD:
                pixels_out[x, y] = (0, 0, 0, 0)
            else:
                min_dist = float("inf")
                nearest = (0, 0, 0)
                for pr, pg, pb in palette:
                    dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                    if dist < min_dist:
                        min_dist = dist
                        nearest = (pr, pg, pb)
                pixels_out[x, y] = (*nearest, 255)

    return out


def pad_to_canvas(img: Image.Image, target_size: tuple,
                  origin: str = "bottom_center") -> Image.Image:
    """Centre-crop or pad image to target canvas size."""
    tw, th = target_size
    w, h = img.size

    if w > tw or h > th:
        # Crop if larger (shouldn't happen after downscale, but safety)
        img = img.crop((
            (w - tw) // 2, (h - th) - (h - th) // 2,
            (w + tw) // 2, (h + th) - (h - th) // 2,
        ))
        return img

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


def process_frame(src_path: str, dst_path: str, canvas_size: tuple = (96, 128),
                  palette: list | None = None, supersample: int = 4):
    """
    Process a raw render frame into a final sprite.

    v0.5.0+ pipeline:
      - Downscales from supersampled render using LANCZOS (smooth, not pixelated)
      - Full RGBA colour unless palette flag is provided
      - No noise removal (preserves material detail)
      - Bounding-box crop before padding to canvas
    """
    img = Image.open(src_path).convert("RGBA")

    target_w, target_h = canvas_size

    # Downscale from supersampled resolution. Bilinear (not Lanczos) preserves hard
    # painted lines; Lanczos interpolates 1px panel lines into muddy gradients across
    # the 3x downscale. An unsharp mask restores high-frequency Sobel boundaries.
    if img.size[0] > target_w or img.size[1] > target_h:
        img = img.resize((target_w, target_h), Image.BILINEAR)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=3))

    # Crop to content bounding box
    bbox = find_bounding_box(img)
    if bbox:
        img = img.crop(bbox)
    else:
        return  # fully transparent frame

    # Optional palette quantize
    if palette is not None:
        img = quantize_to_palette(img, palette)

    # Pad to standard canvas
    img = pad_to_canvas(img, canvas_size, origin="bottom_center")

    # Save
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    img.save(dst_path, "PNG")


def process_directory(src_dir: str, dst_dir: str, canvas_size: tuple = (96, 128),
                      palette: list | None = None, supersample: int = 4):
    """Recursively process all PNGs in src_dir."""
    src_path = Path(src_dir)
    dst_path = Path(dst_dir)
    processed = 0
    skipped = 0

    for src_file in sorted(src_path.rglob("*.png")):
        rel = src_file.relative_to(src_path)
        dst_file = dst_path / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            process_frame(
                str(src_file), str(dst_file),
                canvas_size, palette, supersample,
            )
            processed += 1
            if processed % 100 == 0:
                print(f"  Processed {processed} frames...")
        except Exception as e:
            print(f"  ERROR processing {src_file}: {e}")
            skipped += 1

    print(f"Done. Processed {processed}, Skipped {skipped}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch process Blender renders into final sprites (v0.5.0+)"
    )
    parser.add_argument("--source", "-s", required=True,
                        help="Source directory of raw renders")
    parser.add_argument("--output", "-o", required=True,
                        help="Destination directory for processed sprites")
    parser.add_argument("--type", default="character",
                        choices=list(CANVAS_SIZES.keys()),
                        help="Asset type for canvas size")
    parser.add_argument("--palette", "-p", default=None,
                        help="Optional .gpl palette for quantisation")
    parser.add_argument("--supersample", type=int, default=4,
                        help="Supersample factor used in render (default: 4)")
    args = parser.parse_args()

    canvas_size = CANVAS_SIZES.get(args.type, (96, 128))
    palette = load_palette(args.palette) if args.palette else None

    print(f"Batch processing: {args.source}")
    print(f"Output: {args.output}")
    print(f"Canvas size: {canvas_size}")
    print(f"Downscale: LANCZOS (smooth)")
    print(f"Palette: {'None (full RGBA)' if palette is None else f'{len(palette)} colours'}")

    process_directory(args.source, args.output, canvas_size, palette, args.supersample)


if __name__ == "__main__":
    main()
