"""dow2_poses_to_clips.py — author a unit's clip set from DoW2's own animation files.

DoW2 ships one `.hkx` per clip, and each of those files carries the skeleton **in the pose that
clip was authored in** (verified: 233 guardsman clip files, poses 0.6-2.6 m apart from each other;
`fb_aiming_stand` decodes to a two-handed aim with both hands at y 1.66-1.68 and the head at
2.28). The animation *tracks* are still undecoded, but the poses are not: they are right there in
the reference pose of each file.

That is the answer to "how did they animate them" — so this tool uses those poses instead of
authoring procedural ones. Each DoW2 clip becomes one action on our rig, named for the DoW2 clip,
with every bone set from the shipped pose.

The unit's rig must be built from the same DoW2 skeleton (`rig_template.py --skeleton`), because
the pose is applied bone-for-bone in armature space and the bone names have to correspond.

Usage:
  blender -b -P tools/blender/dow2_poses_to_clips.py -- \
      --glb <unit_rigged.glb> --hkx <unit.hkx> --anim-dir <unit>/animations \
      --out <dir> --id <id> [--limit N] [--filter substr]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/hkx"))
sys.path.insert(0, str(ROOT / "tools/dow2"))

import skeleton as S  # noqa: E402
from hkxread import Packfile  # noqa: E402

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--hkx", required=True, help="the unit's own skeleton (its reference pose)")
_ap.add_argument("--anim-dir", required=True, help="<unit>/animations, searched recursively")
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--limit", type=int, default=0)
_ap.add_argument("--filter", default="", help="only clip names containing this substring")
_ap.add_argument("--height", type=float, default=0.0,
                help="target height in metres; default: read from the rig")
_ap.add_argument("--up-axis", default="y")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

# ------------------------------------------------------------------ rig
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("no armature in the GLB")
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

# The rig is already in base space; the poses come from source space. The transform between them
# is the one dow2_base.py applied to the geometry: declared up axis, uniform scale to the class
# height, ground and centre. Recover the scale/offset from the rig itself so no source OBJ is
# needed: the rig's height and its grounded minimum are the same numbers.
bone_names = {b.name for b in arm.data.bones}
rig_lo = Vector((1e9, 1e9, 1e9))
rig_hi = Vector((-1e9, -1e9, -1e9))
for b in arm.data.bones:
    for p in (b.head_local, b.tail_local):
        rig_lo = Vector((min(rig_lo[i], p[i]) for i in range(3)))
        rig_hi = Vector((max(rig_hi[i], p[i]) for i in range(3)))
print(f"RIG bones={len(bone_names)} bbox_z={rig_lo.z:.3f}..{rig_hi.z:.3f}")

# ------------------------------------------------------------------ source skeleton
src_rest = Packfile.open(A.hkx).skeleton()
rest_W = S.compose(src_rest)
rest_names = src_rest["bone_names"]
rest_by_name = {n: rest_W[i] for i, n in enumerate(rest_names)}

# source -> base. The rig was built from this same skeleton, so the transform between the two is
# recoverable exactly: solve for the uniform scale and offset that map the source reference pose
# onto the rig's rest pose. Deriving it from the rig's bounding-box height instead double-applied
# the scale skeleton.py had already baked in (measured: a pose applied at 0.63x, which tore every
# limb off the mesh).
R = S.euler_matrix(S.UP_AXIS_TO_Z[A.up_axis])

pairs = []
for i, name in enumerate(rest_names):
    mapped = S.canonical(name) or name
    b = arm.data.bones.get(mapped)
    if b is None:
        continue
    pairs.append((R @ rest_W[i][:3, 3], np.array(tuple(b.head_local))))
if len(pairs) < 8:
    raise SystemExit(f"only {len(pairs)} bones correspond between the skeleton and the rig")
P = np.array([a for a, _ in pairs])
Q = np.array([b for _, b in pairs])
Pc, Qc = P - P.mean(0), Q - Q.mean(0)
scale = float((Pc * Qc).sum() / max(1e-12, (Pc * Pc).sum()))
offset = Q.mean(0) - scale * P.mean(0)
resid = np.linalg.norm(scale * P + offset - Q, axis=1)
T = np.eye(4)
T[:3, :3] = R * scale
T[:3, 3] = offset
print(f"SOURCE fit scale={scale:.4f} mean_residual={resid.mean():.4f} "
      f"max_residual={resid.max():.4f} over {len(pairs)} bones")

def to_matrix(m):
    return Matrix([[float(m[r][c]) for c in range(4)] for r in range(4)])


# ------------------------------------------------------------------ clip discovery
clips = sorted(Path(A.anim_dir).rglob("*.hkx"))
if A.filter:
    clips = [c for c in clips if A.filter in c.stem]
if A.limit:
    clips = clips[:A.limit]
print(f"CLIPS found {len(clips)}")

# ------------------------------------------------------------------ author
arm.animation_data_create()
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)

# hierarchy order: a pose bone's armature-space matrix can only be set once its parent is set
depth = {}
for b in arm.data.bones:
    d = 0
    cur = b
    while cur.parent:
        d += 1
        cur = cur.parent
    depth[b.name] = d
ordered_bones = sorted(arm.pose.bones, key=lambda pb: depth.get(pb.name, 0))

applied = 0
skipped = []
for path in clips:
    try:
        sk = Packfile.open(path).skeleton()
    except Exception as exc:
        skipped.append((path.stem, f"decode: {exc}"))
        continue
    if not sk:
        skipped.append((path.stem, "no skeleton"))
        continue
    W = S.compose(sk)
    names = sk["bone_names"]
    if len(names) != sk["bone_count"]:
        skipped.append((path.stem, "name/bone count mismatch"))
        continue
    # Place every bone with a RIGID world-space delta applied to our own rest pose.
    #
    #     delta   = pose_world @ inv(rest_world)        (the motion the shipped bone underwent)
    #     target  = delta_in_base_units @ our_rest      (no scale anywhere)
    #
    # The scale is the trap that broke every previous attempt. `T` is the source->base transform and
    # it carries the 0.632 uniform scale that sizes the body to 1.85 m. Assigning `T @ pose` puts
    # that scale on every joint, and a skinned mesh driven by scaled joints is deformed
    # non-rigidly — measured: every posed joint carried a 0.632 column scale while its rest was
    # unit-scale, which tore the coat into shards and misplaced the hands by 0.2-0.4 m. Only the
    # translation may be scaled; the rotation must stay a rotation.
    #
    # This form is also roll-independent (it is a world-space rotation, not a frame-relative basis),
    # and it is exact at rest: delta = I, so target = our rest.
    #
    # Keyed by NAME: the clip's skeleton and the unit's have different bone lists (46 vs 45 on the
    # guardsman), so anything keyed by index pairs unrelated bones — that is what made these clips
    # look like they carried the bind pose. By name, `fb_aiming_stand` moves the hands 1.13-1.19 m
    # from rest: they are real authored poses.
    S_rot = np.eye(4)
    S_rot[:3, :3] = R
    S_rot_inv = np.linalg.inv(S_rot)
    pose = {}
    for i, name in enumerate(names):
        mapped = S.canonical(name) or name
        if mapped not in bone_names:
            continue
        rest_src = rest_by_name.get(name)
        if rest_src is None:
            continue
        try:
            delta_src = W[i] @ np.linalg.inv(rest_src)
        except np.linalg.LinAlgError:
            continue
        # rotate the delta into base orientation, scale ONLY its translation, and drop any scale
        delta_rot = S_rot @ delta_src @ S_rot_inv
        d = np.eye(4)
        d[:3, :3] = delta_rot[:3, :3]
        d[:3, 3] = delta_rot[:3, 3] * scale
        ours = np.array(arm.data.bones[mapped].matrix_local)
        target = d @ ours
        pose[mapped] = Matrix([[float(target[r][c]) for c in range(4)] for r in range(4)])
    if len(pose) < 12:
        skipped.append((path.stem, f"only {len(pose)} bones map"))
        continue

    act = bpy.data.actions.new(path.stem)
    act.use_fake_user = True
    arm.animation_data.action = act
    try:
        if arm.animation_data.action_slot is None and act.slots:
            arm.animation_data.action_slot = act.slots[0]
    except AttributeError:
        pass
    # A pose, not a motion: two identical keys so the action has a range and plays.
    # Bones must be assigned parents-first with a depsgraph update between: pose_bone.matrix is
    # solved against the CURRENT parent pose, so assigning children before parents (or without
    # an update) multiplies the error down the chain and explodes the model (measured: an 18 m
    # bounding box on the first run of this tool).
    for frame in (1, 2):
        bpy.context.scene.frame_set(frame)
        # reset first: a bone the clip does not animate must return to rest, not keep the previous
        # clip's pose (that accumulation is what makes successive clips drift and fall over)
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        for pb in ordered_bones:
            M = pose.get(pb.name)
            if M is None:
                continue
            pb.matrix = to_matrix(M)
            bpy.context.view_layer.update()
        # assert the assignment landed where it was asked to: a silent mismatch is how a "pose"
        # ends up looking like a fall
        worst = 0.0
        for pb in ordered_bones:
            M = pose.get(pb.name)
            if M is None:
                continue
            worst = max(worst, max(abs(pb.matrix[r][c] - M[r][c])
                                   for r in range(4) for c in range(4)))
        if worst > 1e-3:
            print(f"  WARN {path.stem}: pose assignment off by {worst:.4f}")
        for pb in arm.pose.bones:
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            pb.keyframe_insert("location", frame=frame)
            pb.keyframe_insert("scale", frame=frame)
    applied += 1
    if applied % 20 == 0:
        print(f"  ... {applied} poses")

arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_animated.glb"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=True, export_animation_mode="ACTIONS")
print(f"APPLIED {applied} DoW2 poses, skipped {len(skipped)}")
for s in skipped[:8]:
    print("   skip", s)
print("EXPORTED", dest, "actions", len(bpy.data.actions))
