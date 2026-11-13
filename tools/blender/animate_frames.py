"""animate_frames.py — author the required clip set on a rig template frame.

Clips are generated procedurally on the skeleton (no external mocap), which keeps
them deterministic, editable and identical across the human, super-human, eldar
and monster frames. Every clip is built from the same helpers, so a change to the
gait improves every unit.

Clip set (the contract the game expects): aim, idle, walk, run, fire, reload, hit,
death, melee.

Usage:
  blender -b -P tools/blender/animate_frames.py -- \
    --glb output/units/ig_human/ig_human_rigged.glb \
    --out output/units/ig_human --id ig_human [--fps 24]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--fps", type=int, default=24)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if not arms:
    raise SystemExit("no armature in the GLB")
arm = arms[0]
bpy.context.view_layer.objects.active = arm
bpy.context.scene.render.fps = A.fps

bones = {b.name: b for b in arm.data.bones}
pose = arm.pose.bones
for pb in pose:
    pb.rotation_mode = "QUATERNION"


def local_axis(pb, world_axis):
    """Convert a world-space rotation axis into the bone's local space."""
    m = pb.bone.matrix_local.to_3x3()
    v = m.inverted() @ Vector(world_axis)
    return v.normalized()


def rot(pb, world_axis, degrees):
    """Rotate a bone about a world axis (X = pitch/swing, Y = roll, Z = yaw)."""
    if pb is None or abs(degrees) < 1e-6:
        return
    q = Quaternion(local_axis(pb, world_axis), math.radians(degrees))
    pb.rotation_quaternion = pb.rotation_quaternion @ q


def key(pb, frame):
    pb.keyframe_insert("rotation_quaternion", frame=frame)


def reset():
    for pb in pose:
        pb.rotation_quaternion = Quaternion((1, 0, 0, 0))
        pb.location = (0, 0, 0)


def has(*names):
    return all(n in pose for n in names)


def arms_down():
    """T-posed frames need the arms brought down before any gait is readable."""
    for side, sgn in (("L", 1), ("R", -1)):
        ua = pose.get(f"upperarm_{side}")
        if ua is None:
            continue
        rest = (bones[f"upperarm_{side}"].tail_local - bones[f"upperarm_{side}"].head_local)
        if abs(rest.x) > abs(rest.z):          # T-pose: arm points sideways
            rot(ua, (0, 1, 0), sgn * 62)
        la = pose.get(f"lowerarm_{side}")
        if la is not None:
            rot(la, (0, 1, 0), sgn * 8)


def gait(swing=24, knee=42, bob=0.03, lean=4, arm=18):
    """One 24-frame walk/run cycle; caller keys frames 1..25."""
    frames = [1, 7, 13, 19, 25]
    phase = [0, 1, 0, -1, 0]
    for i, f in enumerate(frames):
        reset()
        arms_down()
        s = phase[i]
        for side, sgn in (("L", 1), ("R", -1)):
            th = pose.get(f"thigh_{side}")
            sh = pose.get(f"shin_{side}")
            ft = pose.get(f"foot_{side}")
            if th is not None:
                rot(th, (1, 0, 0), s * sgn * swing)
            if sh is not None:
                rot(sh, (1, 0, 0), max(0.0, -s * sgn) * knee)
            if ft is not None:
                rot(ft, (1, 0, 0), max(0.0, s * sgn) * 12)
            ua = pose.get(f"upperarm_{side}")
            if ua is not None:
                rot(ua, (1, 0, 0), -s * sgn * arm)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (1, 0, 0), lean)
            rot(sp, (0, 0, 1), s * 3)
        root = pose.get("root")
        if root is not None:
            root.location = (0, 0, abs(s) * bob)
        for pb in pose:
            key(pb, f)


def clip_idle():
    for i, f in enumerate((1, 13, 25)):
        reset()
        arms_down()
        breathe = 1.5 if i != 1 else -1.0
        for name in ("spine_01", "spine_02", "chest"):
            pb = pose.get(name)
            if pb is not None:
                rot(pb, (1, 0, 0), breathe * 0.6)
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (0, 0, 1), 2.0 * (1 if i == 1 else -1))
        for side in ("L", "R"):
            ua = pose.get(f"upperarm_{side}")
            if ua is not None:
                rot(ua, (1, 0, 0), 1.5 * (1 if i == 0 else -1))
        for pb in pose:
            key(pb, f)


