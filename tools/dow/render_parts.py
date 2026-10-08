#!/usr/bin/env python3
"""Render a posed parts-OBJ (trooper/mannequin) with per-part PBR materials.

Generic renderer for the retarget pipeline: OBJ objects carry `usemtl <mat>`;
colours come from the parts JSON `mats` table {name: (r,g,b,rough,metal,
emissive|None)}. Ortho camera at azimuth (8-dir ready), three-light rig,
transparent film for sprite extraction.

    blender -b --python render_parts.py -- --obj m.obj --parts parts.json \
        --out out.png --res 512 --azimuth 0 [--frame-all] [--samples 64]
"""
import json
import math
import sys

import bpy
from mathutils import Euler, Vector

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    if name in ARGS:
        return ARGS[ARGS.index(name) + 1]
    return default


def flag(name):
    return name in ARGS


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build_materials(mats):
    out = {}
    for name, spec in mats.items():
        r, g, b, rough, metal, emis = (list(spec) + [None] * 6)[:6]
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        if emis:
            nt = m.node_tree
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs[0].default_value = (r, g, b, 1)
            em.inputs[1].default_value = 2.0
            mix = nt.nodes.new("ShaderNodeMixShader")
            out_socket = nt.nodes["Material Output"].inputs["Surface"]
            nt.links.new(bsdf.outputs[0], mix.inputs[1])
            nt.links.new(em.outputs[0], mix.inputs[2])
            nt.links.new(mix.outputs[0], out_socket)
        out[name] = m
    return out


def add_light(name, loc, energy, size=1.0):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.size = size
    ob = bpy.data.objects.new(name, data)
    ob.location = loc
    ob.rotation_euler = (Vector(loc) - Vector((0, 1.0, 0))).to_track_quat('Z', 'Y').to_euler()
    bpy.context.collection.objects.link(ob)
    return ob


def main():
    clear()
    obj_path, parts_path = arg("--obj"), arg("--parts")
    out, res = arg("--out", "/tmp/render.png"), int(arg("--res", "512"))
    az = float(arg("--azimuth", "0"))
    samples = int(arg("--samples", "64"))

    bpy.ops.wm.obj_import(filepath=obj_path)
    doc = json.load(open(parts_path)) if parts_path else {"mats": {}, "parts": []}
    part_mat = {p["name"]: p["mat"] for p in doc["parts"]}
    mats = build_materials(doc["mats"])
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        mat = mats.get(part_mat.get(ob.name, ""))
        for slot in ob.material_slots:
            slot.link = 'OBJECT'
            slot.material = mat
        for p in ob.data.polygons:
            p.use_smooth = True

    # bounds
    pts = []
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            for c in ob.bound_box:
                pts.append(ob.matrix_world @ Vector(c))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) / 2
    height = max(hi.z - lo.z, 1e-3)
    width = max(hi.x - lo.x, 1e-3)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(height / 0.78, width * 1.15) * 1.06
    cam = bpy.data.objects.new("cam", cam_data)
    r = height * 3
    ca = math.radians(az)
    cam.location = centre + Vector((math.sin(ca) * r, -math.cos(ca) * r, height * 0.02))
    # look at centre, Z-up world (DoW convention from the imports)
    d = (Vector(centre) - Vector(cam.location)).normalized()
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    add_light("key", (centre.x + 2.0, centre.y - 3.0, centre.z + 3.0), 4000, 3)
    add_light("fill", (centre.x - 3.0, centre.y - 2.0, centre.z + 1.0), 1500, 4)
    add_light("rim", (centre.x, centre.y + 3.0, centre.z + 2.5), 2500, 2)
    w = bpy.data.worlds.new("w"); w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.55, 0.55, 1) if not flag("--alpha") else (0, 0, 0, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    bpy.context.scene.world = w

    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = samples
    sc.render.resolution_x = res
    sc.render.resolution_y = int(res * 4 / 3) if flag("_43") else res
    sc.render.film_transparent = flag("--alpha")
    sc.view_settings.view_transform = 'Standard'
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("rendered", out)


main()
