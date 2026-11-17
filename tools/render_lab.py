#!/usr/bin/env python3
"""render_lab.py — render every lab unit in a pose, so the result is looked at, not inferred.

The numeric gates measure deformation from a bind; they cannot tell a shard pile from a body. This
renders each unit's bind pose and one action frame with a fixed camera, three-point light and the
unit's own materials, into `output/source_lab/renders/`.

Run inside Blender:
  blender -b -P tools/render_lab.py -- <lab dir> <out dir> [<action>:<frame> ...]
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
lab = Path(argv[0])
out = Path(argv[1])
shots = [s.split(":") for s in argv[2:]] or [["idle", "1"]]
out.mkdir(parents=True, exist_ok=True)


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def render(glb, action, frame, dest):
    clear()
    bpy.ops.object.empty_add(location=(0, 0, 0))
    bpy.context.view_layer.objects.active = bpy.context.object
    bpy.ops.import_scene.gltf(filepath=str(glb))
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        print(f"RENDER {glb.name}: no armature")
        return
    if arm.animation_data is None:
        arm.animation_data_create()
    act = next((a for a in bpy.data.actions if a.name == action), None)
    if act is not None:
        arm.animation_data.action = act
        try:
            if arm.animation_data.action_slot is None and act.slots:
                arm.animation_data.action_slot = act.slots[0]
        except AttributeError:
            pass
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    mn = Vector((1e9,) * 3)
    mx = Vector((-1e9,) * 3)
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(dg)
        for v in ev.data.vertices:
            w = ev.matrix_world @ v.co
            for i in range(3):
                mn[i] = min(mn[i], w[i])
                mx[i] = max(mx[i], w[i])
    centre = (mn + mx) / 2
    size = max(mx - mn)
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = centre + Vector((size * 0.9, -size * 1.1, size * 0.35))
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    for name, loc, energy in (("key", (3, -4, 5), 3000), ("fill", (-4, -2, 3), 1200),
                              ("rim", (0, 5, 4), 2000)):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = energy
        light.size = 4
        ob = bpy.data.objects.new(name, light)
        ob.location = Vector(loc) + centre
        bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
    bpy.context.scene.render.resolution_x = 720
    bpy.context.scene.render.resolution_y = 720
    bpy.context.scene.render.filepath = str(dest)
    bpy.ops.render.render(write_still=True)
    print(f"RENDER {dest}")


for glb in sorted(lab.glob("*.glb")):
    for action, frame in shots:
        render(glb, action, int(frame), out / f"{glb.stem}_{action}_{frame}.png")
