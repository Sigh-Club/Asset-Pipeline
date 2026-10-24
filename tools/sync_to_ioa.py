#!/usr/bin/env python3
"""
sync_to_ioa.py — Extract atlas frames into individual PNGs for IoA compatibility.

IoA expects: `/assets/units/<faction>_<unit>_<direction>.png`
Our atlas has: `idle/N/frame_01.png`, `idle/N/frame_02.png`, etc.

This tool:
  1. Reads atlas JSON
  2. Extracts `idle` state, frame 01 for each direction
  3. Saves as `<faction>_<unit>_<direction>.png`
  4. Copies to IoA `frontend/public/assets/units/`

Later when IoA supports animations, we can export all frames.

Usage:
    python tools/sync_to_ioa.py \
        --atlas output/v0.1.0/characters/iron_line_infantry/iron_line_infantry_atlas.json \
        --target /home/talzanar/Projects/Imperium\ of\ Ash/frontend/public/assets/units/
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from PIL import Image


def load_atlas_json(atlas_path: str) -> dict:
    """Read atlas metadata."""
    with open(atlas_path) as f:
        return json.load(f)


def extract_idle_frames(atlas_json: dict, atlas_png_path: str, out_dir: str) -> list:
    """
    Extract idle frame 01 for each direction from atlas.
    Returns list of extracted file paths.
    """
    atlas_img = Image.open(atlas_png_path).convert("RGBA")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    extracted = []
    frames = atlas_json.get("frames", [])
    
    for frame_info in frames:
        filename = frame_info.get("filename", "")
        # Only extract idle/01 frames
        if "idle" in filename and "frame_01" in filename:
            # Parse direction from filename: idle/N/frame_01.png
            parts = filename.split("/")
            if len(parts) >= 3:
                direction = parts[1]
            else:
                continue
            
            # Get frame position in atlas
            frame_data = frame_info.get("frame", {})
            x = frame_data.get("x", 0)
            y = frame_data.get("y", 0)
            w = frame_data.get("w", 96)
            h = frame_data.get("h", 128)
            
            # Extract
            sprite = atlas_img.crop((x, y, x + w, y + h))
            
            # Build output name from atlas name + direction
            atlas_name = Path(atlas_png_path).stem.replace("_atlas", "")
            out_name = f"{atlas_name}_{direction}.png"
            out_path = out_dir / out_name
            
            sprite.save(out_path)
            extracted.append(str(out_path))
            print(f"  Extracted {filename} -> {out_name}")
    
    return extracted


def copy_to_ioa(extracted_paths: list, ioa_units_dir: str) -> None:
    """Copy extracted frames to IoA public assets."""
    target = Path(ioa_units_dir)
    target.mkdir(parents=True, exist_ok=True)
    
    for src in extracted_paths:
        src_path = Path(src)
        dst = target / src_path.name
        shutil.copy2(src, dst)
        print(f"  Copied to IoA: {dst}")


def generate_placeholder_tiles(ioa_tiles_dir: str) -> None:
    """
    Generate basic tile images if IoA doesn't have them.
    Creates simple colored diamonds for testing.
    """
    target = Path(ioa_tiles_dir)
    target.mkdir(parents=True, exist_ok=True)
    
    tiles = {
        "normal": (74, 74, 74),      # Battle grey
        "cover": (90, 74, 60),       # Leather
        "heavy_cover": (60, 60, 60), # Gunmetal
        "impassable": (10, 10, 10),  # Void black
    }
    
    for name, color in tiles.items():
        path = target / f"{name}.png"
        if not path.exists():
            img = Image.new("RGBA", (96, 48), (*color, 255))
            img.save(path)
            print(f"  Generated tile: {name}.png")


def main():
    parser = argparse.ArgumentParser(description="Sync asset-pipeline to IoA repo")
    parser.add_argument("--atlas-json", required=True, help="Atlas JSON path")
    parser.add_argument("--atlas-png", required=True, help="Atlas PNG path")
    parser.add_argument("--ioa-dir", required=True, help="IoA frontend/public path")
    parser.add_argument("--units-only", action="store_true", help="Only sync units")
    args = parser.parse_args()
    
    ioa_units = os.path.join(args.ioa_dir, "assets", "units")
    ioa_tiles = os.path.join(args.ioa_dir, "assets", "tiles")
    
    print(f"[sync] Extracting from {args.atlas_png}")
    # Use a temp dir relative to the atlas location — not a hardcoded v0.1.0 path
    temp_dir = os.path.join(os.path.dirname(args.atlas_png), "..", "ioa_temp")
    temp_dir = os.path.abspath(temp_dir)
    extracted = extract_idle_frames(
        load_atlas_json(args.atlas_json),
        args.atlas_png,
        temp_dir
    )
    
    if extracted:
        print(f"[sync] Copying {len(extracted)} frames to IoA...")
        copy_to_ioa(extracted, ioa_units)
    
    if not args.units_only:
        print(f"[sync] Checking tiles...")
        generate_placeholder_tiles(ioa_tiles)
    
    print(f"[sync] Done. IoA assets ready for testing.")


if __name__ == "__main__":
    main()


# =============================================================================
# H1 full-state sync (review 2026-10-23): deliver EVERY animation state to the
# game, renamed to the game's contract (idle/walk/attack/hit/death — the
# pipeline renders `hurt`/`die`). Rewrites the frame KEYS in the atlas JSON and
# copies the pair into the game's atlases dir. The atlas PNG is untouched.
GAME_STATE_MAP = {"hurt": "hit", "die": "death",
                  # legacy walk/death state names (2026-10-24: the wide-5 pack
                  # and the pre-rename bakes use pipeline-native verbs)
                  "scuttle": "walk", "move": "walk", "destroy": "death"}


def sync_full_atlas(atlas_png: Path, atlas_json: Path, game_atlases_dir: Path) -> int:
    """Copy a packed atlas into the game with combat states mapped. Returns the
    number of frames written."""
    meta = json.loads(atlas_json.read_text())
    frames = meta.get("frames", {})
    renamed = {}
    for key, entry in frames.items():
        # key shape: <state>_<DIR>_frame_NN
        parts = key.split("_")
        if not parts:
            renamed[key] = entry
            continue
        state = parts[0]
        state = GAME_STATE_MAP.get(state, state)
        renamed["_".join([state] + parts[1:])] = entry
    meta["frames"] = renamed

    out_dir = Path(game_atlases_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / atlas_json.name).write_text(json.dumps(meta, indent=2))
    shutil.copy2(atlas_png, out_dir / atlas_png.name)

    # LOD companions: same key treatment so the lod1 primary sheet carries the
    # combat states too (the boot-perf programme loads lod1 as primary).
    for lod in ("lod1", "lod2"):
        lod_json = atlas_json.parent / (atlas_json.name.replace("_atlas.json", f"_atlas_{lod}.json"))
        lod_png = atlas_png.parent / (atlas_png.name.replace("_atlas.png", f"_atlas_{lod}.png"))
        if lod_json.exists() and lod_png.exists():
            lmeta = json.loads(lod_json.read_text())
            lframes = lmeta.get("frames", {})
            lrenamed = {}
            for key, entry in lframes.items():
                parts = key.split("_")
                st = parts[0] if parts else ""
                st = GAME_STATE_MAP.get(st, st)
                lrenamed["_".join([st] + parts[1:])] = entry
            lmeta["frames"] = lrenamed
            (out_dir / lod_json.name).write_text(json.dumps(lmeta, indent=2))
            shutil.copy2(lod_png, out_dir / lod_png.name)
    return len(renamed)


def sync_all_processed(units_root: Path, game_root: Path, only_slugs=None) -> dict:
    """Walk processed/ trees, pack nothing new: for every unit with a packed
    atlas already present, sync full states. Returns a per-unit report."""
    report = {}
    atlases = units_root.parent.glob("**/*_atlas.png")  # not used; kept explicit below
    for packed in Path(units_root).rglob("*_atlas.json"):
        unit_dir = packed.parent
        # derive the game slug from the unit dir name two levels up
        if "processed" not in str(packed):
            continue
        slug = unit_dir.name.replace("_final", "")
        png = unit_dir / (unit_dir.name + "_atlas.png")
        if not png.exists():
            continue
        if only_slugs and slug not in only_slugs:
            continue
        game_atlases = game_root / "frontend" / "public" / "assets" / "atlases"
        n = sync_full_atlas(png, packed, game_atlases)
        report[slug] = n
    return report