def clip_aim():
    for i, f in enumerate((1, 9)):
        reset()
        arms_down()
        # raise both arms forward into a two-handed aim
        for side, sgn in (("L", 1), ("R", -1)):
            ua = pose.get(f"upperarm_{side}")
            la = pose.get(f"lowerarm_{side}")
            if ua is not None:
                rot(ua, (0, 1, 0), -sgn * 42)
                rot(ua, (1, 0, 0), -55)
            if la is not None:
                rot(la, (0, 1, 0), -sgn * 10)
                rot(la, (1, 0, 0), -18)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (0, 0, 1), 6)
        for pb in pose:
            key(pb, f)


def clip_fire():
    for i, f in enumerate((1, 3, 6, 12)):
        reset()
        arms_down()
        kick = {0: 0, 1: 9, 2: 3, 3: 0}[i]
        for side, sgn in (("L", 1), ("R", -1)):
            ua = pose.get(f"upperarm_{side}")
            la = pose.get(f"lowerarm_{side}")
            if ua is not None:
                rot(ua, (0, 1, 0), -sgn * 42)
                rot(ua, (1, 0, 0), -55 + kick)
            if la is not None:
                rot(la, (0, 1, 0), -sgn * 10)
                rot(la, (1, 0, 0), -18 - kick * 0.4)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (1, 0, 0), -kick * 0.5)
        for pb in pose:
            key(pb, f)


def clip_reload():
    for i, f in enumerate((1, 8, 16, 24)):
        reset()
        arms_down()
        drop = {0: 0, 1: 25, 2: 25, 3: 0}[i]
        for side, sgn in (("L", 1), ("R", -1)):
            ua = pose.get(f"upperarm_{side}")
            la = pose.get(f"lowerarm_{side}")
            if ua is not None:
                rot(ua, (1, 0, 0), -35 + drop)
                rot(ua, (0, 1, 0), -sgn * 30)
            if la is not None:
                rot(la, (1, 0, 0), -50 - drop * 0.6)
        for pb in pose:
            key(pb, f)


def clip_hit():
    for i, f in enumerate((1, 5, 12)):
        reset()
        arms_down()
        back = {0: 0, 1: 14, 2: 4}[i]
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (1, 0, 0), -back)
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (1, 0, 0), -back * 0.8)
        for side in ("L", "R"):
            ua = pose.get(f"upperarm_{side}")
            if ua is not None:
                rot(ua, (1, 0, 0), back * 0.5)
        for pb in pose:
            key(pb, f)


def clip_death():
    for i, f in enumerate((1, 10, 24)):
        reset()
        arms_down()
        fall = {0: 0, 1: 40, 2: 88}[i]
        root = pose.get("root")
        if root is not None:
            rot(root, (1, 0, 0), -fall)
            root.location = (0, 0, -0.05 * i)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (1, 0, 0), -fall * 0.15)
        for side in ("L", "R"):
            ua = pose.get(f"upperarm_{side}")
            if ua is not None:
                rot(ua, (0, 1, 0), (1 if side == "L" else -1) * fall * 0.25)
        for pb in pose:
            key(pb, f)


def clip_melee():
    for i, f in enumerate((1, 7, 12, 18)):
        reset()
        arms_down()
        swing = {0: 0, 1: -60, 2: 35, 3: 0}[i]
        ua = pose.get("upperarm_R")
        la = pose.get("lowerarm_R")
        if ua is not None:
            rot(ua, (0, 1, 0), 40)
            rot(ua, (1, 0, 0), swing)
        if la is not None:
            rot(la, (1, 0, 0), -30)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (0, 0, 1), -swing * 0.25)
        for pb in pose:
            key(pb, f)


CLIPS = {
    "aim": clip_aim,
    "idle": clip_idle,
    "walk": lambda: gait(swing=24, knee=42, bob=0.03, lean=4, arm=18),
    "run": lambda: gait(swing=38, knee=64, bob=0.06, lean=12, arm=34),
    "fire": clip_fire,
    "reload": clip_reload,
    "hit": clip_hit,
    "death": clip_death,
    "melee": clip_melee,
}

arm.animation_data_create()
for name, fn in CLIPS.items():
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act
    fn()
    try:  # Blender 5.1 moved fcurves into slotted action layers
        for fc in act.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
    except AttributeError:
        pass
    print(f"CLIP {name} frames={int(act.frame_range[1])}")

arm.animation_data.action = None
for pb in pose:
    pb.rotation_quaternion = Quaternion((1, 0, 0, 0))
    pb.location = (0, 0, 0)

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_animated.glb"
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.data.objects:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=True, export_animation_mode="ACTIONS",
                          export_rest_position_armature=True)
print("EXPORTED", dest, "clips", len(bpy.data.actions))
