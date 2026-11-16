"""pose_weapon_proof.py — render a unit holding its weapon, exactly as the engine places it.

The engine's weapon placement is derived from the two hand bones (grip at the right hand,
barrel along the right→left axis). Judging that from a 26 m tactical screenshot is impossible,
and two rounds of "fixed" were wrong because of it. This reproduces the same transform in
Blender and renders a close-up, so the grip and the arm pose can be read at a scale where a
wrong wrist is visible.

Usage:
  blender -b -P tools/blender/pose_weapon_proof.py -- --glb <unit.glb> --weapon <weapon.glb> \
      --clip cover_high_l_idle --frame 1 --out /tmp/proof --id hc [--view side|front|top]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--weapon", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--clip", default="cover_high_l_idle")
_ap.add_argument("--frame", type=int, default=1)
_ap.add_argument("--view", default="front", choices=("side", "front", "top"))
_ap.add_argument("--res", type=int, default=720)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("no armature in the unit GLB")

actions = {a.name: a for a in bpy.data.actions}
arm.animation_data_create()
if A.clip in actions:
    arm.animation_data.action = actions[A.clip]
    try:
        if arm.animation_data.action_slot is None and actions[A.clip].slots:
            arm.animation_data.action_slot = actions[A.clip].slots[0]
    except AttributeError:
        pass
else:
    print(f"WARN clip {A.clip!r} not found; using rest pose")
bpy.context.scene.frame_set(A.frame)
bpy.context.view_layer.update()


def bone_world(name: str) -> Vector | None:
    pb = arm.pose.bones.get(name)
    if pb is None:
        return None
    return arm.matrix_world @ pb.head


hand_r = bone_world("hand_R")
hand_l = bone_world("hand_L")
print(f"HANDS right={tuple(round(v, 3) for v in hand_r) if hand_r else None} "
      f"left={tuple(round(v, 3) for v in hand_l) if hand_l else None}")

# ---- weapon: same placement the engine uses (grip at the right hand, barrel along the body's
# forward), then the same analytic two-bone IK for the support hand onto the foregrip.
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(Path(A.weapon).resolve()))
weapon = next(o for o in bpy.data.objects if o not in before and o.type == "MESH")
weapon.parent = None

FORWARD = Vector((0, -1, 0))   # this rig's forward (gripping hands sit at negative Y)

if hand_r:
    weapon.matrix_world = Vector((0, 0, 1)).rotation_difference(FORWARD).to_matrix().to_4x4()
    weapon.matrix_world.translation = hand_r
    bpy.context.view_layer.update()
    box = [weapon.matrix_world @ v.co for v in weapon.data.vertices]
    zs = [v.z for v in box]
    foregrip = hand_r + FORWARD * (max(zs) - min(zs)) * 0.45 + Vector((0, 0, 0.03))
    print(f"FOREGRIP {tuple(round(v, 3) for v in foregrip)}")

    # two-bone IK: upper arm -> forearm onto the foregrip, elbow placed by a pole hint
    def bone_head(name):
        pb = arm.pose.bones.get(name)
        return arm.matrix_world @ pb.head if pb else None

    def aim(pb, target):
        if pb is None:
            return
        bpy.context.view_layer.update()
        head = pb.matrix.translation.copy()
        cur = (pb.matrix.to_3x3() @ Vector((0, 1, 0))).normalized()
        des = (target - head)
        if des.length < 1e-6:
            return
        rot = cur.rotation_difference(des.normalized())
        m = rot.to_matrix().to_4x4() @ pb.matrix
        m.translation = head
        pb.matrix = m
        bpy.context.view_layer.update()

    up = arm.pose.bones.get("upperarm_L")
    lo = arm.pose.bones.get("lowerarm_L")
    if up and lo:
        S = up.matrix.translation.copy()
        E0 = lo.matrix.translation.copy()
        H0 = arm.pose.bones["hand_L"].matrix.translation.copy()
        l1 = (E0 - S).length
        l2 = (H0 - E0).length
        to = foregrip - S
        d = max(abs(l1 - l2) + 0.01, min(to.length, l1 + l2 - 0.01))
        dT = to.normalized()
        cosA = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
        a = __import__("math").acos(cosA)
        hint = Vector((0.4, 0.2, -1)).normalized()
        perp = (hint - dT * hint.dot(dT))
        perp = perp.normalized() if perp.length > 1e-6 else Vector((1, 0, 0))
        import math as _m
        elbow = S + dT * (_m.cos(a) * l1) + perp * (_m.sin(a) * l1)
        aim(up, elbow)
        aim(lo, foregrip)
        aim(arm.pose.bones.get("hand_L"), foregrip + dT * 0.1)
        hand_l = bone_head("hand_L")
        print(f"SUPPORT hand->foregrip = {(hand_l - foregrip).length:.3f} m")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
co = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
ctr = (lo + hi) / 2
extent = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
print(f"PROOF bbox {tuple(round(v, 2) for v in (hi - lo))}")

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = A.res
scene.render.resolution_y = A.res
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (0.62, 0.62, 0.66)

cam_data = bpy.data.cameras.new("ortho")
cam_data.type = "ORTHO"
cam_data.ortho_scale = extent * 1.15
cam = bpy.data.objects.new("ortho", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
direction_view = {"side": Vector((1, 0, 0)), "front": Vector((0, -1, 0)), "top": Vector((0, 0, 1))}[A.view]
cam.location = ctr + direction_view * extent * 3
cam.rotation_euler = (ctr - cam.location).normalized().to_track_quat("-Z", "Y").to_euler()

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(out / f"{A.id}_{A.view}.png")
bpy.ops.render.render(write_still=True)
print(f"PROOF rendered {scene.render.filepath}")
