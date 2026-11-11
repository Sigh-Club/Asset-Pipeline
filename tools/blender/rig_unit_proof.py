#!/usr/bin/env python3
"""rig_unit_proof.py — shared humanoid skeleton + animation proof for a unit mesh.

Takes the decimated GLB produced by tools/blender/inspect_mesh.py, builds a
Mixamo-compatible humanoid armature, skins the mesh, authors idle/walk/aim
clips, exports a GLB with clips, and renders frame sequences for review.

This is the P0 "does it read as fluid" gate: the clips are deliberately simple
(procedural curves), the point is to prove the rig/skin/animation pipeline
works on an image-to-3D mesh before scaling to the roster.

Usage:
    blender -b -P tools/blender/rig_unit_proof.py -- \
        --glb output/img23d/<slug>/inspect/lod0.glb \
        --out output/img23d/<slug>/rig --render
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unit_pose  # noqa: E402

# Bone layout: name -> (head, tail, parent, connected). Mixamo-compatible names
# so humanoid clips can be retargeted. Coordinates are authored in metres for a
# 1.9 m unit facing -Y, origin at the feet.
def bone_layout(height: float) -> dict:
    s = height / 1.9

    def p(x, y, z):
        return (x * s, y * s, z * s)

    return {
        "Hips": (p(0, 0, 0.98), p(0, 0, 1.08), None, False),
        "Spine": (p(0, 0, 1.08), p(0, 0, 1.20), "Hips", True),
        "Spine1": (p(0, 0, 1.20), p(0, 0, 1.34), "Spine", True),
        "Spine2": (p(0, 0, 1.34), p(0, 0, 1.50), "Spine1", True),
        "Neck": (p(0, 0, 1.50), p(0, 0, 1.60), "Spine2", True),
        "Head": (p(0, 0, 1.60), p(0, 0, 1.86), "Neck", True),
        "LeftShoulder": (p(0.04, 0, 1.48), p(0.16, 0, 1.50), "Spine2", False),
        "LeftArm": (p(0.16, 0, 1.50), p(0.28, -0.10, 1.36), "LeftShoulder", True),
        "LeftForeArm": (p(0.28, -0.10, 1.36), p(0.19, -0.28, 1.30), "LeftArm", True),
        "LeftHand": (p(0.19, -0.28, 1.30), p(0.10, -0.32, 1.28), "LeftForeArm", True),
        "RightShoulder": (p(-0.04, 0, 1.48), p(-0.16, 0, 1.50), "Spine2", False),
        "RightArm": (p(-0.16, 0, 1.50), p(-0.28, -0.10, 1.36), "RightShoulder", True),
        "RightForeArm": (p(-0.28, -0.10, 1.36), p(-0.19, -0.28, 1.30), "RightArm", True),
        "RightHand": (p(-0.19, -0.28, 1.30), p(-0.10, -0.32, 1.28), "RightForeArm", True),
        "LeftUpLeg": (p(0.13, 0, 0.94), p(0.14, 0, 0.55), "Hips", False),
        "LeftLeg": (p(0.14, 0, 0.55), p(0.15, 0, 0.12), "LeftUpLeg", True),
        "LeftFoot": (p(0.15, 0, 0.12), p(0.15, -0.14, 0.03), "LeftLeg", True),
        "LeftToeBase": (p(0.15, -0.14, 0.03), p(0.15, -0.24, 0.02), "LeftFoot", True),
        "RightUpLeg": (p(-0.13, 0, 0.94), p(-0.14, 0, 0.55), "Hips", False),
        "RightLeg": (p(-0.14, 0, 0.55), p(-0.15, 0, 0.12), "RightUpLeg", True),
        "RightFoot": (p(-0.15, 0, 0.12), p(-0.15, -0.14, 0.03), "RightLeg", True),
        "RightToeBase": (p(-0.15, -0.14, 0.03), p(-0.15, -0.24, 0.02), "RightFoot", True),
    }


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--render", action="store_true")
    p.add_argument("--clips", default="all", choices=("all", "proof"),
                   help="all = the 9 contract clips; proof = idle/walk/aim only")
    p.add_argument("--bind", default="distance", choices=("distance", "authored"),
                   help="distance = the img23d proof weighting; authored = use the "
                        "per-part vertex groups written by parametric_unit.py")
    p.add_argument("--hold", default="relaxed", choices=("relaxed", "ranged", "melee"),
                   help="authored arm pose; must match the pose the mesh was built with")
    p.add_argument("--samples", type=int, default=16)
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_and_normalise(path: Path, bind: str = "distance"):
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh in glb")

    if bind == "authored":
        # `parametric_unit.py` names every part `<bone>__<slot>__<tag>`. Bind the
        # parts rigidly to their bone before the join; the authored mesh is
        # already in metres with feet at z=0, so no rescale or re-centre.
        for o in meshes:
            bone = o.name.split("__")[0]
            if bone not in bone_layout(1.9):
                raise SystemExit(f"part {o.name!r} has no rig bone prefix")
            vg = o.vertex_groups.get(bone) or o.vertex_groups.new(name=bone)
            vg.add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
        bpy.ops.object.select_all(action="DESELECT")
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
        obj.name = "unit_body"
        obj.data.name = "unit_body_mesh"
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        return obj

    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active

    # world-space bounds
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    height = maxs.z - mins.z
    scale = 1.9 / height
    obj.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    centre = (mins + maxs) / 2
    obj.location = (-centre.x, -centre.y, -mins.z)
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    obj.name = "unit_body"
    obj.data.name = "unit_body_mesh"
    return obj


def authored_bind(obj, arm):
    """Use the per-part vertex groups instead of distance weighting."""
    present = [b.name for b in arm.data.bones if obj.vertex_groups.get(b.name) is not None]
    if not present:
        raise SystemExit("authored bind: mesh carries no bone vertex groups")
    mod = obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    return "authored"


def build_armature(height: float, pose: str = "relaxed", authored: bool = False):
    arm_data = bpy.data.armatures.new("unit_rig")
    arm = bpy.data.objects.new("unit_rig", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    # Authored units use the same arm pose the mesh was built with; the img23d
    # route keeps the neutral A-pose layout.
    layout = unit_pose.bone_layout(height, pose) if authored else bone_layout(height)
    created = {}
    for name, (head, tail, parent, connect) in layout.items():
        b = arm_data.edit_bones.new(name)
        b.head = head
        b.tail = tail
        b.roll = 0.0
        created[name] = b
    for name, (head, tail, parent, connect) in layout.items():
        if parent:
            created[name].parent = created[parent]
            created[name].use_connect = connect
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.show_in_front = True
    return arm


def _segment_distance(point, head, tail):
    ab = tail - head
    denom = ab.dot(ab)
    if denom <= 1e-9:
        return (point - head).length
    t = max(0.0, min(1.0, (point - head).dot(ab) / denom))
    return (point - (head + ab * t)).length


def _bone_eligible(name, co):
    """Region gating so a left-leg bone never grabs the right boot."""
    x, y, z = co
    if name.startswith("Left") and x < -0.03:
        return False
    if name.startswith("Right") and x > 0.03:
        return False
    leg = ("UpLeg" in name) or ("Leg" in name and "Fore" not in name) or ("Foot" in name) or ("Toe" in name)
    if leg and z > 1.15:
        return False
    if name in ("Hips", "Spine", "Spine1", "Spine2") and z < 0.75:
        return False
    if name in ("Neck", "Head") and z < 1.35:
        return False
    if name in ("Neck",) and z > 1.85:
        return False
    return True


def auto_weight(obj, arm, iterations=6, max_influences=4, sigma=0.10):
    """Deterministic distance-to-bone-segment weights with Laplacian smoothing.

    Blender's bone-heat solver fails on fused image-to-3D meshes (returns with all
    vertices unweighted). Distance weighting is predictable and good enough for a
    locomotion proof; retopo/hand-painted weights remain the LOD0 production path.
    """
    mesh = obj.data
    segments = {}
    for bone in arm.data.bones:
        segments[bone.name] = (bone.head_local.copy(), bone.tail_local.copy())

    groups = {}
    for name in segments:
        groups[name] = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)

    verts = mesh.vertices
    n = len(verts)
    weights = [dict() for _ in range(n)]
    for v in verts:
        co = v.co
        cand = []
        for name, (head, tail) in segments.items():
            if not _bone_eligible(name, co):
                continue
            d = _segment_distance(co, head, tail)
            cand.append((d, name))
        cand.sort()
        top = cand[:max_influences]
        if not top:
            top = [(d, name) for d, name in sorted(
                ((_segment_distance(co, h, t), nm) for nm, (h, t) in segments.items()))[:max_influences]]
        acc = {}
        total = 0.0
        nearest = top[0][0]
        for d, name in top:
            if d > nearest + sigma * 3.0:
                continue
            w = math.exp(-((d / sigma) ** 2))
            acc[name] = w
            total += w
        for name in acc:
            acc[name] /= total
        weights[v.index] = acc

    # smooth across mesh edges to remove hard seams
    adjacency = [[] for _ in range(n)]
    for e in mesh.edges:
        a, b = e.vertices
        adjacency[a].append(b)
        adjacency[b].append(a)

    for _ in range(iterations):
        new_weights = []
        for i in range(n):
            acc = dict(weights[i])
            for k in acc:
                acc[k] *= 0.35
            neighbours = adjacency[i]
            if neighbours:
                share = 0.65 / len(neighbours)
                for j in neighbours:
                    for k, w in weights[j].items():
                        acc[k] = acc.get(k, 0.0) + w * share
            trimmed = sorted(acc.items(), key=lambda kv: kv[1], reverse=True)[:max_influences]
            total = sum(w for _, w in trimmed) or 1.0
            new_weights.append({k: w / total for k, w in trimmed})
        weights = new_weights

    # rigid extremities: boots and helmet should not smear across joints
    for i, acc in enumerate(weights):
        co = verts[i].co
        if co.z < 0.10:
            side = "Left" if co.x >= 0 else "Right"
            bone = f"{side}ToeBase" if co.y < -0.14 else f"{side}Foot"
            weights[i] = {bone: 1.0}
        elif co.z > 1.74:
            weights[i] = {"Head": 1.0}

    for i, acc in enumerate(weights):
        for name, w in acc.items():
            if w > 1e-4:
                groups[name].add([i], w, "REPLACE")

    # armature modifier + parent, without the heat solver
    mod = obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    return "distance"


def set_rot(arm, bone, axis, degrees):
    pb = arm.pose.bones[bone]
    pb.rotation_mode = "QUATERNION"
    from mathutils import Quaternion
    pb.rotation_quaternion = Quaternion(Vector(axis), math.radians(degrees))


def key_rot(arm, bone, frame):
    pb = arm.pose.bones[bone]
    pb.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def key_loc(arm, bone, frame):
    pb = arm.pose.bones[bone]
    pb.keyframe_insert(data_path="location", frame=frame)


def pose(arm, bone, rx=0.0, ry=0.0, rz=0.0):
    """Compose a rotation; set_rot() overwrites, which is fine for single-axis
    limbs but loses information for spine/hip combinations."""
    from mathutils import Euler
    pb = arm.pose.bones[bone]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = Euler(
        (math.radians(rx), math.radians(ry), math.radians(rz)), "XYZ").to_quaternion()


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)


def new_action(arm, name):
    reset_pose(arm)
    if arm.animation_data is None:
        arm.animation_data_create()
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    arm.animation_data.action = action
    return action


def author_idle(arm, fps):
    action = new_action(arm, "idle")
    frames = [1, 15, 30, 45, 60]
    for i, f in enumerate(frames):
        reset_pose(arm)
        phase = math.sin(2 * math.pi * (i / (len(frames) - 1)))
        set_rot(arm, "Spine", (1, 0, 0), 1.2 * phase)
        set_rot(arm, "Spine2", (1, 0, 0), -0.8 * phase)
        set_rot(arm, "Head", (1, 0, 0), 0.6 * phase)
        arm.pose.bones["Hips"].location = (0, 0, 0.006 * phase)
        for bone in ("Hips", "Spine", "Spine2", "Head"):
            key_rot(arm, bone, f)
        key_loc(arm, "Hips", f)
    return action


def author_walk(arm, fps):
    """In-place walk cycle, 30 frames at 30 fps (1 s), contact-passing-contact."""
    action = new_action(arm, "walk")
    # (frame, leg swing deg, knee bend deg, opposite leg swing, foot pitch)
    keys = [
        (1, 24, 4, -22, 10),
        (8, 6, 26, 4, -6),
        (15, -22, 6, 24, 10),
        (23, 4, 26, 6, -6),
        (30, 24, 4, -22, 10),
    ]
    for frame, lswing, lknee, rswing, foot in keys:
        reset_pose(arm)
        set_rot(arm, "LeftUpLeg", (1, 0, 0), lswing)
        set_rot(arm, "LeftLeg", (1, 0, 0), -lknee)
        set_rot(arm, "LeftFoot", (1, 0, 0), foot)
        set_rot(arm, "RightUpLeg", (1, 0, 0), rswing)
        set_rot(arm, "RightLeg", (1, 0, 0), -max(0.0, -lknee * 0.2))
        set_rot(arm, "RightFoot", (1, 0, 0), -foot)
        set_rot(arm, "Spine", (1, 0, 0), 3.0)
        set_rot(arm, "Spine2", (0, 0, 1), 2.5 if lswing > 0 else -2.5)
        set_rot(arm, "Hips", (0, 0, 1), -2.0 if lswing > 0 else 2.0)
        arm.pose.bones["Hips"].location = (0, 0, 0.02 if abs(lswing) < 10 else -0.01)
        for bone in ("LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg",
                     "RightFoot", "Spine", "Spine2", "Hips"):
            key_rot(arm, bone, frame)
        key_loc(arm, "Hips", frame)
    return action


def author_aim(arm, fps):
    """Aim/fire-ish upper-body layer: slight crouch, weapon lifted, recoil beat."""
    action = new_action(arm, "aim")
    poses = [
        (1, 0.0, 0.0),
        (8, -4.0, 3.0),
        (16, -6.0, 5.0),
        (20, -2.5, 4.0),   # recoil
        (30, 0.0, 0.0),
    ]
    for frame, crouch, lift in poses:
        reset_pose(arm)
        arm.pose.bones["Hips"].location = (0, 0, -0.03 + crouch * 0.002)
        set_rot(arm, "Spine", (1, 0, 0), 4.0 + lift)
        set_rot(arm, "Spine2", (1, 0, 0), 2.0 + lift * 0.6)
        set_rot(arm, "Neck", (1, 0, 0), -2.0)
        set_rot(arm, "LeftArm", (1, 0, 0), lift * 0.8)
        set_rot(arm, "RightArm", (1, 0, 0), lift * 0.8)
        set_rot(arm, "LeftUpLeg", (1, 0, 0), -4.0)
        set_rot(arm, "RightUpLeg", (1, 0, 0), 4.0)
        for bone in ("Spine", "Spine2", "Neck", "LeftArm", "RightArm",
                     "LeftUpLeg", "RightUpLeg"):
            key_rot(arm, bone, frame)
        key_loc(arm, "Hips", frame)
    return action



def author_run(arm, fps):
    """Faster, longer stride, forward lean, stronger arm swing. 24 frames."""
    action = new_action(arm, "run")
    keys = [
        (1, 38, 8, -34, 14),
        (6, 10, 48, 8, -12),
        (12, -34, 10, 38, 14),
        (18, 8, 48, 10, -12),
        (24, 38, 8, -34, 14),
    ]
    for frame, lswing, lknee, rswing, foot in keys:
        reset_pose(arm)
        pose(arm, "LeftUpLeg", rx=lswing)
        pose(arm, "LeftLeg", rx=-lknee)
        pose(arm, "LeftFoot", rx=foot)
        pose(arm, "RightUpLeg", rx=rswing)
        pose(arm, "RightLeg", rx=-max(0.0, -lknee * 0.2))
        pose(arm, "RightFoot", rx=-foot)
        pose(arm, "Spine", rx=12.0)
        pose(arm, "Spine2", rx=4.0, rz=4.0 if lswing > 0 else -4.0)
        pose(arm, "Hips", rz=-3.0 if lswing > 0 else 3.0)
        pose(arm, "LeftArm", rx=-rswing * 0.9)
        pose(arm, "RightArm", rx=-lswing * 0.9)
        arm.pose.bones["Hips"].location = (0, 0, 0.045 if abs(lswing) < 15 else -0.02)
        for b in ("LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg",
                  "RightFoot", "Spine", "Spine2", "Hips", "LeftArm", "RightArm"):
            key_rot(arm, b, frame)
        key_loc(arm, "Hips", frame)
    return action


def author_fire(arm, fps):
    """Shoulder the weapon, one recoil beat, settle. 20 frames."""
    action = new_action(arm, "fire")
    poses = [
        (1, 0.0, 0.0, 0.0),
        (3, 5.0, -8.0, 1.0),    # recoil: torso back, weapon up
        (7, 2.0, -3.0, 0.4),
        (14, 0.5, -1.0, 0.1),
        (20, 0.0, 0.0, 0.0),
    ]
    for frame, back, lift, jitter in poses:
        reset_pose(arm)
        pose(arm, "Spine", rx=-back)
        pose(arm, "Spine2", rx=-back * 0.5, rz=jitter)
        pose(arm, "Neck", rx=back * 0.4)
        pose(arm, "Head", rx=back * 0.3)
        pose(arm, "LeftArm", rx=lift)
        pose(arm, "RightArm", rx=lift)
        pose(arm, "LeftForeArm", rx=lift * 0.6)
        pose(arm, "RightForeArm", rx=lift * 0.6)
        for b in ("Spine", "Spine2", "Neck", "Head", "LeftArm", "RightArm",
                  "LeftForeArm", "RightForeArm"):
            key_rot(arm, b, frame)
    return action


def author_reload(arm, fps):
    """Drop the muzzle, magazine-out beat, seat, re-shoulder. 40 frames."""
    action = new_action(arm, "reload")
    poses = [
        (1, 0, 0, 0, 0),
        (8, -12, 10, 55, -8),
        (16, -14, 16, 85, -14),   # magazine out
        (24, -10, 8, 45, -6),     # magazine in
        (32, -3, 2, 12, -1),
        (40, 0, 0, 0, 0),
    ]
    for frame, muzzle, elbow, right_lift, tilt in poses:
        reset_pose(arm)
        pose(arm, "Spine", rx=muzzle * 0.4, rz=tilt * 0.5)
        pose(arm, "Spine2", rx=muzzle * 0.3, rz=tilt * 0.5)
        pose(arm, "Neck", rx=-muzzle * 0.4)
        pose(arm, "LeftArm", rx=muzzle)
        pose(arm, "LeftForeArm", rx=elbow)
        pose(arm, "RightArm", rx=muzzle + right_lift * 0.25)
        pose(arm, "RightForeArm", rx=right_lift)
        pose(arm, "RightHand", rx=right_lift * 0.4)
        for b in ("Spine", "Spine2", "Neck", "LeftArm", "LeftForeArm",
                  "RightArm", "RightForeArm", "RightHand"):
            key_rot(arm, b, frame)
    return action


def author_hit(arm, fps):
    """Impact recoil: torso and head snap back, arms open, one stagger step."""
    action = new_action(arm, "hit")
    poses = [
        (1, 0.0, 0.0, 0.0),
        (3, -18.0, 10.0, -0.03),
        (7, -10.0, 6.0, -0.015),
        (12, 4.0, -2.0, 0.005),
        (18, 0.0, 0.0, 0.0),
    ]
    for frame, back, arms, hip_y in poses:
        reset_pose(arm)
        pose(arm, "Spine", rx=back)
        pose(arm, "Spine2", rx=back * 0.6)
        pose(arm, "Neck", rx=back * 0.5)
        pose(arm, "Head", rx=back * 0.8)
        pose(arm, "LeftArm", rz=-arms)
        pose(arm, "RightArm", rz=arms)
        pose(arm, "LeftUpLeg", rx=-arms * 0.4)
        pose(arm, "RightUpLeg", rx=arms * 0.2)
        arm.pose.bones["Hips"].location = (0, hip_y, 0)
        for b in ("Spine", "Spine2", "Neck", "Head", "LeftArm", "RightArm",
                  "LeftUpLeg", "RightUpLeg"):
            key_rot(arm, b, frame)
        key_loc(arm, "Hips", frame)
    return action


def author_death(arm, fps):
    """Stagger, knees buckle, fall back to the ground. 45 frames, in place."""
    action = new_action(arm, "death")
    poses = [
        # frame, hips_z, hips_rx, spine_rx, knee, head_rx
        (1, 0.00, 0.0, 0.0, 0, 0.0),
        (8, -0.06, -6.0, -10.0, 18, -8.0),
        (18, -0.30, 18.0, -18.0, 55, -12.0),
        (30, -0.62, 55.0, -10.0, 70, -6.0),
        (39, -0.82, 82.0, 6.0, 40, 4.0),
        (45, -0.86, 88.0, 8.0, 28, 6.0),
    ]
    for frame, hz, hrx, srx, knee, head in poses:
        reset_pose(arm)
        arm.pose.bones["Hips"].location = (0, 0, hz)
        pose(arm, "Hips", rx=hrx)
        pose(arm, "Spine", rx=srx)
        pose(arm, "Spine2", rx=srx * 0.5)
        pose(arm, "Neck", rx=head * 0.4)
        pose(arm, "Head", rx=head)
        pose(arm, "LeftUpLeg", rx=-knee * 0.5)
        pose(arm, "RightUpLeg", rx=-knee * 0.5)
        pose(arm, "LeftLeg", rx=knee)
        pose(arm, "RightLeg", rx=knee)
        pose(arm, "LeftArm", rx=-20.0)
        pose(arm, "RightArm", rx=-20.0)
        for b in ("Hips", "Spine", "Spine2", "Neck", "Head", "LeftUpLeg",
                  "RightUpLeg", "LeftLeg", "RightLeg", "LeftArm", "RightArm"):
            key_rot(arm, b, frame)
        key_loc(arm, "Hips", frame)
    return action


def author_melee(arm, fps):
    """Wind-up, swing across the body, recover. 30 frames."""
    action = new_action(arm, "melee")
    poses = [
        (1, 0, 0, 0, 0),
        (7, -55, 22, -14, 8),     # wind-up: arm back, torso twisted
        (14, 35, -26, 26, -6),    # swing through
        (20, 12, -14, 14, -3),
        (30, 0, 0, 0, 0),
    ]
    for frame, rarm, twist, forward, hips in poses:
        reset_pose(arm)
        pose(arm, "Spine", rx=forward * 0.5, rz=twist)
        pose(arm, "Spine2", rx=forward * 0.5, rz=twist)
        pose(arm, "Hips", rz=hips)
        pose(arm, "RightArm", rx=rarm, rz=-twist * 0.6)
        pose(arm, "RightForeArm", rx=-abs(rarm) * 0.3)
        pose(arm, "LeftArm", rx=-rarm * 0.4)
        pose(arm, "LeftUpLeg", rx=-forward * 0.4)
        pose(arm, "RightUpLeg", rx=forward * 0.4)
        for b in ("Spine", "Spine2", "Hips", "RightArm", "RightForeArm",
                  "LeftArm", "LeftUpLeg", "RightUpLeg"):
            key_rot(arm, b, frame)
    return action


def setup_render(out_dir: Path, samples: int):
    scene = bpy.context.scene
    engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
    scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = samples
    scene.render.resolution_x = 480
    scene.render.resolution_y = 640
    for candidate in ("AgX", "Filmic", "Standard"):
        try:
            scene.view_settings.view_transform = candidate
            break
        except TypeError:
            continue

    world = bpy.data.worlds.new("proof_world")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.05, 0.06, 0.08, 1.0)
        bg.inputs[1].default_value = 0.7
    scene.world = world

    key = bpy.data.lights.new("key", type="AREA")
    key.energy = 1400
    key.size = 3.0
    ko = bpy.data.objects.new("key", key)
    ko.location = (2.5, -3.0, 3.0)
    ko.rotation_euler = (0.9, 0.2, 0.6)
    bpy.context.collection.objects.link(ko)

    rim = bpy.data.lights.new("rim", type="AREA")
    rim.energy = 800
    rim.size = 2.5
    ro = bpy.data.objects.new("rim", rim)
    ro.location = (-2.5, 2.0, 2.5)
    ro.rotation_euler = (1.2, 0.0, -2.2)
    bpy.context.collection.objects.link(ro)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2.6
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    centre = Vector((0, 0, 1.0))
    cam.location = centre + Vector((3.4, -1.2, 0.55))
    direction = centre - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return out_dir


def render_clip_frames(arm, action, out_dir: Path, frames, step):
    scene = bpy.context.scene
    arm.animation_data.action = action
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in range(1, frames + 1, step):
        scene.frame_set(f)
        scene.render.filepath = str(out_dir / f"{action.name}_{f:03d}.png")
        bpy.ops.render.render(write_still=True)


def stash_to_nla(arm, action):
    ad = arm.animation_data
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, int(action.frame_range[0]), action)
    strip.name = action.name
    track.mute = True


def main():
    args = parse_args()
    glb = Path(args.glb).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    body = import_and_normalise(glb, args.bind)
    corners = [body.matrix_world @ Vector(c) for c in body.bound_box]
    height = max(c.z for c in corners) - min(c.z for c in corners)
    if args.bind == "authored":
        # Accessories (banners, thrusters) may exceed the body; the skeleton is
        # authored for the 1.9 m body and must not be rescaled by them.
        height = 1.9

    arm = build_armature(height, args.hold, authored=(args.bind == "authored"))
    mode = authored_bind(body, arm) if args.bind == "authored" else auto_weight(body, arm)

    scene = bpy.context.scene
    scene.render.fps = 30
    clip_builders = {
        "idle": author_idle, "walk": author_walk, "run": author_run,
        "aim": author_aim, "fire": author_fire, "reload": author_reload,
        "hit": author_hit, "death": author_death, "melee": author_melee,
    }
    if args.clips == "proof":
        clip_builders = {k: clip_builders[k] for k in ("idle", "walk", "aim")}
    for builder in clip_builders.values():
        builder(arm, 30)
    actions = [bpy.data.actions.get(n) for n in clip_builders]

    if args.render:
        setup_render(out / "frames", args.samples)
        for action in actions:
            if action is None:
                continue
            end = int(action.frame_range[1])
            render_clip_frames(arm, action, out / "frames" / action.name, end, max(1, end // 8))

    for action in actions:
        stash_to_nla(arm, action)

    # export mesh + skeleton + clips
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    glb_out = out / "unit_rigged.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_out),
        use_selection=True,
        export_format="GLB",
        export_animation_mode="NLA_TRACKS",
        export_anim_slide_to_zero=True,
        export_yup=True,
    )

    # diagnostic: confirm the action actually drives the pose and the mesh
    diag = {}
    for action in actions:
        arm.animation_data.action = action
        samples = {}
        for f in (1, 8, 15):
            scene.frame_set(f)
            bpy.context.view_layer.update()
            pb = arm.pose.bones["LeftUpLeg"]
            samples[f] = [round(v, 4) for v in pb.rotation_quaternion]
        diag[action.name] = samples
    print("POSE-DIAG:", json.dumps(diag))
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "unit_rigged.blend"))

    bones = [b.name for b in arm.data.bones]
    report = {
        "source": str(glb),
        "height_m": round(height, 3),
        "skin_mode": mode,
        "bones": len(bones),
        "bone_names": bones,
        "actions": [{"name": a.name, "frames": [a.frame_range[0], a.frame_range[1]]} for a in actions],
        "glb": str(glb_out),
        "glb_bytes": glb_out.stat().st_size if glb_out.exists() else 0,
        "pose_diag": diag,
    }
    (out / "rig_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


main()
