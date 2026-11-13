"""creature_base.py — generate an organic creature base mesh from a rig template.

The template's bone chain becomes a skin-modifier skeleton with per-bone radii,
then subdivision and smoothing turn it into a continuous body. That gives a
believable quadruped/monster base with real volume, unlike primitive kits, and
it is driven by the same template the rig builder consumes.

Usage:
  blender -b -P tools/blender/creature_base.py -- \
    --template configs/rigs/quadruped.json --out output/base --id beast \
    [--subdiv 2] [--target-tris 16000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
_ap = argparse.ArgumentParser()
_ap.add_argument("--template", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--subdiv", type=int, default=2)
_ap.add_argument("--target-tris", type=int, default=16000)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

tpl_path = Path(A.template) if Path(A.template).is_absolute() else ROOT / A.template
TPL = json.loads(tpl_path.read_text())

bpy.ops.wm.read_factory_settings(use_empty=True)

# ---------------------------------------------------------------- skeleton mesh
me = bpy.data.meshes.new(f"{A.id}_skel")
obj = bpy.data.objects.new(f"{A.id}_skel", me)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

bm = bmesh.new()
nodes = {}
radius = {}
for spec in TPL["bones"]:
    if not spec.get("deform", True):
        continue
    h = Vector(spec["head"])
    t = Vector(spec["tail"])
    vh = bm.verts.new(h)
    vt = bm.verts.new(t)
    nodes[spec["name"] + ":h"] = vh
    nodes[spec["name"] + ":t"] = vt
    radius[vh] = spec.get("radius", 0.08)
    radius[vt] = spec.get("radius", 0.08)
    bm.edges.new((vh, vt))
# connect child bone heads to parent tails so the skin is continuous
for spec in TPL["bones"]:
    if not spec.get("parent") or not spec.get("deform", True):
        continue
    p = nodes.get(spec["parent"] + ":t")
    c = nodes.get(spec["name"] + ":h")
    if p and c and p is not c:
        try:
            bm.edges.new((p, c))
        except ValueError:
            pass
bm.to_mesh(me)
bm.free()

skin = obj.modifiers.new("skin", "SKIN")
skin.use_smooth_shade = True
for i, v in enumerate(me.vertices):
    r = radius.get(v, 0.08)
    me.skin_vertices[0].data[i].radius = (r, r)
bpy.ops.object.modifier_apply(modifier="skin")

if A.subdiv > 0:
    sub = obj.modifiers.new("sub", "SUBSURF")
    sub.levels = A.subdiv
    sub.render_levels = A.subdiv
    bpy.ops.object.modifier_apply(modifier="sub")

smooth = obj.modifiers.new("smooth", "SMOOTH")
smooth.factor = 0.5
smooth.iterations = 6
bpy.ops.object.modifier_apply(modifier="smooth")

polys = len(obj.data.polygons)
if polys * 2 > A.target_tris:
    dm = obj.modifiers.new("dec", "DECIMATE")
    dm.ratio = max(0.05, A.target_tris / (polys * 2))
    dm.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")

obj.name = f"{A.id}_base"
print("BASE", obj.name, len(obj.data.vertices), "verts", len(obj.data.polygons), "polys")

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}_base.glb"
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False)
print("EXPORTED", dest)
