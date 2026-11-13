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
tpl_pts = [Vector(b["head"]) for b in TPL["bones"]] + [Vector(b["tail"]) for b in TPL["bones"]]
tlo = Vector((min(p.x for p in tpl_pts), min(p.y for p in tpl_pts), min(p.z for p in tpl_pts)))
thi = Vector((max(p.x for p in tpl_pts), max(p.y for p in tpl_pts), max(p.z for p in tpl_pts)))
if A.no_fit:
    fit_scale = Vector((1, 1, 1))
    fit_off = Vector((0, 0, 0))
else:
    # per-axis bbox fit: a uniform height scale puts bones outside a bulky
    # creature (measured on the carnifex: pelvis 114 cm off the mesh)
    fit_scale = Vector(((hi.x - lo.x) / max(1e-6, thi.x - tlo.x),
                        (hi.y - lo.y) / max(1e-6, thi.y - tlo.y),
                        (hi.z - lo.z) / max(1e-6, thi.z - tlo.z)))
    fit_off = lo - Vector((tlo.x * fit_scale.x, tlo.y * fit_scale.y, tlo.z * fit_scale.z))
scale = fit_scale
print(f"FIT mesh=({hi.x-lo.x:.2f},{hi.y-lo.y:.2f},{hi.z-lo.z:.2f}) "
      f"scale=({fit_scale.x:.3f},{fit_scale.y:.3f},{fit_scale.z:.3f})")


def fit_point(p):
    v = Vector(p)
    return Vector((v.x * scale.x, v.y * scale.y, v.z * scale.z)) + fit_off


_fb = [fit_point(b["head"]) for b in TPL["bones"]] + [fit_point(b["tail"]) for b in TPL["bones"]]
print("FITTED bone bbox", tuple(round(min(p[i] for p in _fb), 2) for i in range(3)),
      tuple(round(max(p[i] for p in _fb), 2) for i in range(3)))
print("MESH bbox", tuple(round(v, 2) for v in lo), tuple(round(v, 2) for v in hi),
      "obj_matrix", tuple(round(v, 2) for v in body.matrix_world.to_translation()))

# ------------------------------------------------------------------ armature
arm_data = bpy.data.armatures.new(f"{A.id}_rig")
arm = bpy.data.objects.new(f"{A.id}_rig", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
created = {}
for spec in TPL["bones"]:
    b = arm_data.edit_bones.new(spec["name"])
    b.head = fit_point(spec["head"])
    b.tail = fit_point(spec["tail"])
    b.use_deform = bool(spec.get("deform", True))
    r = float(spec.get("radius", 0.08)) * (scale.x + scale.y + scale.z) / 3
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
# Distance-based weighting: Blender's heat weighting returns empty groups on
# non-manifold shells and the envelope bind does the same on these bases, so the
# weights are computed directly. Each vertex is weighted to its three nearest
# deform bones with an inverse-distance falloff, which blends across joints.
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
mod = body.modifiers.new("armature", "ARMATURE")
mod.object = arm
body.parent = arm

import math
from mathutils import Vector as _V

deform_bones = [b for b in arm.data.bones if b.use_deform]
segments = [(b.name, arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local)
            for b in deform_bones]
for name, _h, _t in segments:
    if name not in body.vertex_groups:
        body.vertex_groups.new(name=name)
vgroups = {g.name: g for g in body.vertex_groups}


def seg_dist(p, a, b):
    ab = b - a
    d2 = ab.length_squared
    t = 0.0 if d2 < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / d2))
    return (p - (a + ab * t)).length


POWER = 4.0
MAXB = 3
weighted = {b.name: 0 for b in deform_bones}
for v in body.data.vertices:
    p = body.matrix_world @ v.co
    ds = sorted(((seg_dist(p, a, b), n) for n, a, b in segments))[:MAXB]
    ws = [(1.0 / max(1e-4, d) ** POWER, n) for d, n in ds]
    total = sum(w for w, _ in ws) or 1.0
    for w, n in ws:
        w /= total
        if w > 0.01:
            vgroups[n].add([v.index], w, "REPLACE")
            weighted[n] += 1
print("BIND proximity groups", len(vgroups))

orphans = [n for n, c in weighted.items() if c == 0]
print("BIND orphan_deform_bones", len(orphans), orphans[:8])

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
