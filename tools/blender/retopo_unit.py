#!/usr/bin/env python3
"""retopo_unit.py — rebuild a coherent, unwrapped, slot-separated unit mesh.

Image-to-3D output arrives as vertex soup: every triangle disconnected, the
weapon fused into the chest, no UVs. Unwrapping soup produces thousands of
islands, so texture work is impossible. This stage produces the asset the rig and
the material pipeline can actually use:

  1. weld the soup and drop debris components
  2. voxel remesh to a single watertight shell (silhouette-preserving)
  3. decimate to the LOD0 tri budget, shade smooth, remove interior faces
  4. unwrap with a measured texel density
  5. assign authored material zones (vertex groups + material slots) from the
     semantic region of each face, not a height/normal heuristic

This is automated retopology, not artist retopology: the topology is uniform
triangles, good enough for an isometric combat camera and a rig, and clearly
better than soup. Artist retopo remains the path for hero close-ups.

Usage:
    blender -b -P tools/blender/retopo_unit.py -- \
        --glb output/img23d/<slug>/uv/lod0_uv.glb \
        --out output/img23d/<slug>/retopo --tris 20000 --voxel 0.012 --render
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]

# Semantic regions → material slot. Zones are defined in normalised body space
# (0 = feet, 1 = top of head) and in X (side) / Y (front-back). The rifle is the
# distinctive case: it sits forward of the chest and alongside the arms, so it is
# selected by a forward/height box before the torso rule.
SLOT_ORDER = ["armour_primary", "armour_secondary", "underlayer", "metal_trim"]
REGION_SLOT = {
    "helmet": "armour_primary",
    "torso": "armour_primary",
    "pauldron": "armour_secondary",
    "backpack": "armour_secondary",
    "arm": "underlayer",
    "hand": "underlayer",
    "leg": "armour_secondary",
    "boot": "metal_trim",
    "belt": "metal_trim",
    "weapon": "metal_trim",
    "other": "armour_primary",
}


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tris", type=int, default=20000)
    ap.add_argument("--voxel", type=float, default=0.012,
                    help="voxel size in metres; smaller keeps detail, larger merges parts")
    ap.add_argument("--smooth", type=int, default=2)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--debug-zones", action="store_true",
                    help="render flat colours per region so the split can be reviewed")
    ap.add_argument("--samples", type=int, default=32)
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_mesh(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit(f"no mesh in {path}")
    obj = max(objs, key=lambda o: len(o.data.polygons))
    for o in objs:
        if o is not obj:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.objects.active = obj
    return obj


def weld_and_clean(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    # drop debris islands: keep components with at least 1% of the largest
    bm.verts.ensure_lookup_table()
    seen = set()
    comps = []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack = [v]
        comp = set()
        while stack:
            x = stack.pop()
            if x.index in comp:
                continue
            comp.add(x.index)
            for e in x.link_edges:
                o = e.other_vert(x)
                if o.index not in comp:
                    stack.append(o)
        seen |= comp
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    if comps:
        keep = max(1, int(len(comps[0]) * 0.01))
        bm.verts.ensure_lookup_table()
        drop = [bm.verts[i] for c in comps[1:] if len(c) < keep for i in c]
        if drop:
            bmesh.ops.delete(bm, geom=drop, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    return {"components": len(comps), "dropped_components": max(0, len(comps) - 1)}


def remesh(obj, voxel: float):
    mod = obj.modifiers.new("retopo_voxel", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=mod.name)


def decimate(obj, target_tris: int):
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris <= target_tris:
        return tris
    mod = obj.modifiers.new("lod0", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(0.02, target_tris / tris)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def smooth(obj, iterations: int):
    if iterations <= 0:
        return
    mod = obj.modifiers.new("relax", "SMOOTH")
    mod.factor = 0.5
    mod.iterations = iterations
    bpy.ops.object.modifier_apply(modifier=mod.name)


def unwrap(obj, margin: float):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    # texel density: UV area / world area, reported as texels per metre at 1024
    uv_layer = obj.data.uv_layers.active.data if obj.data.uv_layers.active else None
    if not uv_layer:
        return {"islands": None, "texels_per_m": None}
    uvs = {i: (uv_layer[i].uv.copy()) for i in range(len(obj.data.loops))}
    uv_area = 0.0
    world_area = 0.0
    for p in obj.data.polygons:
        pts = [uvs[i] for i in p.loop_indices]
        if len(pts) >= 3:
            uv_area += abs(sum(pts[i].x * pts[(i + 1) % len(pts)].y
                               - pts[(i + 1) % len(pts)].x * pts[i].y
                               for i in range(len(pts)))) / 2.0
        world_area += p.area
    density = math.sqrt(uv_area / world_area) * 1024 if world_area else 0.0
    return {"uv_area": round(uv_area, 4), "world_area": round(world_area, 4),
            "texels_per_m": round(density, 1)}


def region_for(center: Vector, normal: Vector, height: float) -> str:
    """Semantic region from measured proportions of this mesh (height 1.995 m,
    torso front at y=-0.19, rifle slab forward of it at z 1.03-1.47)."""
    z = center.z / height
    x = abs(center.x)
    y = center.y
    # rifle: the forward slab above the waist and below the shoulders
    if 0.515 < z < 0.74 and y < -0.215 and x < 0.46:
        return "weapon"
    if z > 0.855:
        return "helmet"
    if z > 0.795:
        return "neck"
    if z > 0.735:
        return "pauldron" if x > 0.21 else "torso"
    if z > 0.525:
        if y > 0.16:
            return "backpack"
        if x > 0.235:
            return "arm"
        return "torso"
    if z > 0.475:
        return "belt"
    if z > 0.20:
        return "leg"
    return "boot"


def assign_zones(obj, height: float):
    """Author slots per face region and write vertex groups for the rig."""
    # the contract names materials by slot; drop whatever the import carried
    obj.data.materials.clear()
    for slot in SLOT_ORDER:
        mat = bpy.data.materials.new(slot)
        mat.use_nodes = True
        obj.data.materials.append(mat)
    for name in sorted(set(REGION_SLOT) | {"neck"}):
        if name not in obj.vertex_groups:
            obj.vertex_groups.new(name=name)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    counts: dict[str, int] = {}
    groups = {g.name: g.index for g in obj.vertex_groups}
    slot_index = {m.name: i for i, m in enumerate(obj.data.materials) if m}
    face_region = {}
    for f in bm.faces:
        c = f.calc_center_median()
        region = region_for(c, f.normal, height)
        face_region[f.index] = region
        counts[region] = counts.get(region, 0) + 1
    bm.to_mesh(obj.data)
    bm.free()

    # material slots per face
    for p in obj.data.polygons:
        region = face_region.get(p.index, "other")
        slot = REGION_SLOT.get(region, "armour_primary")
        idx = slot_index.get(slot)
        if idx is not None:
            p.material_index = idx

    # vertex groups per region (rig weighting / later painting)
    region_verts: dict[str, set[int]] = {}
    for p in obj.data.polygons:
        region = face_region.get(p.index, "other")
        region_verts.setdefault(region, set()).update(p.vertices)
    for region, verts in region_verts.items():
        vg = obj.vertex_groups.get(region) or obj.vertex_groups.new(name=region)
        vg.add(list(verts), 1.0, "REPLACE")
    return counts, face_region


def setup_render(out_dir: Path, samples: int, flat: bool = False):
    from mathutils import Vector as V
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH" if flat else "BLENDER_EEVEE"
    if flat:
        scene.display.shading.light = "FLAT"
        scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.film_transparent = False
    scene.eevee.taa_render_samples = samples
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.035, 0.045, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    scene.world = world
    key = bpy.data.lights.new("key", "AREA")
    key.energy = 900
    key.size = 4
    ko = bpy.data.objects.new("key", key)
    ko.location = (3, -4, 5)
    ko.rotation_euler = (math.radians(45), 0, math.radians(35))
    scene.collection.objects.link(ko)
    cam = bpy.data.cameras.new("cam")
    cam.lens = 70
    co = bpy.data.objects.new("cam", cam)
    co.location = (3.2, -5.6, 2.3)
    co.rotation_euler = (math.radians(78), 0, math.radians(29))
    scene.collection.objects.link(co)
    scene.camera = co
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out_dir / "retopo_review.png")
    bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    glb = Path(args.glb).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    obj = import_mesh(glb)
    clean = weld_and_clean(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    zs = [v.co.z for v in bm.verts]
    height = max(zs) - min(zs) if zs else 1.9
    bm.free()

    remesh(obj, args.voxel)
    smooth(obj, args.smooth)
    tris = decimate(obj, args.tris)
    uv = unwrap(obj, args.margin)
    counts, face_region = assign_zones(obj, height)

    if args.render or args.debug_zones:
        setup_render(out / "render" / ("zones" if args.debug_zones else ""), args.samples)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    glb_out = out / "lod0_retopo.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb_out), use_selection=True,
                              export_format="GLB", export_yup=True)

    if args.debug_zones:
        colours = {
            "helmet": (0.95, 0.8, 0.2, 1), "neck": (0.95, 0.5, 0.1, 1),
            "torso": (0.15, 0.4, 0.95, 1), "pauldron": (0.1, 0.75, 0.95, 1),
            "backpack": (0.45, 0.25, 0.85, 1), "arm": (0.2, 0.85, 0.4, 1),
            "hand": (0.4, 1.0, 0.7, 1), "leg": (0.9, 0.25, 0.25, 1),
            "boot": (1.0, 0.55, 0.55, 1), "belt": (0.95, 0.95, 0.3, 1),
            "weapon": (1.0, 0.1, 0.9, 1), "other": (0.6, 0.6, 0.6, 1),
        }
        obj.data.materials.clear()
        idx = {}
        for region, col in colours.items():
            mat = bpy.data.materials.new(f"zone_{region}")
            mat.diffuse_color = col
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = col
            bsdf.inputs["Roughness"].default_value = 0.55
            idx[region] = len(obj.data.materials)
            obj.data.materials.append(mat)
        for p in obj.data.polygons:
            p.material_index = idx.get(face_region.get(p.index, "other"), idx["other"])
        setup_render(out / "render" / "zones", args.samples, flat=True)

    report = {
        "source": str(glb), "glb": str(glb_out),
        "height_m": round(height, 3),
        "weld": clean, "voxel_m": args.voxel, "smooth_iterations": args.smooth,
        "tris": tris, "uv": uv, "regions": counts,
        "slots": [m.name for m in obj.data.materials if m],
        "note": "automated retopology (voxel shell + decimate + smart UV); artist "
                "retopo still required for hero close-ups",
    }
    (out / "retopo_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("RETOPO:", json.dumps(report))


main()
