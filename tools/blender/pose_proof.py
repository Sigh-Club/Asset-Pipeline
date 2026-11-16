"""pose_proof.py — render a named clip at a named frame, orthographically.

The cover gates are pose gates: "a soldier on a low-cover cell crouches with hips near
the heels and leans into the correct side of the wall" cannot be asserted numerically
without encoding the whole pose. This renders the pose so it can be read against the
source, which is the check that catches a mis-scaled or mis-axed rig (D-1 shipped past a
green numeric gate).

Usage:
  blender -b -P tools/blender/pose_proof.py -- --glb <unit.glb> --clip crouch_idle \
      --frame 1 --out output/proof --id ig_human_crouch [--view side|front|top]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--clip", required=True)
_ap.add_argument("--frame", type=int, default=1)
_ap.add_argument("--view", default="side", choices=("side", "front", "top"))
_ap.add_argument("--res", type=int, default=640)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))

arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("no armature in the GLB")
actions = {a.name: a for a in bpy.data.actions}
if A.clip not in actions:
    raise SystemExit(f"clip {A.clip!r} not in {sorted(actions)}")
arm.animation_data_create()
arm.animation_data.action = actions[A.clip]
try:  # Blender 5.1 slotted actions: assign the slot so the action actually evaluates
    if arm.animation_data.action_slot is None and actions[A.clip].slots:
        arm.animation_data.action_slot = actions[A.clip].slots[0]
except AttributeError:
    pass
bpy.context.scene.frame_set(A.frame)
bpy.context.view_layer.update()

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
co = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
ctr = (lo + hi) / 2
span = hi - lo
extent = max(span.x, span.y, span.z)
print(f"POSE {A.clip}@{A.frame} bbox x={span.x:.2f} y={span.y:.2f} z={span.z:.2f} "
      f"min_z={lo.z:.2f}")

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = A.res
scene.render.resolution_y = A.res
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (0.62, 0.62, 0.66)

cam_data = bpy.data.cameras.new("ortho")
cam_data.type = "ORTHO"
cam_data.ortho_scale = extent * 1.25
cam = bpy.data.objects.new("ortho", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
direction = {"side": Vector((1, 0, 0)), "front": Vector((0, -1, 0)), "top": Vector((0, 0, 1))}[A.view]
cam.location = ctr + direction * extent * 3
cam.rotation_euler = (ctr - cam.location).normalized().to_track_quat("-Z", "Y").to_euler()

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(out / f"{A.id}_{A.view}.png")
bpy.ops.render.render(write_still=True)
print(f"POSE rendered {scene.render.filepath}")
