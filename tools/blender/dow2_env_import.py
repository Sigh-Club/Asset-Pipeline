"""dow2_env_import.py — import one shipped DoW2 environment prop and export it as a static GLB.

The unit pipeline poses clips on an armature; a map prop is a static model. The assembly is still the
community add-on's (it builds the object, resolves the materials from the model's own `MTRL` chunks and
reads the shipped textures), and the same rules apply: prune the damage states and extra LoDs the
add-on imports, and export the materials opaque so a prop does not render see-through.

Run inside Blender:
  blender -b -P tools/blender/dow2_env_import.py -- --model <prop.model> --out <dest.glb> --name <id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]

_ap = argparse.ArgumentParser()
_ap.add_argument("--model", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--name", required=True)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

if "dow2_tools" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="dow2_tools")

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

bpy.ops.import_scene.dow2_model(filepath=A.model, merge=False, reset_scene=False)

# the add-on imports every damage state and every LoD; the game draws one of each (see
# docs/DOW2_COMMUNITY_TOOLCHAIN.md — the same rule the units use)
groups, lods = {}, {}
keep_lod = 0
for ob in list(bpy.data.objects):
    if ob.type != "MESH":
        continue
    group = str(ob.get("dow2_group", "healthy"))
    level = int(ob.get("dow2_lod", 0))
    groups[group] = groups.get(group, 0) + 1
    lods[level] = lods.get(level, 0) + 1
keep_lod = min((int(o.get("dow2_lod", 0)) for o in bpy.data.objects
                if o.type == "MESH" and str(o.get("dow2_group", "healthy")) == "healthy"), default=0)
for ob in list(bpy.data.objects):
    if ob.type != "MESH":
        continue
    if str(ob.get("dow2_group", "healthy")) != "healthy" or int(ob.get("dow2_lod", 0)) != keep_lod:
        bpy.data.objects.remove(ob, do_unlink=True)
print(f"STATES {groups} LODS {lods} -> kept healthy/lod{keep_lod}")

# materials opaque unless the source declares a cutout (identical rule to the unit build)
alpha = {"opaque": 0, "cutout": 0}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    socket = bsdf.inputs["Alpha"]
    if bool(mat.get("dow2_alphaTest", False)) and socket.is_linked:
        clip = nodes.new("ShaderNodeMath")
        clip.operation = "ROUND"
        links.new(socket.links[0].from_socket, clip.inputs[0])
        links.new(clip.outputs[0], socket)
        alpha["cutout"] += 1
    else:
        for link in list(socket.links):
            links.remove(link)
        socket.default_value = 1.0
        alpha["opaque"] += 1
    mat.use_backface_culling = True
print(f"MATERIALS alpha: {alpha['opaque']} opaque, {alpha['cutout']} cutout")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"{A.name}: the model imported no geometry")
lo = Vector((1e9, 1e9, 1e9))
hi = Vector((-1e9, -1e9, -1e9))
tris = 0
for ob in meshes:
    ob.data.calc_loop_triangles()
    tris += len(ob.data.loop_triangles)
    for corner in ob.bound_box:
        world = ob.matrix_world @ Vector(corner)
        for i in range(3):
            lo[i] = min(lo[i], world[i])
            hi[i] = max(hi[i], world[i])
size = hi - lo
print(f"SIZE {size.x:.2f},{size.y:.2f},{size.z:.2f}")
print(f"TRIS {tris}")
print(f"GROUND {lo.z:.2f}..{hi.z:.2f}")

# sit the prop on the ground plane: the map page places props by their base, so the origin is moved to
# the model's lowest point on Z (Blender is Z-up; the glTF export converts)
for ob in meshes:
    ob.location.z -= lo.z
bpy.context.view_layer.update()

dest = Path(A.out)
dest.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False, export_yup=True)
print(f"EXPORTED {dest}")
