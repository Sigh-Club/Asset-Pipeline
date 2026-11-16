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


def aim_bone(pb, target):
    """Point a pose bone's own axis at a world-space target.

    Authoring arms by guessing rotation angles does not converge: measured on the certified
    pose, both hands stayed at y=0.072 (hanging at the sides) no matter which world-axis
    rotation was applied, because the bone's rest orientation is not aligned to the world axes.
    Aiming the bone at a target is the direct statement of the intent and cannot be misread.
    """
    if pb is None:
        return
    bpy.context.view_layer.update()
    head = pb.matrix.translation.copy()
    cur = (pb.matrix.to_3x3() @ Vector((0, 1, 0))).normalized()   # bone Y = its own direction
    des = (Vector(target) - head)
    if des.length < 1e-6:
        return
    des.normalize()
    rot = cur.rotation_difference(des)
    m = rot.to_matrix().to_4x4() @ pb.matrix
    m.translation = head
    pb.matrix = m
    bpy.context.view_layer.update()


def arms_hold(offset_r, offset_l):
    """Both hands onto two grip points — a two-handed carry, stated as positions.

    The right hand takes the pistol grip and the left the foregrip; each arm is aimed through
    an elbow point partway to its grip so the elbow bends instead of the arm locking straight.
    Offsets are relative to the CHEST, not to the world: an absolute target would be reached
    from wherever the body is, so a crouch would leave the arms stretched up to standing height.
    """
    chest = pose.get("chest")
    base = chest.matrix.translation.copy() if chest is not None else Vector((0, 0, 1.4))
    grip_r = base + Vector(offset_r)
    grip_l = base + Vector(offset_l)
    for side, grip in (("R", grip_r), ("L", grip_l)):
        ua = pose.get(f"upperarm_{side}")
        la = pose.get(f"lowerarm_{side}")
        hd = pose.get(f"hand_{side}")
        if ua is None:
            continue
        shoulder = ua.matrix.translation.copy()
        g = Vector(grip)
        elbow = shoulder.lerp(g, 0.55)
        # drop the elbow out and back so the arm reads as bent rather than as a rod
        elbow.z -= 0.06
        elbow.x += (-0.10 if side == "R" else 0.10)
        aim_bone(ua, elbow)
        if la is not None:
            aim_bone(la, g)
        if hd is not None:
            aim_bone(hd, g + (g - elbow).normalized() * 0.12)


def arms_ready():
    """Both hands up on the weapon.

    XCOM's cover poses are built around a shouldered rifle: the arms are up and the elbows
    are bent, which is also what makes the attached weapon read as held rather than stuck to
    the hand. `arms_down()` leaves the hands at the hips, which reads as standing at ease.
    """
    for side, sgn in (("L", 1), ("R", -1)):
        ua = pose.get(f"upperarm_{side}")
        if ua is None:
            continue
        rest = (bones[f"upperarm_{side}"].tail_local - bones[f"upperarm_{side}"].head_local)
        if abs(rest.x) > abs(rest.z):
            rot(ua, (0, 1, 0), sgn * 58)
        rot(ua, (1, 0, 0), 48)
        la = pose.get(f"lowerarm_{side}")
        if la is not None:
            rot(la, (1, 0, 0), -62)


def _crouch(depth=1.0):
    """Low-cover crouch: hips back and down, torso UPRIGHT against the wall.

    XCOM's LowLeft/LowRight pose is not a deep squat — the soldier keeps its back to the wall
    with the head up and the weapon shouldered, and only the legs fold. A forward-folded squat
    (the DoW2 idle crouch) reads as hiding in the open instead of using the cover.
    """
    reset()
    arms_hold((0.11, -0.26, -0.10), (-0.09, -0.46, -0.13))
    for side in ("L", "R"):
        th = pose.get(f"thigh_{side}")
        sh = pose.get(f"shin_{side}")
        ft = pose.get(f"foot_{side}")
        if th is not None:
            rot(th, (1, 0, 0), -68 * depth)
        if sh is not None:
            rot(sh, (1, 0, 0), 88 * depth)
        if ft is not None:
            rot(ft, (1, 0, 0), -20 * depth)
    # torso stays close to upright: the back is against the wall, not folded over the knees
    for name, deg in (("spine_01", 5), ("spine_02", 7), ("chest", 3)):
        pb = pose.get(name)
        if pb is not None:
            rot(pb, (1, 0, 0), deg * depth)
    # The root bone points up, so its local Y is world Z; a negative Y offset lowers the
    # body. (The gait clips write the bob on local Z, which is horizontal — see the note
    # in KNOWN-ISSUES; it is a cosmetic 3-6 cm there and a visible 46 cm here.)
    root = pose.get("root")
    if root is not None:
        root.location = (0, -0.40 * depth, 0)


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
        _lean(side, 7 + (1 if i == 1 else 0))
        for pb in pose:
            key(pb, f)


