#!/usr/bin/env python3
"""preview_unit_materials.py — put the generated material library on a unit mesh
and render it, so the result can be judged before it reaches the game.

This is a *preview*, not the final material assignment: it paints zones with a
geometric heuristic (height band + surface normal) because image-to-3D meshes
have no material IDs. It proves the library reads correctly on real geometry and
gives the reviewer a target for the authored split.

Usage:
    blender -b -P tools/blender/preview_unit_materials.py -- \
        --glb output/img23d/<slug>/inspect/lod0_uv.glb \
        --library assets/materials/grimdark_scifi/grimdark_scifi.blend \
        --out output/img23d/<slug>/material_preview --faction iron_directorate

Outputs <out>/three_quarter.png and <out>/front.png (1280x960, EEVEE).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
SLOTS = ["armour_primary", "armour_secondary", "underlayer", "metal_trim"]


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--library", default=str(ROOT / "assets/materials/grimdark_scifi/grimdark_scifi.blend"))
    ap.add_argument("--faction", default="iron_directorate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=32)
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def load_materials(library: Path, faction: str):
    mats = {}
    with bpy.data.libraries.load(str(library), link=False) as (src, dst):
        wanted = [n for n in src.materials if n.startswith(f"IOA_{faction}__")]
        dst.materials = wanted
    for m in dst.materials:
        if m:
            mats[m.name.split("__")[-1]] = m
    return mats


def import_mesh(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def paint_zones(obj, mats, faction):
    """Height/normal heuristic: lower limbs lose armour, upper plates gain it,
    near-vertical hard faces get secondary trim. Deliberately crude."""
    me = obj.data
    me.materials.clear()
    order = [s for s in SLOTS if s in mats]
    for slot in order:
        me.materials.append(mats[slot])
    idx = {s: i for i, s in enumerate(order)}
    if not order:
        return {}

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zmin = min(c.z for c in corners)
    zmax = max(c.z for c in corners)
    height = max(zmax - zmin, 1e-6)
    counts = {s: 0 for s in order}

    for poly in me.polygons:
        z = (poly.center.z - zmin) / height
        nz = abs(poly.normal.z)
        if z < 0.32:
            slot = "underlayer" if "underlayer" in idx else order[0]
        elif z > 0.62 and nz > 0.6:
            slot = "armour_secondary" if "armour_secondary" in idx else order[0]
        else:
            slot = "armour_primary" if "armour_primary" in idx else order[0]
        poly.material_index = idx[slot]
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def studio():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "CYCLES"
    prof = PROFILES.get(os.environ.get("IOA_GPU_PROFILE", ""), PROFILES["balanced"])
    scene.render.resolution_x, scene.render.resolution_y = prof["w"], prof["h"]
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("w") if not bpy.data.worlds else bpy.data.worlds[0]
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.022, 0.026, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    for name, loc, energy, size, colour in [
        ("key", (2.6, -3.2, 3.4), 900, 1.2, (1.0, 0.96, 0.9)),
        ("fill", (-3.0, -1.6, 1.8), 260, 2.0, (0.75, 0.85, 1.0)),
        ("rim", (-1.2, 3.2, 2.6), 700, 1.0, (1.0, 0.9, 0.75)),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = size
        data.color = colour
        ob = bpy.data.objects.new(name, data)
        ob.location = loc
        bpy.context.collection.objects.link(ob)
        direction = Vector((0, 0, 0.9)) - Vector(loc)
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def frame_for(obj, cam):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zmin = min(c.z for c in corners); zmax = max(c.z for c in corners)
    h = zmax - zmin
    fov = 2 * math.atan(24.0 / (2 * cam.data.lens))
    dist = (h * 1.15) / (2 * math.tan(fov / 2))
    return dist, (zmin + zmax) / 2


def aim(cam, angle_deg, target=(0, 0, 0.95), dist=3.4, height=1.25):
    a = math.radians(angle_deg)
    cam.location = (math.sin(a) * dist, -math.cos(a) * dist, height + 0.15)
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


PROFILES = {
    "low": {"w": 960, "h": 720, "samples": 8},
    "balanced": {"w": 1280, "h": 960, "samples": 16},
    "max": {"w": 1920, "h": 1080, "samples": 32},
}


def main():
    args = parse_args()
    # the launcher's resolved memory profile overrides the CLI for renders
    profile = os.environ.get("IOA_GPU_PROFILE", "")
    if profile in PROFILES:
        args.samples = PROFILES[profile]["samples"]
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    obj = import_mesh(Path(args.glb))
    mats = load_materials(Path(args.library), args.faction)
    if not mats:
        raise SystemExit(f"no IOA_{args.faction}__* materials in {args.library}")
    counts = paint_zones(obj, mats, args.faction)
    print("faces per slot:", counts)

    cam = studio()
    dist, mid = frame_for(obj, cam)
    scenes = [("front", 0), ("three_quarter", 40)]
    for name, angle in scenes:
        aim(cam, angle, target=(0, 0, mid), dist=dist, height=mid)
        bpy.context.scene.render.filepath = str(out / f"{name}.png")
        bpy.context.scene.eevee.taa_render_samples = args.samples
        bpy.ops.render.render(write_still=True)
    print(f"rendered -> {out}/front.png, {out}/three_quarter.png")


if __name__ == "__main__":
    main()
