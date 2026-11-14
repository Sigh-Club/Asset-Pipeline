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
_ap.add_argument("--fit", choices=("uniform", "bbox"), default="uniform",
                 help="uniform (default) fits height and grounds; bbox stretches per axis")
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
# bake any import transform: the fit and the weighting must share one space, or
# every vertex ends up nearest the bone at the origin (measured: thigh_L owned
# 30% of the mesh and the legs exploded on every clip)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print("MESH", body.name, len(body.data.vertices), "verts", len(body.data.polygons), "polys",
      "scale", tuple(round(v, 4) for v in body.scale))

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
elif A.fit == "bbox":
    # per-axis bbox fit. Only correct for a mesh already in the template's pose:
    # a T-posed or weapon-carrying base inflates one axis and stretches the
    # skeleton (measured: depth scaled 6x on the DoW2 ig_base).
    fit_scale = Vector(((hi.x - lo.x) / max(1e-6, thi.x - tlo.x),
                        (hi.y - lo.y) / max(1e-6, thi.y - tlo.y),
                        (hi.z - lo.z) / max(1e-6, thi.z - tlo.z)))
    fit_off = lo - Vector((tlo.x * fit_scale.x, tlo.y * fit_scale.y, tlo.z * fit_scale.z))
else:
    # uniform, centred, grounded fit: the base is already scaled to the unit
    # height by the base builder, so the authored template lands on it directly.
    s = (hi.z - lo.z) / max(1e-6, thi.z - tlo.z)
    fit_scale = Vector((s, s, s))
    tcx = (tlo.x + thi.x) / 2
    tcy = (tlo.y + thi.y) / 2
    mcx = (lo.x + hi.x) / 2
    mcy = (lo.y + hi.y) / 2
    fit_off = Vector((mcx - tcx * s, mcy - tcy * s, lo.z - tlo.z * s))
scale = fit_scale
print(f"FIT mode={A.fit} mesh=({hi.x-lo.x:.2f},{hi.y-lo.y:.2f},{hi.z-lo.z:.2f}) "
      f"scale={fit_scale.x:.3f}")


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
# attachment sockets: non-deform bones the game can parent gear to (weapons,
# backpacks, helmets). They export as nodes even though they carry no weights.
sockets = 0
for s in TPL.get("sockets", []):
    parent = created.get(s.get("parent"))
    if parent is None:
        continue
    base = parent.tail if s.get("at", "tail") == "tail" else parent.head
    pos = Vector(base) + Vector(s.get("offset", [0, 0, 0]))
    b = arm_data.edit_bones.new(s["name"])
    b.head = pos
    b.tail = pos + Vector((0, 0, 0.05))
    b.use_deform = False
    b.parent = parent
    sockets += 1
# limb fitting: place the arm and leg chains along the mesh's own limbs instead
# of trusting the template's pose. Shipped bases are A-posed or T-posed and the
# fingertips/feet are the reliable landmarks.
if not A.no_fit:
    world_co = [v.co for v in body.data.vertices]
    zmax = max(p.z for p in world_co)
    for side, sgn in (("L", 1), ("R", -1)):
        clav = created.get(f"clavicle_{side}")
        ua = created.get(f"upperarm_{side}")
        la = created.get(f"lowerarm_{side}")
        hd = created.get(f"hand_{side}")
        if not (clav and ua and la and hd):
            continue
        shoulder = clav.tail.copy()
        upper_body = [p for p in world_co if p.z > shoulder.z - (zmax * 0.25)]
        if not upper_body:
            continue
        tip = max(upper_body, key=lambda p: sgn * p.x)
        reach = (tip - shoulder).length
        if 0.25 < reach < 1.4:
            def at(f):
                return shoulder + (tip - shoulder) * f
            ua.head = shoulder
            ua.tail = at(0.45)
            la.head = ua.tail
            la.tail = at(0.80)
            hd.head = la.tail
            hd.tail = at(1.0)
            print(f"FIT arm {side} reach={reach:.2f} tip=({tip.x:.2f},{tip.y:.2f},{tip.z:.2f})")
        # legs: the foot chain ends at the lowest vertex on that side
        th = created.get(f"thigh_{side}")
        sh = created.get(f"shin_{side}")
        ft = created.get(f"foot_{side}")
        if not (th and sh and ft):
            continue
        hip = th.head.copy()
        lower = [p for p in world_co if sgn * p.x > 0 and p.z < hip.z * 0.75]
        if not lower:
            continue
        foot = min(lower, key=lambda p: p.z)
        if 0.2 < (foot - hip).length < 1.4:
            mid = hip + (foot - hip) * 0.55
            th.tail = mid
            sh.head = mid
            sh.tail = foot + (hip - foot).normalized() * 0.12
            ft.head = sh.tail
            ft.tail = foot
            print(f"FIT leg {side} foot=({foot.x:.2f},{foot.y:.2f},{foot.z:.2f})")

bpy.ops.object.mode_set(mode="OBJECT")
print("RIG bones", len(arm_data.bones), "deform", sum(1 for b in arm_data.bones if b.use_deform),
      "sockets", sockets)

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
segments = [(b.name, b.head_local, b.tail_local) for b in deform_bones]
# bone radius is the template's authored capture size: a small detail bone (jaw)
# must not out-compete the head for the skull/helmet surface
radius_of = {s["name"]: float(s.get("radius", 0.08)) for s in TPL["bones"]}
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
    p = v.co
    ds = sorted(((seg_dist(p, a, b), n) for n, a, b in segments))[:MAXB]
    ws = [((radius_of.get(n, 0.08) / max(1e-4, d)) ** POWER, n) for d, n in ds]
    total = sum(w for w, _ in ws) or 1.0
    for w, n in ws:
        w /= total
        if w > 0.01:
            vgroups[n].add([v.index], w, "REPLACE")
            weighted[n] += 1
print("BIND proximity groups", len(vgroups))

# coverage fallback: a bone that lost the nearest-3 contest still needs geometry,
# otherwise the rig has a dead joint. Claims are resolved by distance across all
# orphan bones so one fallback cannot strip another (measured: the jaw stripped
# the neck and the export lost it).
orphan_names = [n for n, c in weighted.items() if c == 0]
claims = {}
for name in orphan_names:
    seg = next((s for s in segments if s[0] == name), None)
    if not seg:
        continue
    _n, a, b = seg
    ranked = sorted(((seg_dist(v.co, a, b), v.index)
                     for v in body.data.vertices))[:max(4, len(body.data.vertices) // 200)]
    for d, vi in ranked:
        if vi not in claims or d < claims[vi][0]:
            claims[vi] = (d, name)
for vi, (_d, name) in claims.items():
    for other in vgroups.values():
        if other.name != name:
            other.remove([vi])
    vgroups[name].add([vi], 1.0, "REPLACE")
for name in orphan_names:
    weighted[name] = sum(1 for vi, (_d, n) in claims.items() if n == name)
    if weighted[name]:
        print("BIND coverage", name, weighted[name], "verts")

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