def cover_high(side):
    """High cover: standing, leaning around the edge. No crouch — XCOM stands here."""
    for i, f in enumerate((1, 17, 33)):
        reset()
        arms_hold((0.11, -0.26, -0.03), (-0.09, -0.46, -0.06))
        _lean(side, 8 + (1 if i == 1 else 0))
        for pb in pose:
            key(pb, f)


def peek(side):
    """Peek out from low cover: rise slightly and lean further, then settle back."""
    for i, f in enumerate((1, 7, 13, 25)):
        _crouch(depth=1.0 if i != 1 else 0.86)
        _lean(side, 12 if i == 1 else 5)
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
            _lean(side_from, 8)
        elif i == 2:
            _lean(other, 8)
        else:
            _lean(side_from, 1)
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


def cover_exit(angle, stay=False, low=True):
    """Leave cover by `angle` degrees from the cover plane.

    XComAnimNodeBlendByExitCoverType names the variants (Zero, Ninety, OneEighty,
    Ninety_Stay, Zero_LowCoverStepOut) and XCOM 2 selects them against
    StepOutAngleThreshold=40 (0 = parallel to the cover, 90 = perpendicular). The clip
    rises out of the crouch, unwinds the lean, and turns the body by the exit angle so the
    departure reads as leaving a specific edge rather than standing up.
    """
    for i, f in enumerate((1, 7, 13)):
        depth = (1.0, 0.55, 0.0)[i] if low else 0.0
        if low:
            _crouch(depth=depth)
        else:
            reset()
            arms_down()
        _lean("L", max(0.0, 7 - i * 3))
        twist = angle * (i / 2.0) * 0.35
        for name in ("spine_02", "chest"):
            pb = pose.get(name)
            if pb is not None:
                rot(pb, (0, 0, 1), twist)
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (0, 0, 1), twist * 0.6)
        if stay and i == 2:
            root = pose.get("root")
            if root is not None:
                root.location = (0, 0, 0)
        for pb in pose:
            key(pb, f)


def cover_fire(side):
    """Fire from high cover: the standing lean holds, the arms take the recoil."""
    for i, f in enumerate((1, 5, 13)):
        reset()
        arms_ready()
        _lean(side, 8)
        k = (0.0, 1.0, 0.3)[i]
        for s in ("L", "R"):
            ua = pose.get(f"upperarm_{s}")
            if ua is not None:
                rot(ua, (1, 0, 0), -8 * k)
            la = pose.get(f"lowerarm_{s}")
            if la is not None:
                rot(la, (1, 0, 0), -6 * k)
        sp = pose.get("spine_02")
        if sp is not None:
            rot(sp, (1, 0, 0), -5 * k)
        for pb in pose:
            key(pb, f)


def panic_pose(phase):
    """BlendByPanic: start (break posture), loop (shaking), stop (recover)."""
    for i, f in enumerate((1, 13, 25)):
        reset()
        arms_down()
        k = 1.0 if phase == "start" else (0.7 if phase == "loop" else 0.25)
        for s in ("L", "R"):
            ua = pose.get(f"upperarm_{s}")
            if ua is not None:
                rot(ua, (0, 1, 0), (1 if s == "L" else -1) * 70 * k)
            la = pose.get(f"lowerarm_{s}")
            if la is not None:
                rot(la, (1, 0, 0), -40 * k)
        for name, deg in (("spine_01", -8), ("spine_02", -12), ("chest", -6)):
            pb = pose.get(name)
            if pb is not None:
                rot(pb, (1, 0, 0), deg * k)
        hd = pose.get("head")
        if hd is not None:
            rot(hd, (0, 0, 1), (6 if i == 1 else -6) * k)
        if phase == "loop" and i == 1:
            root = pose.get("root")
            if root is not None:
                root.location = (0, 0, 0.02)
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
    "cover_high_l_fire": lambda: cover_fire("L"),
    "cover_high_r_fire": lambda: cover_fire("R"),
    "cover_exit_zero": lambda: cover_exit(0),
    "cover_exit_ninety": lambda: cover_exit(90),
    "cover_exit_oneeighty": lambda: cover_exit(180),
    "cover_exit_ninety_stay": lambda: cover_exit(90, stay=True),
    "cover_exit_low_stepout": lambda: cover_exit(0, low=True),
    "panic_start": lambda: panic_pose("start"),
    "panic_loop": lambda: panic_pose("loop"),
    "panic_stop": lambda: panic_pose("stop"),
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
