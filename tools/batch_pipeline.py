#!/usr/bin/env python3
"""batch_pipeline.py — Post-process and pack all unit renders in one pass."""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools", "packer"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools", "gimp"))

from batch_pixelate import process_frame
from pack_sprites import pack_unit

# Allow override via PIPELINE_VERSION env var (set by pipeline_cli.py)
DEFAULT_VERSION = "v0.3.0"
PIPELINE_VERSION = os.environ.get("PIPELINE_VERSION", DEFAULT_VERSION)

UNITS_DIR = os.path.join(PROJECT_ROOT, "assets", "units")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", PIPELINE_VERSION)
FRAME_SIZE = (96, 128)


def find_units_with_renders():
    units = []
    for unit_dir in sorted(os.listdir(UNITS_DIR)):
        raw_dir = os.path.join(UNITS_DIR, unit_dir, "model", "render", "raw")
        if os.path.isdir(raw_dir):
            png_count = sum(1 for r, d, f in os.walk(raw_dir) for fn in f if fn.endswith(".png"))
            if png_count > 0:
                units.append((unit_dir, raw_dir, png_count))
    return units


def process_unit(unit_name, raw_dir, frame_count):
    print(f"\n{'='*60}")
    print(f"Processing: {unit_name} ({frame_count} raw frames)")
    print(f"{'='*60}")

    pixelated_dir = os.path.join(UNITS_DIR, unit_name, "model", "render", "pixelated")

    processed = 0
    for root, dirs, files in os.walk(raw_dir):
        for f in sorted(files):
            if not f.endswith(".png"):
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(root, raw_dir)
            dst_dir = os.path.join(pixelated_dir, rel)
            dst = os.path.join(dst_dir, f)
            os.makedirs(dst_dir, exist_ok=True)
            process_frame(src, dst, FRAME_SIZE)
            processed += 1

    print(f"  Processed {processed} frames")

    atlas_name = f"{unit_name}_atlas"
    pack_unit(pixelated_dir, OUTPUT_DIR, atlas_name)
    print(f"  Atlas: {os.path.join(OUTPUT_DIR, atlas_name)}.png")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    units = find_units_with_renders()
    print(f"Found {len(units)} units with renders")

    for unit_name, raw_dir, count in units:
        try:
            process_unit(unit_name, raw_dir, count)
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