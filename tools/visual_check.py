"""visual_check.py — render a unit and judge it the way a person would.

Numeric gates have shipped broken models three times in this project: a jumble of
triangles still has valid UVs, a plausible tri count and one silhouette blob. This
tool produces the evidence a human needs:

  * 8 orthographic views on a transparent background (silhouette + shaded),
  * silhouette metrics per view (coverage, components, largest-piece fraction),
  * when a `--source` is given, per-view IoU against it (is this a copy?) and a
    contact sheet pairing source and candidate side by side.

Exit code 1 when the silhouette is empty, when no single piece dominates (debris),
or when `--source` is given and IoU is above `--copy-iou` (default 0.90) — i.e. the
derived model is still effectively the source.

Usage:
  blender -b -P tools/visual_check.py -- --glb output/units/x/x_rigged.glb \
      --out output/visual/x [--source output/base/x_base.glb] [--size 256]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--source")
_ap.add_argument("--size", type=int, default=256)
_ap.add_argument("--directions", type=int, default=8)
_ap.add_argument("--copy-iou", type=float, default=0.90)
_ap.add_argument("--label", default="")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def load_unit(path: Path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path.resolve()))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit(f"no mesh in {path}")
    body = max(meshes, key=lambda o: len(o.data.vertices))
    for o in meshes:
        if o is not body:
            bpy.data.objects.remove(o, do_unlink=True)
    return body


def frame_scene(body):
    co = [body.matrix_world @ v.co for v in body.data.vertices]
    lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
    hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
    centre = (lo + hi) / 2
    height = max(hi.z - lo.z, hi.x - lo.x, hi.y - lo.y)
    return centre, height


def setup_render(size: int, centre: Vector, height: float):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.8, 0.8, 0.8)
    scene.render.film_transparent = True
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    cam_data = bpy.data.cameras.new("vis_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.25
    cam = bpy.data.objects.new("vis_cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    return cam


def render_views(out: Path, centre: Vector, height: float, size: int, directions: int):
    cam = setup_render(size, centre, height)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(directions):
        az = (2 * math.pi * i) / directions
        dist = height * 3
        cam.location = (centre.x + math.sin(az) * dist,
                        centre.y - math.cos(az) * dist,
                        centre.z + height * 0.15)
        direction = centre - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        p = out / f"az{int(round(az * 180 / math.pi)):03d}.png"
        bpy.context.scene.render.filepath = str(p)
        bpy.ops.render.render(write_still=True)
        paths.append(p)
    return paths


def mask_metrics(path: Path):
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    alpha = px[:, :, 3]
    mask = alpha > 0.5
    bpy.data.images.remove(img)
    if not mask.any():
        return {"coverage": 0.0, "components": 0, "largest_frac": 0.0}, mask
    # 4-connected components without scipy
    seen = np.zeros_like(mask, dtype=bool)
    sizes = []
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        n = 0
        while stack:
            cy, cx = stack.pop()
            n += 1
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        sizes.append(n)
    total = float(sum(sizes)) or 1.0
    return {"coverage": round(float(mask.mean()), 4), "components": len(sizes),
            "largest_frac": round(max(sizes) / total, 4)}, mask


def iou(a, b):
    inter = float(np.logical_and(a, b).sum())
    union = float(np.logical_or(a, b).sum())
    return round(inter / union, 4) if union else 0.0


def main():
    out = Path(A.out)
    body = load_unit(Path(A.glb))
    centre, height = frame_scene(body)
    views = render_views(out / "candidate", centre, height, A.size, A.directions)

    metrics = {"glb": str(A.glb), "source": A.source, "views": {}, "failures": []}
    cand_masks = {}
    for p in views:
        m, mask = mask_metrics(p)
        metrics["views"][p.stem] = m
        cand_masks[p.stem] = mask
        if m["coverage"] <= 0.001:
            metrics["failures"].append(f"{p.stem}: empty silhouette")
        elif m["largest_frac"] < 0.90:
            metrics["failures"].append(
                f"{p.stem}: no dominant body (largest piece {m['largest_frac']:.0%})")

    if A.source:
        src_body = load_unit(Path(A.source))
        s_centre, s_height = frame_scene(src_body)
        src_views = render_views(out / "source", s_centre, s_height, A.size, A.directions)
        ious = {}
        for p, q in zip(src_views, views):
            _, smask = mask_metrics(p)
            ious[p.stem] = iou(smask, cand_masks[q.stem])
        metrics["iou_vs_source"] = ious
        mean_iou = round(float(np.mean(list(ious.values()))), 4)
        metrics["mean_iou_vs_source"] = mean_iou
        if mean_iou > A.copy_iou:
            metrics["failures"].append(
                f"mean silhouette IoU vs source {mean_iou:.2f} > {A.copy_iou:.2f}: still a copy")

    (out / "visual_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # contact sheet for human review: candidate row over source row when available
    rows = ["candidate"] + (["source"] if A.source else [])
    cmd = ["montage"]
    for row in rows:
        for p in sorted((out / row).glob("*.png")):
            cmd += ["-label", f"{row} {p.stem}", str(p)]
    cmd += ["-tile", f"{A.directions}x{len(rows)}", "-geometry", "+2+2",
            "-background", "#3a3a3a", "-fill", "white", str(out / "contact_sheet.png")]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as exc:  # montage missing is not fatal
        print("montage skipped:", exc)

    verdict = "PASS" if not metrics["failures"] else "FAIL"
    print(f"VISUAL {verdict} {A.glb} mean_iou={metrics.get('mean_iou_vs_source')}")
    for f in metrics["failures"]:
        print("  ERROR", f)
    print("  sheet", out / "contact_sheet.png")
    return 0 if not metrics["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
