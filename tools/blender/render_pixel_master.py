#!/usr/bin/env python3
"""render_pixel_master.py — capture the 8-direction pixel master from a baked,
palette-locked GLB.

This is the last 3D stage of the `pixel_3d` route and it is deliberately thin:
the look is decided by the texel-grid atlas (bake_pixel_atlas.py) and the palette
lock (palette_lock.py). This script only guarantees the capture conditions the
technique needs — one constant scale across the set, no antialiasing, flat
shading, and normal/AO/emission masks saved as data.

    tools/blender_run.sh --job render -- -b -P tools/blender/render_pixel_master.py -- \
        --glb output/gen/<asset>/<asset>_pixel.glb --out output/gen/<asset> \
        --size 256 --directions 8 --masks --anchor bottom

Follow with:
    python3 tools/style/palette_lock.py --dir <out>/render --profile pixel_3d \
        --dither bayer4 --out-dir <out>/pixel_masters --suffix ""
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import master_render  # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id", help="asset id (default: glb stem without _pixel)")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--directions", type=int, default=8, choices=(1, 4, 8))
    ap.add_argument("--masks", action="store_true")
    ap.add_argument("--anchor", default="centre", choices=("centre", "bottom"))
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--emission-atlas", help="emission atlas PNG for the emission pass")
    ap.add_argument("--keep-smooth", action="store_true",
                    help="do not force flat shading (not the pixel look)")
    ap.add_argument("--exclude-mesh", action="append", default=[],
                    help="mesh object name to exclude from framing (still rendered)")
    ap.add_argument("--action", help="armature action to pose before framing")
    ap.add_argument("--frame", type=int, default=1)
    return ap.parse_args(argv)


def main():
    args = parse_args()
    glb = Path(args.glb).resolve()
    out = Path(args.out).resolve()
    asset_id = args.id or glb.stem.replace("_pixel", "")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]
    if not meshes:
        raise SystemExit(f"no mesh in {glb}")
    # a source GLB may carry helper geometry (the unit asset ships an Icosphere
    # proxy). Framing on it makes the character half the canvas, so the pose and
    # the frame must be chosen explicitly, not inherited from the importer.
    for arm in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        if args.action:
            act = bpy.data.actions.get(args.action)
            if act is None:
                raise SystemExit(f"no action '{args.action}' (have: "
                                 f"{sorted(a.name for a in bpy.data.actions)})")
            if arm.animation_data is None:
                arm.animation_data_create()
            arm.animation_data.action = act
    bpy.context.scene.frame_set(args.frame)
    bpy.context.view_layer.update()
    framing = [o for o in meshes if o.name not in set(args.exclude_mesh)]
    if not framing:
        raise SystemExit("every mesh was excluded from framing")
    if not args.keep_smooth:
        for o in meshes:
            for p in o.data.polygons:
                p.use_smooth = False

    emission = None
    if args.emission_atlas:
        p = Path(args.emission_atlas).resolve()
        if p.exists():
            emission = bpy.data.images.load(str(p), check_existing=False)
            emission.colorspace_settings.name = "sRGB"

    master_render.setup_studio(args.size, args.samples)
    result = master_render.render_master_set(
        meshes, out, asset_id, args.size, args.directions, args.masks,
        anchor=args.anchor, samples=args.samples, emission_atlas=emission,
        framing_objs=framing)

    (out / f"{asset_id}_render_meta.json").write_text(json.dumps({
        "asset": asset_id, "source": str(glb), "size_px": args.size,
        "directions": result["directions"], "anchor": args.anchor,
        "samples": args.samples, "masks": args.masks,
        "plans": result["plans"],
        "pose": {"action": args.action, "frame": args.frame},
        "excluded_from_framing": args.exclude_mesh,
        "note": "beauty frames are shaded colours; lock them with "
                "tools/style/palette_lock.py to reach palette compliance",
    }, indent=2) + "\n")
    print(f"RENDERED {result['directions']} dirs -> {out / 'render'}")


main()
