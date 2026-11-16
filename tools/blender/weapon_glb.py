"""weapon_glb.py — turn a decoded DoW2 weapon part into a GLB a unit can hold.

The unit masters carry `socket_weapon_L/R` bones but no weapon geometry: DoW2 ships the
weapons as separate `troops_wargear` parts, so an imported body arrives empty-handed and
reads as a soldier gesturing at nothing. XCOM's soldiers always carry a rifle, and the cover
poses are built around a shouldered weapon, so the weapon is part of the silhouette rather
than decoration.

This keeps the palette contract (one flat material in the faction's colour) instead of running
the full texel/bake/palette-lock prop route, because a weapon is 100-600 tris of solid metal
and an atlas would be wasted on it. The M2 PBR rebuild can give it a real material later.

Usage:
  blender -b -P tools/blender/weapon_glb.py -- --obj /tmp/w.obj --out output/weapons \
      --id lasgun --length 0.95 --colour 0x8a8f7a
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
_ap.add_argument("--length", type=float, default=0.95, help="longest-axis size in metres")
_ap.add_argument("--colour", default="0x8a8f7a", help="flat palette colour, 0xRRGGBB")
_ap.add_argument("--up-axis", choices=["x", "y", "z"], default="y",
                 help="source up axis of the decoded OBJ (DoW2 is Y-up)")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
# pin the import so no implicit axis conversion happens (same rule as dow2_base.py)
bpy.ops.wm.obj_import(filepath=str(Path(A.obj).resolve()), up_axis="Z", forward_axis="Y")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")
obj = meshes[0]
bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = obj
if len(meshes) > 1:
    bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

co = [v.co for v in obj.data.vertices]
span = Vector((max(c.x for c in co) - min(c.x for c in co),
               max(c.y for c in co) - min(c.y for c in co),
               max(c.z for c in co) - min(c.z for c in co)))
print(f"WEAPON span x={span.x:.2f} y={span.y:.2f} z={span.z:.2f}")

# Normalise the barrel onto +Z before scaling. DoW2 weapon parts are authored on whatever
# axis the modeller used (measured: lasgun along Z, bolter along X), so without this every
# weapon needs its own attachment rotation and the muzzle points somewhere different.
import math as _math
if span.x >= span.y and span.x >= span.z:
    obj.rotation_euler = (0.0, -_math.pi / 2, 0.0)   # +X -> +Z
elif span.y >= span.z:
    obj.rotation_euler = (_math.pi / 2, 0.0, 0.0)    # +Y -> +Z
bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
co = [v.co for v in obj.data.vertices]
span = Vector((max(c.x for c in co) - min(c.x for c in co),
               max(c.y for c in co) - min(c.y for c in co),
               max(c.z for c in co) - min(c.z for c in co)))
print(f"WEAPON normalised x={span.x:.2f} y={span.y:.2f} z={span.z:.2f}")

# scale so the barrel axis is the requested length
longest = max(span.x, span.y, span.z)
if longest > 1e-6:
    s = A.length / longest
    obj.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

# Origin at the TRIGGER GRIP, not at the centre. A weapon centred on its own bounding box,
# placed at a hand, puts half of itself inside the soldier — which is exactly what shipped.
# The grip of every weapon in this library is at the rear-bottom (behind the trigger, under
# the barrel), so the rear-bottom corner becomes the origin: the right hand then holds the
# weapon where a hand actually goes, and the barrel extends forward (+Z) from it.
co = [v.co for v in obj.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
grip = Vector(((lo.x + hi.x) / 2, lo.y, lo.z))
obj.location = -grip
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
co = [v.co for v in obj.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
print(f"WEAPON grip-at-origin: extents z={lo.z:.2f}..{hi.z:.2f} y={lo.y:.2f}..{hi.y:.2f}")

tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)

# A weapon is one flat colour, but it is still held to the palette contract every shipped
# asset meets (texel-grid UVs on the 256px lattice + a 256 atlas), so it goes through the
# pipeline's own unwrapper rather than a smart projection or a guard exemption.
ATLAS = 256
sys.path.insert(0, str(Path(__file__).resolve().parent))
import palette_uv  # noqa: E402

report = palette_uv.unwrap_and_grid(obj, 0.02, ATLAS)
print(f"WEAPON uv util={report.get('utilisation', report.get('util', '?'))}")

for slot in list(obj.data.materials):
    obj.data.materials.pop()
hexv = A.colour.replace("0x", "").replace("#", "")
r, g, b = (int(hexv[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
img = bpy.data.images.new("palette_atlas", width=ATLAS, height=ATLAS, alpha=False)
img.pixels = [r, g, b, 1.0] * (ATLAS * ATLAS)
img.pack()

mat = bpy.data.materials.new("palette_atlas")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = img
tex.interpolation = "Closest"
tex.extension = "CLIP"  # glTF CLAMP_TO_EDGE: a palette atlas must never repeat
if bsdf:
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.72
    bsdf.inputs["Metallic"].default_value = 0.0
obj.data.materials.append(mat)

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False)
print(f"WEAPON exported {dest} tris={tris}")
