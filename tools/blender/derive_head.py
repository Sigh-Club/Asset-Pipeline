"""derive_head.py — replace a unit's head with an IoA helm.

First derivation of the kit method: strip the source's head (the commissar cap),
then add our vocabulary (visor slit, crest, breather, neck ring) so the silhouette
belongs to the faction rather than the reference.

The operation is deliberately narrow: a head swap is the smallest change that
alters a silhouette, so it is the safest way to prove the derive-and-reshape loop
before touching torsos and limbs.

Usage:
  blender -b -P tools/blender/derive_head.py -- \
      --base output/base/ig_human_base.glb --out output/base --id ig_human_v2 \
      --faction iron_directorate --cut-z 1.60
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
_ap = argparse.ArgumentParser()
_ap.add_argument("--base", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--faction", default="iron_directorate")
_ap.add_argument("--cut-z", type=float, default=0.0, help="0 = auto from height")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

spec = json.loads((ROOT / f"configs/factions/{A.faction}.json").read_text())

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.base).resolve()))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
body = max(meshes, key=lambda o: len(o.data.vertices))
for o in meshes:
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

co = [v.co for v in body.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
height = hi.z - lo.z
width = max(hi.x - lo.x, hi.y - lo.y)
cut_z = A.cut_z if A.cut_z > 0 else lo.z + height * 0.855
print(f"BODY height={height:.2f} width={width:.2f} cut_z={cut_z:.2f}")

# ---- strip: remove the source head/cap above the neck line -------------------
bm = bmesh.new()
bm.from_mesh(body.data)
bm.faces.ensure_lookup_table()
dead = []
for f in bm.faces:
    c = f.calc_center_median()
    if c.z > cut_z and abs(c.x) < width * 0.30:
        dead.append(f)
if dead:
    bmesh.ops.delete(bm, geom=dead, context="FACES")
bm.to_mesh(body.data)
bm.free()
print(f"STRIP removed {len(dead)} faces above z={cut_z:.2f}")

# ---- add: IoA helm -----------------------------------------------------------
head_c = Vector((0.0, lo.y + (hi.y - lo.y) * 0.45, cut_z))
head_r = height * 0.065
parts = []


def add_mesh(name, verts, faces, material):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(material)
    parts.append(ob)
    return ob


def add_uv_sphere(name, centre, radius, scale, segments=24, rings=16, cut_bottom=None):
    verts, faces = [], []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        for s in range(segments):
            theta = 2 * math.pi * s / segments
            x = radius * scale[0] * math.sin(phi) * math.cos(theta)
            y = radius * scale[1] * math.sin(phi) * math.sin(theta)
            z = radius * scale[2] * math.cos(phi)
            verts.append((centre.x + x, centre.y + y, centre.z + z))
    for r in range(rings):
        for s in range(segments):
            a = r * segments + s
            b = r * segments + (s + 1) % segments
            c = (r + 1) * segments + (s + 1) % segments
            d = (r + 1) * segments + s
            faces.append((a, b, c, d))
    return add_mesh(name, verts, faces, MAT)


def add_box(name, centre, size, bevel=0.01):
    sx, sy, sz = (s / 2 for s in size)
    verts = [(centre.x + x * sx, centre.y + y * sy, centre.z + z * sz)
             for x, y, z in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                             (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))]
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2),
             (2, 6, 7, 3), (3, 7, 4, 0)]
    ob = add_mesh(name, verts, faces, MAT)
    if bevel > 0:
        mod = ob.modifiers.new("bev", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    return ob


# reuse the body's contract slot: a second material datablock with the same name
# becomes armour_primary.001 after the join and the bake cannot map it
MAT = bpy.data.materials.get("armour_primary")
if MAT is None:
    MAT = bpy.data.materials.new("armour_primary")
    MAT.use_nodes = True

# skull dome
add_uv_sphere("helm_dome", head_c + Vector((0, 0, head_r * 0.95)), head_r,
              (1.0, 1.15, 1.05))
# neck ring covers the cut seam
add_uv_sphere("helm_ring", Vector((head_c.x, head_c.y, cut_z + head_r * 0.10)),
              head_r * 1.05, (1.15, 1.15, 0.35), segments=24, rings=8)
# visor band, slightly proud of the face
add_box("helm_visor", head_c + Vector((0, -head_r * 1.02, head_r * 0.95)),
        (head_r * 1.55, head_r * 0.35, head_r * 0.34), bevel=head_r * 0.05)
# crest: the Directorate's pennant-line, front to back
add_box("helm_crest", head_c + Vector((0, 0, head_r * 1.95)),
        (head_r * 0.16, head_r * 2.0, head_r * 0.42), bevel=head_r * 0.04)
# breather
add_box("helm_breather", head_c + Vector((0, -head_r * 1.15, head_r * 0.35)),
        (head_r * 0.5, head_r * 0.4, head_r * 0.5), bevel=head_r * 0.06)

# apply bevels, join everything into the body
for ob in parts:
    bpy.context.view_layer.objects.active = ob
    for mod in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=mod.name)
bpy.ops.object.select_all(action="DESELECT")
for ob in parts:
    ob.select_set(True)
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")

tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
print("DERIVED", body.name, len(body.data.vertices), "verts", tris, "tris")

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_base.glb"
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False)
print("EXPORTED", dest)
