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
# Drop any clips the incoming GLB already carries. Without this the authored set is added
# on top of the imported one and the export accumulates duplicates (measured: 25 clips
# instead of 16), so a rebuild looks like it worked while the engine sees stale actions.
for _act in list(bpy.data.actions):
    bpy.data.actions.remove(_act)
arm.animation_data_clear()
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


# ---------------------------------------------------------------- cover family
# XCOM's own taxonomy (XComAnimNodeCover: eAnimCover_LowLeft/LowRight/HighLeft/
# HighRight). There is no crouch-open or crouch-high state in the shipped game: crouching
# exists ONLY as a low-cover state, and high cover stands and leans. That is the rule the
# owner asked for, and it is why this family is split the way it is.
#
# Tier A — authored here. Tier B (retargeted DoW2 motion) replaces the *motion* when the
# hkx track decoder lands; the clip names stay, because they are the XCOM family members
# the engine's state machine selects by.


def _crouch(depth=1.0):
    """Full low-cover crouch: hips down toward the heels, torso folded over the thighs."""
    reset()
    arms_down()
    for side in ("L", "R"):
        th = pose.get(f"thigh_{side}")
        sh = pose.get(f"shin_{side}")
        ft = pose.get(f"foot_{side}")
        if th is not None:
            rot(th, (1, 0, 0), -84 * depth)
        if sh is not None:
            rot(sh, (1, 0, 0), 108 * depth)
        if ft is not None:
            rot(ft, (1, 0, 0), -24 * depth)
        ua = pose.get(f"upperarm_{side}")
        if ua is not None:
            rot(ua, (1, 0, 0), 22 * depth)
    for name, deg in (("spine_01", 9), ("spine_02", 13), ("chest", 7)):
        pb = pose.get(name)
        if pb is not None:
            rot(pb, (1, 0, 0), deg * depth)
    # The root bone points up, so its local Y is world Z; a negative Y offset lowers the
    # body. (The gait clips write the bob on local Z, which is horizontal — see the note
    # in KNOWN-ISSUES; it is a cosmetic 3-6 cm there and a visible 46 cm here.)
    root = pose.get("root")
    if root is not None:
        root.location = (0, -0.46 * depth, 0)


def _lean(side, degrees):
    """Roll the torso laterally about the body's forward axis — XCOM's cover lean."""
    sgn = 1.0 if side == "L" else -1.0
    for name, scale in (("spine_02", 1.0), ("spine_03", 0.7), ("chest", 0.5)):
        pb = pose.get(name)
        if pb is not None:
            rot(pb, (0, 1, 0), sgn * degrees * scale)
    hd = pose.get("head")
    if hd is not None:
        rot(hd, (0, 1, 0), -sgn * degrees * 0.35)


def crouch_idle():
    for i, f in enumerate((1, 17, 33)):
        _crouch()
        b = 1.4 if i == 1 else -1.0
        for name in ("spine_01", "chest"):
            pb = pose.get(name)
            if pb is not None:
                rot(pb, (1, 0, 0), b * 0.7)
        for pb in pose:
            key(pb, f)


def cover_low(side):
    """Low cover: crouched, back to the wall, leaning around the edge on `side`."""
    for i, f in enumerate((1, 17, 33)):
        _crouch()
        _lean(side, 16 + (2 if i == 1 else 0))
        for pb in pose:
            key(pb, f)


def cover_high(side):
    """High cover: standing, leaning around the edge. No crouch — XCOM stands here."""
    for i, f in enumerate((1, 17, 33)):
        reset()
        arms_down()
        _lean(side, 20 + (2 if i == 1 else 0))
        for pb in pose:
            key(pb, f)


def peek(side):
    """Peek out from low cover: rise slightly and lean further, then settle back."""
    for i, f in enumerate((1, 7, 13, 25)):
        _crouch(depth=1.0 if i != 1 else 0.86)
        _lean(side, 26 if i == 1 else 12)
        if i == 1:
            hd = pose.get("head")
            if hd is not None:
                rot(hd, (0, 0, 1), 10 if side == "L" else -10)
        for pb in pose:
            key(pb, f)


def cover_switch(side_from, high=False):
    """XCOM's SwitchSidesLL2LR / SwitchSidesHL2HR: cross from one lean to the other.

    The soldier keeps its back to the wall and swings the torso across the middle of the
    wall, so the clip is one pass through neutral — playing it as a cross-fade instead
    reads as a slide, which is why the shipped game has dedicated clips for it.
    """
    other = "R" if side_from == "L" else "L"
    for i, f in enumerate((1, 7, 13)):
        if high:
            reset()
            arms_down()
        else:
            _crouch()
        if i == 0:
            _lean(side_from, 18)
        elif i == 2:
            _lean(other, 18)
        else:
            _lean(side_from, 2)
        for pb in pose:
            key(pb, f)


def flanked_idle():
    """Self-flanked: the cover set is broken. Crouched, no lean, head scanning."""
    for i, f in enumerate((1, 13, 25, 37)):
        _crouch(depth=0.9)
        # no lateral lean — there is no longer a safe side — and the head sweeps
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (0, 0, 1), (12, -10, 8, 0)[i])
        ch = pose.get("chest")
        if ch is not None:
            rot(ch, (0, 0, 1), (4, -3, 3, 0)[i])
        for pb in pose:
            key(pb, f)


def flinch(amount=1.0):
    """A round that lands: torso snaps back, head jerks, then recovers."""
    for i, f in enumerate((1, 4, 10)):
        _crouch(depth=0.9)
        k = (1.0, 1.0, 0.25)[i] * amount
        for name, deg in (("spine_01", -10), ("spine_02", -14), ("chest", -8)):
            pb = pose.get(name)
            if pb is not None:
                rot(pb, (1, 0, 0), deg * k)
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (1, 0, 0), -16 * k)
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
    # cover family — the state machine selects these by XCOM family name
    "crouch_idle": crouch_idle,
    "cover_low_l_idle": lambda: cover_low("L"),
    "cover_low_r_idle": lambda: cover_low("R"),
    "cover_high_l_idle": lambda: cover_high("L"),
    "cover_high_r_idle": lambda: cover_high("R"),
    "peek_l": lambda: peek("L"),
    "peek_r": lambda: peek("R"),
    "cover_switch_ll_lr": lambda: cover_switch("L", high=False),
    "cover_switch_hl_hr": lambda: cover_switch("L", high=True),
    "flanked_idle": flanked_idle,
    "flinch_a": lambda: flinch(1.0),
    "flinch_b": lambda: flinch(0.6),
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
