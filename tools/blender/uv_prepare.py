#!/usr/bin/env python3
"""uv_prepare.py — give an image-to-3D mesh a usable UV layout and re-export.

Hunyuan/TripoSR output has no UVs, so `apply_unit_textures.py` and any PBR set
can only produce a flat clay look. This stage is the missing middle between
`inspect_mesh.py` (decimate) and `rig_unit_proof.py` (skin/animate): it unwraps
the mesh, reports coverage, and writes a GLB that can carry a texture.

Usage:
    blender -b -P tools/blender/uv_prepare.py -- \
        --glb output/img23d/<slug>/inspect/lod0.glb \
        --out output/img23d/<slug>/uv --render

Outputs:
    <out>/lod0_uv.glb        unwrapped mesh (same scale/orientation as input)
    <out>/uv_report.json     islands, coverage, texel density figures
    <out>/render/uv_layout.png  (only with --render) UV layout for review

This does NOT paint a texture; it makes texturing possible.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TARGET_TEXELS_PER_M = 1024.0  # support 1K-2K maps per unit at metre scale


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--margin", type=float, default=0.02, help="island margin (0-1)")
    ap.add_argument("--angle", type=float, default=66.0, help="angle limit in degrees")
    ap.add_argument("--weld", type=float, default=1e-4,
                    help="merge-by-distance threshold in metres (0 disables)")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--samples", type=int, default=16)
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_and_join(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh in glb")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    # Deterministic naming so downstream stages can rely on it.
    obj.name = "unit_body"
    obj.data.name = "unit_body_mesh"
    return obj


def weld(obj, threshold: float):
    """Image-to-3D output is triangle soup: every triangle has its own verts,
    so smart-project makes one island per face. Weld first or UVs are useless.
    Returns the vertex count before/after."""
    before = len(obj.data.vertices)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return before, len(obj.data.vertices)


def place_at_origin(obj):
    """Contract: origin at the feet, centred in X/Z, +Y up on export. glTF
    import centres the mesh, so re-place it or the GLB origin drifts."""
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zmin = min(c.z for c in corners)
    cx = (min(c.x for c in corners) + max(c.x for c in corners)) / 2
    cy = (min(c.y for c in corners) + max(c.y for c in corners)) / 2
    obj.location = (obj.location.x - cx, obj.location.y - cy, obj.location.z - zmin)
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def unwrap(obj, angle_deg: float, margin: float):
    """Smart-project UVs. Returns (islands, coverage, area)."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=math.radians(angle_deg),
        island_margin=margin,
        area_weight=0.0,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    me = obj.data
    uv_layer = me.uv_layers.active
    if uv_layer is None:
        raise SystemExit("smart_project produced no UV layer")

    # Coverage: sum of UV triangle areas (0..1 UV space). Islands: connected
    # UV components, approximated by counting distinct UV islands via loops.
    uvs = uv_layer.data
    total_uv_area = 0.0
    for poly in me.polygons:
        if poly.loop_total < 3:
            continue
        pts = [uvs[li].uv for li in poly.loop_indices]
        area = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        total_uv_area += abs(area) / 2.0

    # Connected-component count on the mesh (approximates island count).
    islands = count_components(me)

    # 3D surface area for texel density.
    surface = 0.0
    for poly in me.polygons:
        surface += poly.area
    texel_density = math.sqrt(total_uv_area) * TARGET_TEXELS_PER_M / max(math.sqrt(surface), 1e-9)

    return {
        "islands": islands,
        "uv_area_fraction": round(total_uv_area, 4),
        "surface_area_m2": round(surface, 4),
        "texel_density_px_per_m": round(texel_density, 1),
        "uv_layers": [l.name for l in me.uv_layers],
    }


def count_components(me):
    parent = list(range(len(me.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for e in me.edges:
        union(e.vertices[0], e.vertices[1])
    return len({find(i) for i in range(len(parent))})


def export_glb(obj, out_path: Path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    kwargs = dict(filepath=str(out_path), export_format="GLB",
                  export_yup=True, use_selection=True)
    try:
        bpy.ops.export_scene.gltf(**kwargs, export_apply=True)
    except TypeError:
        bpy.ops.export_scene.gltf(**kwargs)


def render_uv_layout(obj, out_png: Path, samples: int):
    """Render the UV layout to a PNG so an agent can see the islands."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="OBJECT")
    img = bpy.data.images.new("uv_layout", width=1024, height=1024, alpha=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.export_layout(filepath=str(out_png), size=(1024, 1024), opacity=0.25)
    bpy.ops.object.mode_set(mode="OBJECT")
    if img.users == 0:
        bpy.data.images.remove(img)


def main():
    args = parse_args()
    src = Path(args.glb).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clear_scene()
    obj = import_and_join(src)
    weld_info = {"verts_before": len(obj.data.vertices), "verts_after": len(obj.data.vertices)}
    if args.weld > 0:
        before, after = weld(obj, args.weld)
        weld_info = {"verts_before": before, "verts_after": after}
    place_at_origin(obj)
    info = unwrap(obj, args.angle, args.margin)
    glb_path = out_dir / "lod0_uv.glb"
    export_glb(obj, glb_path)

    if args.render:
        (out_dir / "render").mkdir(exist_ok=True)
        try:
            render_uv_layout(obj, out_dir / "render" / "uv_layout.png", args.samples)
        except Exception as exc:  # noqa: BLE001 - layout is a nicety, not a gate
            print(f"[uv_prepare] layout render skipped: {exc}")

    report = {
        "source": str(src),
        "output": str(glb_path),
        "triangles": sum(len(p.vertices) - 2 for p in obj.data.polygons),
        "verts": len(obj.data.vertices),
        "weld": weld_info,
        **info,
    }
    (out_dir / "uv_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if info["uv_area_fraction"] < 0.25:
        print("[uv_prepare] WARNING: UV coverage below 25% of UV space — wasted texel budget")


if __name__ == "__main__":
    main()
