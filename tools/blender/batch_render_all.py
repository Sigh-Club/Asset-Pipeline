#!/usr/bin/env python3
"""
batch_render_all.py — Batch 8-Direction Rendering for All Characters
Scans assets/characters/ for .blend files and runs render_8dir.py on each.

Usage:
    python batch_render_all.py

Optional environment variables:
    BLENDER_PATH=/usr/bin/blender (default: "blender")

Author: Asset-Pipeline Automation
"""

import os
import sys
import subprocess
from pathlib import Path

BLENDER_CMD = os.environ.get("BLENDER_PATH", "blender")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "characters"
RENDER_SCRIPT = Path(__file__).resolve().parent / "render_8dir.py"


def find_blend_files() -> list:
    """Recursively find all .blend model files."""
    blends = []
    if not ASSETS_DIR.exists():
        print(f"WARNING: Assets directory not found: {ASSETS_DIR}")
        return blends
    for model_dir in ASSETS_DIR.iterdir():
        if model_dir.is_dir():
            blend_dir = model_dir / "model"
            if blend_dir.exists():
                for f in blend_dir.glob("*.blend"):
                    blends.append(f)
    return blends


def render_blend(blend_path: Path):
    """Run Blender background render on a single .blend file."""
    cmd = [
        BLENDER_CMD,
        str(blend_path),
        "--background",
        "--python", str(RENDER_SCRIPT),
    ]
    print(f"Rendering: {blend_path.name}")
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"  ERROR: Blender exited with code {result.returncode}")
        return False
    print(f"  SUCCESS: {blend_path.name}")
    return True


def main():
    blends = find_blend_files()
    if not blends:
        print("No .blend files found. Nothing to render.")
        sys.exit(0)

    print(f"Found {len(blends)} .blend file(s):")
    for b in blends:
        print(f"  - {b}")

    success = 0
    fail = 0
    for blend in blends:
        if render_blend(blend):
            success += 1
        else:
            fail += 1

    print(f"\nBatch render complete: {success} succeeded, {fail} failed.")


if __name__ == "__main__":
    main()
