"""attach_weapon_baked.py — parent a weapon into a unit GLB, the way a creator does it.

This is the researched construction: the weapon becomes part of the unit asset, bone-parented to
the hand, with the transform authored once. No runtime placement, no aim vector, no IK solving a
pose that was authored with empty hands.

The weapon is placed so its grip (its origin, set by weapon_glb.py) sits in the right hand and its
barrel points along the body's forward at the authored frame, then parented to `hand_R` with the
parent-inverse matrix fixed so the offset is constant for every clip.

Usage:
  blender -b -P tools/blender/attach_weapon_baked.py -- --unit <unit.glb> --weapon <weapon.glb> \
      --out <dir> --id <unit_id> [--clip idle --frame 1]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--unit", required=True)
_ap.add_argument("--weapon", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--clip", default="idle")
_ap.add_argument("--frame", type=int, default=1)
_ap.add_argument("--hand", default="hand_R")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.unit).resolve()))
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
pb = arm.pose.bones.get(A.hand)
if pb is None:
    raise SystemExit(f"no bone {A.hand}")
# REST pose, deliberately: the weapon is rigidly attached to the hand bone, so it must sit in
# the hand the mesh was bound in. Using the posed matrix instead put the weapon where the clip
# happened to place the hand, and made the GLB's default pose disagree with its bind-pose mesh.
rest = arm.matrix_world @ pb.bone.matrix_local
hand_pos = rest.translation.copy()
print(f"HAND {A.hand} world={tuple(round(v, 3) for v in hand_pos)}")

# drop any weapon already baked in (re-baking must not stack a second rifle in the hand)
KNOWN = ("lasgun", "bolter", "shuriken", "shoota")
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.name.split(".")[0] in KNOWN:
        bpy.data.objects.remove(o, do_unlink=True)

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(Path(A.weapon).resolve()))
weapon = next(o for o in bpy.data.objects if o not in before and o.type == "MESH")
weapon.parent = None

# forward = the rig's forward in REST pose (the mesh faces -Y)
fwd = Vector((0, -1, 0))
print(f"FORWARD {tuple(round(v, 3) for v in fwd)}")

# Rigid-attach by SKINNING, and bind it for the HOLDING pose, not the rest pose.
#
# Two lessons are baked into this block:
#  * bone parenting through the glTF exporter put the weapon 0.50 m from the hand, so the weapon
#    is skinned to the hand bone at weight 1.0 and follows it through the same deformation path
#    as the body;
#  * placing it against the REST hand made the barrel point up and back, because the clip then
#    rotates the hand and carries the weapon with it. The bind transform is therefore solved for
#    the holding pose: weapon_rest = hand_rest * inverse(hand_posed) * desired_posed, so that
#    when the clip poses the hand onto the grip the barrel points along the body's forward.
if A.clip in actions:
    arm.animation_data.action = actions[A.clip]
    try:
        if arm.animation_data.action_slot is None and actions[A.clip].slots:
            arm.animation_data.action_slot = actions[A.clip].slots[0]
    except AttributeError:
        pass
bpy.context.scene.frame_set(A.frame)
bpy.context.view_layer.update()

hand_rest = arm.matrix_world @ pb.bone.matrix_local
hand_posed = arm.matrix_world @ pb.matrix
desired = Vector((0, 0, 1)).rotation_difference(fwd).to_matrix().to_4x4()
desired.translation = hand_posed.translation.copy()
weapon.matrix_world = hand_rest @ hand_posed.inverted() @ desired
bpy.context.view_layer.update()
print(f"BOUND weapon for the holding pose (grip at "
      f"{tuple(round(v, 3) for v in hand_posed.translation)})")

for vg in list(weapon.vertex_groups):
    weapon.vertex_groups.remove(vg)
grp = weapon.vertex_groups.new(name=A.hand)
grp.add([v.index for v in weapon.data.vertices], 1.0, "REPLACE")
mod = weapon.modifiers.new("armature", "ARMATURE")
mod.object = arm
weapon.parent = arm
bpy.context.view_layer.update()

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"
# select EVERYTHING (body mesh included): selecting only the armature and the weapon exported
# a GLB whose sole mesh was the lasgun — the soldier was missing
# Clear the POSE, not the animation data: animation_data_clear() also drops the action
# assignments and the export then carries zero clips (measured: every re-baked unit lost all
# 31 animations). Detaching the active action and zeroing the pose gives a rest-pose export
# while every action stays in bpy.data.actions for the ACTIONS export mode to pick up.
if arm.animation_data:
    arm.animation_data.action = None
for pbone in arm.pose.bones:
    pbone.rotation_quaternion = (1, 0, 0, 0)
    pbone.location = (0, 0, 0)
    pbone.scale = (1, 1, 1)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(
    filepath=str(dest),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="ACTIONS",
)
print(f"EXPORTED {dest}")
