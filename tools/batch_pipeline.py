#!/usr/bin/env python3
"""batch_pipeline.py — Post-process and pack all unit renders in one pass.

v0.5.0+ pipeline shift:
  - Uses batch_process.py (LANCZOS smooth downscale, full RGBA colour)
  - No strict palette quantisation (optional via --palette)
  - Same pack_sprites.py atlas packing
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools", "packer"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools", "gimp"))

from batch_process import process_frame
from pack_sprites import pack_unit

# Allow override via PIPELINE_VERSION env var (set by pipeline_cli.py)
DEFAULT_VERSION = "v0.4.0"
PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", DEFAULT_VERSION)

UNITS_DIR = os.path.join(PROJECT_ROOT, "assets", "units")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", PIPELINE_VERSION)
FRAME_SIZE = (384, 512)
PALETTE_PATH = os.path.join(PROJECT_ROOT, "assets", "palettes", "grimdark_64.gpl")


def find_units_with_renders():
    units = []
    for unit_dir in sorted(os.listdir(UNITS_DIR)):
        raw_dir = os.path.join(UNITS_DIR, unit_dir, "model", "render", "raw")
        if os.path.isdir(raw_dir):
            png_count = sum(1 for r, d, f in os.walk(raw_dir) for fn in f if fn.endswith(".png"))
            if png_count > 0:
                units.append((unit_dir, raw_dir, png_count))
    return units


def load_palette(gpl_path):
    """Load optional palette for quantisation."""
    if not os.path.exists(gpl_path):
        return None
    from batch_process import load_palette as _load
    return _load(gpl_path)


def process_unit(unit_name, raw_dir, frame_count, palette=None):
    print(f"\n{'='*60}")
    print(f"Processing: {unit_name} ({frame_count} raw frames)")
    print(f"{'='*60}")

    processed_dir = os.path.join(UNITS_DIR, unit_name, "model", "render", "processed")

    processed = 0
    for root, dirs, files in os.walk(raw_dir):
        for f in sorted(files):
            if not f.endswith(".png"):
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(root, raw_dir)
            dst_dir = os.path.join(processed_dir, rel)
            dst = os.path.join(dst_dir, f)
            os.makedirs(dst_dir, exist_ok=True)
            process_frame(src, dst, FRAME_SIZE, palette=palette)
            processed += 1

    print(f"  Processed {processed} frames")

    # NOTE: pack_unit appends _atlas suffix itself — don't double it
    pack_unit(processed_dir, OUTPUT_DIR, unit_name)
    print(f"  Atlas: {os.path.join(OUTPUT_DIR, unit_name)}_atlas.png")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch process + pack all unit renders")
    parser.add_argument("--palette", "-p", default=None,
                        help="Optional .gpl palette for quantisation")
    args = parser.parse_args()

    palette = load_palette(args.palette or PALETTE_PATH) if args.palette else None
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    units = find_units_with_renders()
    print(f"Found {len(units)} units with renders")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Colour: {'Full RGBA' if palette is None else f'Palette ({len(palette)} colours)'}")

    for unit_name, raw_dir, count in units:
        try:
            process_unit(unit_name, raw_dir, count, palette)
        except Exception as e:
            print(f"  ERROR processing {unit_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n{'='*60}")
    print(f"Batch complete. Output in {OUTPUT_DIR}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
