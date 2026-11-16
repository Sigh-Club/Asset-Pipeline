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
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--obj", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--height", type=float, default=0.0,
                 help="target height in metres (default: the rig's declared height_m)")
_ap.add_argument("--up-axis", choices=["x", "y", "z"],
                 help="source-space up axis; required unless --rig declares source_up_axis")
_ap.add_argument("--rig", help="configs/rigs/<class>.json declaring source_up_axis and height_m")
_ap.add_argument("--target-tris", type=int, default=14000)
_ap.add_argument("--no-weld", action="store_true", help="keep the shipped topology as-is")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
# Pin the OBJ axis convention to identity. Blender's importer defaults to treating an
# OBJ as Y-up and silently converting it to Z-up, so the geometry arrived already
# rotated and the up-axis handling below then rotated it a SECOND time. That double
# conversion is the real mechanism of D-1 (not "the heuristic declined to rotate"):
# measured, the raw Carnifex OBJ is (6.96, 7.52, 13.27) with Y vertical, the importer
# turned that into Blender (6.96, 13.27, 7.52), and the old span test then saw
# y 13.27 > z*1.05 and rotated the body length into the height. With the import pinned
# the declared source axis below is the file's real axis and exactly one conversion
# is applied.
bpy.ops.wm.obj_import(filepath=str(Path(A.obj).resolve()), up_axis="Z", forward_axis="Y")
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

# up axis: declared, never inferred.
#
# DoW2 vertex data is Y-up. Measured across all eight race families: the Y span is the
# standing height (commissar 2.93, space-marine commander 3.16, farseer 2.65) and, for a
# quadrupedal creature, the Z span is the BODY LENGTH (carnifex 12.22, termagaunt 4.31,
# hormagaunt 3.45). Choosing the axis by comparing spans rotated the humanoids correctly
# and scaled every creature by its length, standing it on its tail: the Carnifex shipped
# at 1.26 x 2.40 x 1.36 because its 13.27-unit body length was taken as the 2.40 m
# height. 37 of 221 body parts took that path (36 tyranid, 1 ork).
# The axis is a property of the source format, so the asset class declares it and this
# tool refuses to guess. See D-1 in HANDOFF_DOW2_IMPORT.md.
UP_AXIS_TO_Z = {
    "x": (0.0, -math.pi / 2, 0.0),   # +X -> +Z
    "y": (math.pi / 2, 0.0, 0.0),    # +Y -> +Z
    "z": (0.0, 0.0, 0.0),            # already Z-up
}

rig_cfg = json.loads(Path(A.rig).read_text()) if A.rig else None
if A.up_axis:
    up_axis, axis_source = A.up_axis, "--up-axis"
elif rig_cfg and rig_cfg.get("source_up_axis") in UP_AXIS_TO_Z:
    up_axis, axis_source = rig_cfg["source_up_axis"], f"{A.rig}:source_up_axis"
else:
    raise SystemExit(
        "up-axis not declared. Pass --up-axis {x,y,z} or --rig <configs/rigs/<class>.json> "
        "declaring source_up_axis. This tool does not infer the axis from the bounding box: "
        "that heuristic stood 37 parts on their tails (D-1)."
    )


def _span(o):
    c = [v.co for v in o.data.vertices]
    return Vector((max(p.x for p in c) - min(p.x for p in c),
                   max(p.y for p in c) - min(p.y for p in c),
                   max(p.z for p in c) - min(p.z for p in c)))


before = _span(obj)
print(f"SPAN x={before.x:.2f} y={before.y:.2f} z={before.z:.2f} "
      f"up_axis={up_axis} ({axis_source})")
rot = UP_AXIS_TO_Z[up_axis]
if any(rot):
    obj.rotation_euler = rot
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    print(f"AXIS rotated {up_axis.upper()}-up -> Z-up")

# Invariant: the declared axis must now be the Z span. A wrong declaration fires here
# rather than shipping a uniformly mis-scaled mesh past a gate that only sees edges.
after = _span(obj)
declared_span = {"x": before.x, "y": before.y, "z": before.z}[up_axis]
if abs(after.z - declared_span) > 1e-3 * max(1.0, declared_span):
    raise SystemExit(
        f"declared up axis {up_axis!r} does not map to +Z "
        f"(source span {declared_span:.3f} -> resulting Z span {after.z:.3f})"
    )

# Height comes from the rig that will be fitted; a caller override is allowed but said
# out loud, because silently contradicting the rig is defect D-6.
height = after.z
rig_height = float(rig_cfg["height_m"]) if rig_cfg and rig_cfg.get("height_m") else 0.0
target = A.height
if target <= 0 and rig_height > 0:
    target = rig_height
    print(f"HEIGHT from {A.rig} = {target} m")
elif target > 0 and rig_height > 0 and abs(target - rig_height) > 0.02 * rig_height:
    print(f"WARN height {target} m overrides {A.rig}'s declared {rig_height} m "
          f"({(target / rig_height - 1) * 100:+.0f}%) - D-6: the rig config should "
          f"declare this class's real height")
if target > 0 and height > 1e-6:
    s = target / height
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    print(f"SCALE {s:.4f} -> height {target} m")

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

# The gate line: measured bbox after axis, scale and grounding. A mis-declared axis
# shows here as a body whose depth exceeds its height on a humanoid, or a creature
# whose height equals its length.
dims = _span(obj)
print(f"BBOX x={dims.x:.2f} y={dims.y:.2f} z={dims.z:.2f}")

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
