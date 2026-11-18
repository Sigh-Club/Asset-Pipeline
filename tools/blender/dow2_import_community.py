"""dow2_import_community.py — build a DoW2 unit with the community toolchain, not our own assembly.

The DoW2 Tools add-on (`dow2-blender`, Santos Tools 2 lineage — the tooling the Elite mod is built
with) does the assembly the game does: it reads the model's own bone table, builds the skeleton with
its bone-axis adapter, binds the shipped weights and resolves the materials. This script uses that
importer for the body, the head/attachments and the weapon (merged onto the one armature), then
applies the shipped clips with the add-on's own pose maths (DirectX→Blender conversion, rest delta,
adapter conjugation) and exports a GLB.

Nothing here re-implements bone construction or pose conversion: the only code we supply is the clip
reader, because the add-on's reader is a Windows binary and ours produces the same data.

Run inside Blender:
  blender -b -P tools/blender/dow2_import_community.py -- \
      --id <unit> --out <dir> --manifest <actions.json> \
      --part <body.model> [--part <head.model> ...] [--weapon <weapon.model>]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "hkx"))
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

from hkxread import Packfile  # noqa: E402
import skeleton as S  # noqa: E402

# the add-on's constants, copied verbatim from model/skeleton_space.py and utils.py
BONE_AXIS_ADAPTER = Matrix.Rotation(math.radians(-90.0), 4, "Z")
BONE_AXIS_ADAPTER_INV = BONE_AXIS_ADAPTER.inverted()
BLENDER_TO_DX = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
DX_TO_BLENDER = BLENDER_TO_DX.inverted()


def dx_to_blender(M):
    return DX_TO_BLENDER @ M @ BLENDER_TO_DX


def canonical_ci(name):
    hit = S.canonical(name)
    if hit:
        return hit
    low = name.lower()
    for k, v in S.BONE_MAP.items():
        if k.lower() == low:
            return v
    return name


_ap = argparse.ArgumentParser()
_ap.add_argument("--id", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--manifest", default="")
_ap.add_argument("--part", action="append", default=[])
_ap.add_argument("--weapon", default="")
_ap.add_argument("--stride", type=int, default=1)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

if "dow2_tools" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="dow2_tools")

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

# ------------------------------------------------------------------ assembly, by the add-on
for i, part in enumerate(A.part):
    bpy.ops.import_scene.dow2_model(filepath=str(part), merge=(i > 0), reset_scene=False)
    print(f"IMPORTED part {Path(part).name} merge={i > 0}")
if A.weapon:
    bpy.ops.import_scene.dow2_model(filepath=str(A.weapon), merge=True, reset_scene=False)
    print(f"IMPORTED weapon {Path(A.weapon).name}")

arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("the add-on produced no armature")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"ASSEMBLED armature={arm.name} bones={len(arm.data.bones)} meshes={len(meshes)} "
      f"verts={sum(len(m.data.vertices) for m in meshes)}")

# ------------------------------------------------------------------ clips, by the add-on's maths
rest_world = {b.name.lower(): b.matrix_local @ BONE_AXIS_ADAPTER_INV for b in arm.data.bones}


def rest_local_for(pb, parent_pb):
    """Rest of `pb` relative to `parent_pb` (the add-on's get_rest_local_matrix).

    The parent comes from the CLIP's hierarchy, matched to the armature, not from the model's own
    parent: a clip whose hierarchy differs from the model's (the necron's) otherwise produces a
    delta against the wrong rest and the bones fly metres away.
    """
    w = rest_world.get(pb.name.lower())
    if w is None:
        return None
    if parent_pb is None:
        return w
    pw = rest_world.get(parent_pb.name.lower())
    return pw.inverted() @ w if pw is not None else w

for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

arm.animation_data_create()
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)


def apply_clip(clip_path, action_name, fps, frames):
    pf = Packfile.open(clip_path)
    sk = pf.skeleton()
    anim = pf.animation()
    if sk is None or anim is None:
        return None
    names = sk["bone_names"]
    parents = sk["parents"]
    # the add-on keeps the model's own bone names (`bip01 r thigh`), so the clip's bones are
    # matched against the armature's names case-insensitively -- NOT through our canonical
    # vocabulary, which would find nothing and leave every bone unkeyed.
    arm_bones = {b.name.lower(): b for b in arm.pose.bones}
    pb_by_index = {}
    for i, n in enumerate(names):
        pb = arm_bones.get(n.lower())
        if pb is not None:
            pb_by_index[i] = pb
    parent_pb = {}
    for i in pb_by_index:
        p = parents[i]
        if p >= 0 and p in pb_by_index:
            parent_pb[i] = pb_by_index[p]
    print(f"  mapped {len(pb_by_index)}/{len(names)} clip bones onto {arm.name}")

    act = bpy.data.actions.new(action_name)
    act.use_fake_user = True
    arm.animation_data.action = act
    try:
        if arm.animation_data.action_slot is None and act.slots:
            arm.animation_data.action_slot = act.slots[0]
    except AttributeError:
        pass

    bpy.context.scene.render.fps = 30
    bpy.context.scene.render.fps_base = 30.0 / max(1e-6, fps)
    stride = max(1, A.stride)
    for f in frames:
        bpy.context.scene.frame_set(f + 1)
        # clip locals in Blender space, composed to world
        local = []
        for i in range(len(names)):
            t = anim["tracks"][i]
            q = t["rotation"][f]
            M = Matrix.LocRotScale(Vector(t["translation"][f]),
                                   Quaternion((q[3], q[0], q[1], q[2])),
                                   Vector(t["scale"][f]))
            local.append(dx_to_blender(M))
        world = [None] * len(local)

        def resolve(i):
            if world[i] is not None:
                return world[i]
            p = parents[i]
            world[i] = local[i] if p < 0 else resolve(p) @ local[i]
            return world[i]

        for i in range(len(local)):
            resolve(i)
        # Place each bone at the clip's world pose, expressed in the armature's own convention
        # (rest = model world @ ADAPTER). Blender then derives the local transform against the
        # armature's real parent, so a clip whose hierarchy differs from the model's (the necron's)
        # still lands correctly, and a matching one gives the same result as the delta form.
        # the add-on's own sequence: rest^-1 @ (parent^-1 @ world), conjugated by the adapter
        for i, pb in pb_by_index.items():
            rl = rest_local_for(pb, parent_pb.get(i))
            if rl is None:
                continue
            pidx = parents[i]
            pw = world[pidx] if pidx >= 0 else Matrix.Identity(4)
            delta = rl.inverted() @ (pw.inverted() @ world[i])
            delta = BONE_AXIS_ADAPTER_INV @ delta @ BONE_AXIS_ADAPTER
            pb.location, pb.rotation_quaternion, pb.scale = delta.decompose()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            pb.keyframe_insert("location", frame=f + 1)
            pb.keyframe_insert("rotation_quaternion", frame=f + 1)
            pb.keyframe_insert("scale", frame=f + 1)
    _fc = []
    try:
        _fc = list(act.fcurves)
    except Exception:
        pass
    if not _fc:
        for _l in getattr(act, "layers", []):
            for _st in getattr(_l, "strips", []):
                for _cb in getattr(_st, "channelbags", []):
                    _fc.extend(list(_cb.fcurves))
    print(f"  KEYED {action_name}: fcurves={len(_fc)} keys="
          f"{sum(len(fc.keyframe_points) for fc in _fc)} frames={len(frames)}")
    # Park the action on its own NLA track. With Blender 5.x slotted actions, exporting several
    # actions by assigning them one after another collapses them (the exporter evaluates the
    # armature with no action bound and writes two constant keys). NLA tracks are the supported
    # way to export a set of actions.
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = action_name
    strip = track.strips.new(action_name, 1, act)
    strip.name = action_name
    track.mute = False
    return {"frames": len(frames), "fps": fps / stride, "source_fps": fps}


meta = {}
if A.manifest:
    manifest = json.loads(Path(A.manifest).read_text())
    for name, entry in manifest.get("actions", {}).items():
        clip = entry.get("clip")
        if not clip:
            continue
        path = Path(entry["file"])
        try:
            pf = Packfile.open(path)
            anim = pf.animation()
        except Exception as exc:
            print(f"SKIP {name}: {exc}")
            continue
        if anim is None:
            print(f"SKIP {name}: not a delta-compressed clip")
            continue
        stride = max(1, A.stride)
        frames = list(range(0, anim["numberOfPoses"], stride))
        if frames[-1] != anim["numberOfPoses"] - 1:
            frames.append(anim["numberOfPoses"] - 1)
        info = apply_clip(path, name, anim["frame_rate"], frames)
        if info is None:
            continue
        info.update({"source_clip": clip, "duration": anim["duration"],
                     "events": entry.get("events", []),
                     "acting_frame": entry.get("acting_frame", {})})
        meta[name] = info
        print(f"ACTION {name} <- {clip} {len(frames)}f")

arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=True, export_animation_mode="ACTIONS",
                          export_optimize_animation_size=False,
                          export_optimize_animation_keep_anim_armature=True)
print(f"EXPORTED {dest} actions={len(bpy.data.actions)}")
if meta:
    (out / f"{A.id}.actions.json").write_text(json.dumps(
        {"unit": A.id, "source": A.manifest, "actions": meta}, indent=1))
    print(f"ACTIONS {out / (A.id + '.actions.json')}")
