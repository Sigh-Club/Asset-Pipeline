"""rig_template.py — build a production skeleton from a rig template and bind a mesh.

Rig templates are declarative: bone names, hierarchy, rest positions, deform
flags and skin radii. The same builder serves humanoids (MPFB), aliens and
monsters, so a creature is not a special case with hand-written code.

Bone budgets follow the measured shipped-game references (see
configs/rigs/*.json "reference"): DoW DE kroot_hounds 30 / krootox 82 /
daemonprince 33 / kroot_warrior 43, XCOM EU soldier 63.

Usage:
  blender -b -P tools/blender/rig_template.py -- \
    --template configs/rigs/quadruped.json --mesh output/base/beast_base.glb \
    --out output/units/beast --id beast [--no-fit]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]

_ap = argparse.ArgumentParser()
_ap.add_argument("--template", required=True)
_ap.add_argument("--mesh", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--no-fit", action="store_true", help="keep template coordinates")
_ap.add_argument("--export", action="store_true", default=True)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

TPL = json.loads((ROOT / A.template).read_text()) if not Path(A.template).is_absolute() \
    else json.loads(Path(A.template).read_text())

# ------------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.mesh).resolve()))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"no mesh in {A.mesh}")
body = max(meshes, key=lambda o: len(o.data.vertices))
for o in meshes:
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
print("MESH", body.name, len(body.data.vertices), "verts", len(body.data.polygons), "polys")

# ------------------------------------------------------------------ fit
lo = Vector((min(v.co.x for v in body.data.vertices),
             min(v.co.y for v in body.data.vertices),
             min(v.co.z for v in body.data.vertices)))
hi = Vector((max(v.co.x for v in body.data.vertices),
             max(v.co.y for v in body.data.vertices),
             max(v.co.z for v in body.data.vertices)))
mesh_h = hi.z - lo.z
tpl_h = max(b["head"][2] for b in TPL["bones"] + [{"head": [0, 0, 0]}])
scale = 1.0 if A.no_fit else mesh_h / max(1e-6, TPL["height_m"])
print(f"FIT mesh_height={mesh_h:.3f} template_height={TPL['height_m']} scale={scale:.4f}")

# ------------------------------------------------------------------ armature
arm_data = bpy.data.armatures.new(f"{A.id}_rig")
arm = bpy.data.objects.new(f"{A.id}_rig", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
created = {}
for spec in TPL["bones"]:
    b = arm_data.edit_bones.new(spec["name"])
    b.head = Vector(spec["head"]) * scale
    b.tail = Vector(spec["tail"]) * scale
    b.use_deform = bool(spec.get("deform", True))
    r = float(spec.get("radius", 0.08)) * scale
    b.head_radius = r
    b.tail_radius = r
    b.envelope_distance = r * 1.6
    created[spec["name"]] = b
for spec in TPL["bones"]:
    if spec.get("parent"):
        created[spec["name"]].parent = created[spec["parent"]]
        created[spec["name"]].use_connect = False
bpy.ops.object.mode_set(mode="OBJECT")
print("RIG bones", len(arm_data.bones), "deform", sum(1 for b in arm_data.bones if b.use_deform))

# ------------------------------------------------------------------ bind
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")


def count_weights():
    name_by_index = {g.index: g.name for g in body.vertex_groups}
    counts = {b.name: 0 for b in arm_data.bones if b.use_deform}
    for v in body.data.vertices:
        for g in v.groups:
            if g.weight > 1e-4:
                n = name_by_index.get(g.group)
                if n in counts:
                    counts[n] += 1
    return counts


weighted = count_weights()
if not any(weighted.values()):
    # heat weighting fails on non-manifold shells (skin-modifier bases); the
    # envelope bind uses the template radii instead
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    for g in list(body.vertex_groups):
        body.vertex_groups.remove(g)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
    weighted = count_weights()
    print("BIND fallback envelope")

orphans = [n for n, c in weighted.items() if c == 0]
print("BIND groups", len(body.vertex_groups), "orphan_deform_bones", len(orphans), orphans[:8])

# ------------------------------------------------------------------ export
out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_rigged.glb"
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
arm.data.pose_position = "REST"
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False, export_rest_position_armature=True)
print("EXPORTED", dest)
