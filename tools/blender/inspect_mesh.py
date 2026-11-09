#!/usr/bin/env python3
"""inspect_mesh.py — inspect, decimate and render a generated unit mesh.

Used by the 3D unit pipeline proof stage: import a GLB/OBJ produced by
tools/img23d, report geometry statistics (verts/tris/watertight/components/
bounds), optionally decimate to a LOD0 triangle budget, then render ortho
front and 3/4 views so the mesh can actually be looked at.

Usage:
    blender -b -P tools/blender/inspect_mesh.py -- \
        --glb output/img23d/<slug>/front.glb --out output/img23d/<slug>/inspect \
        --tris 20000 --render
"""

import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--tris", type=int, default=0, help="decimate target tris (0 = keep)")
    p.add_argument("--render", action="store_true")
    p.add_argument("--samples", type=int, default=32)
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def import_mesh(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".glb" or suffix == ".gltf":
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise SystemExit(f"unsupported mesh format: {suffix}")
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def join(meshes):
    if len(meshes) == 1:
        return meshes[0]
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def mesh_stats(obj) -> dict:
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    # connected components
    seen = set()
    comps = 0
    for v in bm.verts:
        if v.index in seen:
            continue
        comps += 1
        stack = [v]
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
    bm.free()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return {
        "name": obj.name,
        "verts": len(me.vertices),
        "polys": len(me.polygons),
        "tris": sum(len(p.vertices) - 2 for p in me.polygons),
        "materials": [m.name for m in me.materials if m],
        "uv_layers": [uv.name for uv in me.uv_layers],
        "non_manifold_edges": non_manifold,
        "components": comps,
        "bounds_min": [round(v, 4) for v in mins],
        "bounds_max": [round(v, 4) for v in maxs],
        "size": [round(v, 4) for v in (maxs - mins)],
    }


def decimate(obj, target_tris: int):
    current = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if not target_tris or current <= target_tris:
        return current, None
    ratio = target_tris / current
    mod = obj.modifiers.new(name="LOD0", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    now = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    return now, round(ratio, 4)


def add_material(obj):
    mat = bpy.data.materials.new("proof_clay")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.34, 0.38, 0.46, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.55
        bsdf.inputs["Metallic"].default_value = 0.25
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def setup_world():
    world = bpy.data.worlds.new("proof_world")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.05, 0.06, 0.08, 1.0)
        bg.inputs[1].default_value = 0.6
    bpy.context.scene.world = world


def add_lights():
    key = bpy.data.lights.new("key", type="AREA")
    key.energy = 1200
    key.size = 3.0
    ko = bpy.data.objects.new("key", key)
    ko.location = (2.5, -3.0, 3.0)
    ko.rotation_euler = (0.9, 0.2, 0.6)
    bpy.context.collection.objects.link(ko)

    rim = bpy.data.lights.new("rim", type="AREA")
    rim.energy = 700
    rim.size = 2.5
    ro = bpy.data.objects.new("rim", rim)
    ro.location = (-2.5, 2.0, 2.0)
    ro.rotation_euler = (1.1, 0.0, -2.2)
    bpy.context.collection.objects.link(ro)


def render_views(obj, out_dir: Path, samples: int):
    scene = bpy.context.scene
    engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
    engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    scene.render.engine = engine
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = samples
    scene.render.resolution_x = 720
    scene.render.resolution_y = 960
    scene.render.film_transparent = False
    for candidate in ("AgX", "Filmic", "Standard"):
        try:
            scene.view_settings.view_transform = candidate
            break
        except TypeError:
            continue

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    stats = mesh_stats(obj)
    centre = sum((Vector(c) for c in obj.bound_box), Vector()) / 8
    height = max(v - u for u, v in zip(stats["bounds_min"], stats["bounds_max"]))
    cam_data.ortho_scale = height * 1.25
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

    views = {
        "front": (0.0, -1.0),
        "three_quarter": (0.85, -1.0),
        "side": (1.0, 0.0),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (dx, dy) in views.items():
        dist = height * 4
        d = Vector((dx, dy, 0.25)).normalized() * dist
        cam.location = centre + d
        direction = centre - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        path = out_dir / f"{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        written.append(str(path))
    return written


def main():
    args = parse_args()
    glb = Path(args.glb).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    meshes = import_mesh(glb)
    if not meshes:
        raise SystemExit("no mesh imported")
    obj = join(meshes)
    before = mesh_stats(obj)
    tris_after, ratio = decimate(obj, args.tris)
    after = mesh_stats(obj)
    add_material(obj)

    report = {
        "source": str(glb),
        "imported": before,
        "decimate": {"target_tris": args.tris, "ratio": ratio, "tris_after": tris_after},
        "final": after,
    }
    (out / "mesh_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

    if args.render:
        setup_world()
        add_lights()
        views = render_views(obj, out / "render", args.samples)
        print("rendered:", views)

    # export the decimated mesh for the next stage
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    export = out / "lod0.glb"
    bpy.ops.export_scene.gltf(filepath=str(export), use_selection=True, export_format="GLB")
    print("exported:", export)


main()
