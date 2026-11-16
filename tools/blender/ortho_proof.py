"""ortho_proof.py — orthographic contact sheet of an imported mesh, for the visual gate.

Numeric gates cannot see a jumble: the Carnifex shipped at 1.26 x 2.40 x 1.36 because
every automated check it passed was scale-invariant (uniformly wrong, not exploded).
This renders the silhouette from three orthogonal directions so the shape can be read
against the source it came from — talons up, carapace hunched, tail behind.

Usage:
  blender -b -P tools/blender/ortho_proof.py -- --glb output/base/carnifex_base.glb \
      --out output/proof --id carnifex
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--glb", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--res", type=int, default=640)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"no mesh in {A.glb}")

co = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
ctr = (lo + hi) / 2
span = hi - lo
extent = max(span.x, span.y, span.z)
print(f"PROOF bbox x={span.x:.2f} y={span.y:.2f} z={span.z:.2f} "
      f"(y/z ratio {span.y / max(1e-6, span.z):.2f})")

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = A.res
scene.render.resolution_y = A.res
scene.render.film_transparent = False
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (0.62, 0.62, 0.66)

cam_data = bpy.data.cameras.new("ortho")
cam_data.type = "ORTHO"
cam_data.ortho_scale = extent * 1.15
cam = bpy.data.objects.new("ortho", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
# (name, direction) — side view reads the body axis, front reads the shoulder span,
# top reads the footprint. Side is the one that exposes a creature on its tail.
views = {
    "side": Vector((1, 0, 0)),
    "front": Vector((0, -1, 0)),
    "top": Vector((0, 0, 1)),
}
for name, direction in views.items():
    dist = extent * 3
    cam.location = ctr + direction * dist
    # aim the camera at the mesh centre
    look = (ctr - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(out / f"{A.id}_{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"PROOF {name} -> {scene.render.filepath}")
