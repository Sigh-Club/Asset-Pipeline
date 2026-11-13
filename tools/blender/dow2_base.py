"""dow2_base.py — turn a decoded DoW2 model into a clean base mesh for our rigs.

The shipped-game mesh is the modelling reference: we import it, weld it, fix the
up-axis, scale it to the unit height and decimate to our budget, then hand it to
`rig_template.py`, which fits our own skeleton and binds it. The result is our
unit built on the shipped silhouette, with our rig and our palette.

Usage:
  python3 tools/dow2/chunky_mesh.py <model> -o /tmp/base.obj
  blender -b -P tools/blender/dow2_base.py -- --obj /tmp/base.obj \
      --out output/base --id carnifex [--height 2.4] [--target-tris 14000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--obj", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--height", type=float, default=0.0, help="target height in metres")
_ap.add_argument("--target-tris", type=int, default=14000)
_ap.add_argument("--no-weld", action="store_true", help="keep the shipped topology as-is")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=str(Path(A.obj).resolve()))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")
# the OBJ writer emits one group per submesh, and the importer creates one
# object per group; joining keeps every part (deleting the extras silently lost
# up to 44% of the mesh, measured on the eldar guardian)
obj = meshes[0]
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = obj
if len(meshes) > 1:
    bpy.ops.object.join()
    print("JOINED", len(meshes), "imported groups")
bpy.context.view_layer.objects.active = obj
# the OBJ importer can leave an object-level rotation; bake every transform so
# the mesh and any later armature share one space (measured: an un-applied
# import rotation made the exported skeleton land outside the mesh)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# weld and clean
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
if not A.no_weld:
    bpy.ops.mesh.remove_doubles(threshold=0.001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")

# up-axis: shipped parts are not guaranteed Z-up; the longest axis is the body
# axis for a creature, the vertical is whichever of Y/Z spans the standing body
co = [v.co for v in obj.data.vertices]
span = Vector((max(c.x for c in co) - min(c.x for c in co),
               max(c.y for c in co) - min(c.y for c in co),
               max(c.z for c in co) - min(c.z for c in co)))
print(f"SPAN x={span.x:.2f} y={span.y:.2f} z={span.z:.2f}")
if span.y > span.z * 1.05:
    # Y-up asset: rotate so +Z is up
    obj.rotation_euler = (1.5707963, 0, 0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    print("AXIS rotated Y-up -> Z-up")

co = [v.co for v in obj.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
height = hi.z - lo.z
if A.height > 0 and height > 1e-6:
    s = A.height / height
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    print(f"SCALE {s:.4f} -> height {A.height} m")

# ground the feet at z=0 and centre on x/y
co = [v.co for v in obj.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
obj.location = (-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
if A.target_tris and tris > A.target_tris:
    dm = obj.modifiers.new("dec", "DECIMATE")
    dm.ratio = A.target_tris / tris
    dm.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
print("BASE", obj.name, len(obj.data.vertices), "verts", tris, "tris")

# one contract material slot so the pixel pipeline can map and bake it; the
# shipped DDS textures need the DATADATA UV attribute decoded first
if not obj.data.materials:
    mat = bpy.data.materials.new("armour_primary")
    mat.use_nodes = True
    obj.data.materials.append(mat)

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_base.glb"
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False)
print("EXPORTED", dest)
