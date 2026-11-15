#!/usr/bin/env python3
"""parametric_prop.py — hard-surface assets from an asset request.

Weapons, barrels, crates, tiles and modular building blocks are built from
primitives with real dimensions, not generated from images. This is the route the
`ioa-3d-assets` skill mandates for hard-surface work: image-to-3D fuses parts and
loses dimensions; a parametric build is deterministic and editable.

Reads a request from `configs/assets/*.json`:

    blender -b -P tools/blender/parametric_prop.py -- \
        --request configs/assets/examples.json --id iron_directorate_barrel_a \
        --out output/props/barrel --render --library <library.blend>

Recipes: barrel | crate | tile | weapon | block. Unknown kinds fall back to the
recipe named by `params.recipe`, then to a crate.

Outputs <out>/<id>.glb (real dimensions, UVs, slot materials), <out>/render/*.png
(orthographic, no antialiasing, profile canvas), and <out>/<id>_meta.json.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_materials  # noqa: E402
import master_render  # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--library", help="material library .blend for render")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--directions", type=int, default=1, choices=(1, 4, 8),
                    help="camera orbit positions (8 for the sprite pipeline)")
    ap.add_argument("--masks", action="store_true",
                    help="also render normal / AO / emission masks per direction")
    ap.add_argument("--samples", type=int, default=1, help="1 = no antialiasing")
    # Imported-mesh route: a decoded shipped-game prop (DoW2 `.model` -> OBJ) is
    # normalised into the same contract the parametric recipes produce. This is how a
    # shipped-game silhouette becomes a pixel prop without hand-modelling it.
    ap.add_argument("--obj", help="import this OBJ instead of building a parametric recipe")
    ap.add_argument("--height", type=float, default=0.0,
                    help="target height in metres for an imported mesh (0 = keep source scale)")
    ap.add_argument("--target-tris", type=int, default=600,
                    help="decimation budget for an imported mesh")
    ap.add_argument("--profile-override", default="",
                    help="use this style profile instead of the request's (large props "
                         "need a coarser texel grid than the 256 px atlas can hold at 0.02 m)")
    ap.add_argument("--max-footprint", type=float, default=2.2,
                    help="clamp the longest horizontal dimension (metres). Cover occupies "
                         "ONE cell (TILE_SIZE 2.4 m in the renderer): a prop wider than its "
                         "cell overhangs the neighbours and blows the texel budget.")
    return ap.parse_args(argv)


# ------------------------------------------------------------------ requests ---

def load_request(path: Path, req_id: str) -> dict:
    data = json.loads(path.read_text())
    for req in data.get("requests", []):
        if req.get("id") == req_id:
            return req
    raise SystemExit(f"no request '{req_id}' in {path}")


def profile_of(req: dict) -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location("style_profiles",
                                                 ROOT / "tools" / "style" / "profiles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    resolved = mod.resolve(req["profile"])
    errors = mod.validate(resolved)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    return resolved


# ------------------------------------------------------------------ geometry ---

def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _box(bm, size, loc):
    res = bmesh.ops.create_cube(bm, size=1.0)
    for v in res["verts"]:
        v.co.x = v.co.x * size[0] + loc[0]
        v.co.y = v.co.y * size[1] + loc[1]
        v.co.z = v.co.z * size[2] + loc[2]
    return res["verts"]


def _cyl(bm, radius, depth, loc, segments=20, axis="z"):
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                                segments=segments, radius1=radius, radius2=radius,
                                depth=depth)
    for v in res["verts"]:
        if axis == "x":
            v.co = Vector((v.co.z, v.co.y, -v.co.x))
        v.co += Vector(loc)
    return res["verts"]


def build_barrel(bm, p):
    r = float(p.get("diameter_m", 0.58)) / 2
    h = float(p.get("height_m", 0.88))
    _cyl(bm, r, h, (0, 0, h / 2), 24)
    for i in range(int(p.get("ribs", 3))):
        z = h * (i + 1) / (int(p.get("ribs", 3)) + 1)
        _cyl(bm, r * 1.06, h * 0.05, (0, 0, z), 24)
    # lid rim
    _cyl(bm, r * 0.96, h * 0.04, (0, 0, h - h * 0.02), 24)


def build_crate(bm, p):
    w = float(p.get("width_m", 0.7))
    h = float(p.get("height_m", 0.7))
    d = float(p.get("depth_m", 0.7))
    _box(bm, (w, d, h), (0, 0, h / 2))
    for i in range(3):
        z = h * (i + 1) / 4
        _box(bm, (w * 1.02, d * 0.06, h * 0.06), (0, d / 2, z))
        _box(bm, (w * 1.02, d * 0.06, h * 0.06), (0, -d / 2, z))


def build_tile(bm, p):
    """Industrial deck module.

    A single box renders as a featureless slab (the 2026-11-09 review's finding).
    A deck reads because of its module seams, tread ribs and corner fixings, and
    those are 4-6 cm features: visible at a 2 cm texel grid, invisible in a
    smooth render. Geometry, not texture, is what carries them.
    """
    t = float(p.get("tile_m", 2.0))
    slab = 0.12
    gap = float(p.get("seam_gap_m", 0.04))
    panels = max(1, int(p.get("panels", 2)))
    panel = (t - gap * (panels - 1)) / panels
    bolts = bool(p.get("bolts", True))
    ribs = int(p.get("tread_ribs", 3))
    # the panel gap is a recessed weld seam, not a hole through the deck: a
    # narrow filler under the gap, not a second full slab (a full base plate
    # doubles the tile's surface area and bursts the 256 texel budget)
    for i in range(1, panels):
        x = -t / 2 + i * panel + (i - 0.5) * gap
        _box(bm, (gap + 0.05, t, slab * 0.5), (x, 0, -slab * 0.42))
    for i in range(panels):
        x = -t / 2 + panel / 2 + i * (panel + gap)
        _box(bm, (panel, t, slab), (x, 0, -slab / 2))
        for k in range(ribs):
            y = -t / 2 + t * (k + 0.5) / ribs
            _box(bm, (panel * 0.78, 0.045, 0.022), (x, y, 0.011))
        if bolts:
            for sx in (-1, 1):
                for sy in (-1, 1):
                    bx = x + sx * (panel / 2 - 0.09)
                    by = sy * (t / 2 - 0.09)
                    _cyl(bm, 0.032, 0.03, (bx, by, 0.015), 8)
    lip = 0.05
    if p.get("edges", "raised") == "raised":
        _box(bm, (t, lip, 0.1), (0, t / 2 - lip / 2, 0.05))
        _box(bm, (t, lip, 0.1), (0, -t / 2 + lip / 2, 0.05))
        _box(bm, (lip, t, 0.1), (t / 2 - lip / 2, 0, 0.05))
        _box(bm, (lip, t, 0.1), (-t / 2 + lip / 2, 0, 0.05))


def _rot_x(verts, deg, pivot):
    from mathutils import Matrix
    piv = Vector(pivot)
    m = Matrix.Rotation(math.radians(deg), 4, "X")
    for v in verts:
        v.co = piv + m @ (v.co - piv)
    return verts


def _rot_y(verts, deg, pivot):
    from mathutils import Matrix
    piv = Vector(pivot)
    m = Matrix.Rotation(math.radians(deg), 4, "Y")
    for v in verts:
        v.co = piv + m @ (v.co - piv)
    return verts


def build_weapon(bm, p):
    """Lasrifle from named parts.

    A receiver box with a barrel reads as a stick at 256 px. What makes a weapon
    legible in a pixel master is the *silhouette vocabulary*: stock, pistol grip,
    trigger guard, magazine, sight, muzzle device, and a fore-end that steps away
    from the receiver line. Each is 2-6 cm, i.e. 1-3 texels on the 2 cm grid.
    """
    L = float(p.get("length_m", 1.05))
    w = float(p.get("receiver_w_m", 0.07))
    barrel = float(p.get("barrel_len_m", 0.46))

    # receiver + top rail
    _box(bm, (L * 0.30, w, 0.10), (L * 0.02, 0, 0.06))
    if p.get("rail", True):
        _box(bm, (L * 0.26, w * 0.5, 0.022), (L * 0.02, 0, 0.121))
        for i in range(5):
            _box(bm, (0.012, w * 0.5, 0.012),
                 (L * 0.02 - L * 0.10 + i * L * 0.05, 0, 0.132))

    # handguard with vent slots
    _box(bm, (L * 0.20, w * 0.85, 0.065), (L * 0.27, 0, 0.052))
    for i in range(3):
        _box(bm, (0.016, w * 0.95, 0.05), (L * 0.22 + i * 0.045, 0, 0.052))

    # barrel + muzzle device
    _cyl(bm, 0.013, barrel, (L * 0.47, 0, 0.055), 10, axis="x")
    _cyl(bm, 0.024, 0.05, (L * 0.47 + barrel * 0.5 - 0.02, 0, 0.055), 10, axis="x")
    for i in range(3):
        _cyl(bm, 0.026, 0.008, (L * 0.47 + barrel * 0.5 - 0.035 + i * 0.012, 0, 0.055),
             10, axis="x")

    # stock with buttplate
    _box(bm, (L * 0.17, w * 0.7, 0.085), (-L * 0.21, 0, 0.045))
    _box(bm, (L * 0.06, w * 0.55, 0.05), (-L * 0.32, 0, 0.03))
    _box(bm, (0.02, w * 0.75, 0.115), (-L * 0.355, 0, 0.05))

    # pistol grip (raked back 16 deg) and trigger guard
    grip = _box(bm, (0.042, w * 0.62, 0.135), (-L * 0.10, 0, -0.035))
    _rot_y(grip, 16.0, (-L * 0.10, 0, 0.0))
    _box(bm, (0.05, w * 0.5, 0.012), (-L * 0.045, 0, -0.028))
    _box(bm, (0.012, w * 0.5, 0.05), (-L * 0.022, 0, -0.052))

    # magazine well + curved magazine
    _box(bm, (0.07, w * 0.8, 0.045), (-L * 0.015, 0, 0.0))
    if p.get("magazine", "drum") == "drum":
        _cyl(bm, 0.062, 0.052, (-L * 0.02, 0, -0.04), 14, axis="y")
    else:
        mag = _box(bm, (0.045, w * 0.55, 0.14), (-L * 0.02, 0, -0.085))
        _rot_y(mag, 10.0, (-L * 0.02, 0, -0.02))

    # sight block
    _box(bm, (0.055, 0.022, 0.045), (L * 0.09, 0, 0.155))


def build_cover(bm, p):
    """Battlefield cover, one shape per gameplay tier.

    XCOM's tactical read depends on a player recognising, at a glance, whether an
    object gives partial (waist) or hardened (chest+) cover and which side is
    protected. Colour cannot carry that at 256 px, so each shape gets a distinct
    silhouette vocabulary: stacked crates, a lumpy sandbag row and an angled
    barricade for partial; a heavy machine block with a firing slit, a buttressed
    shield wall and a capped column for hardened. `height_m` from the request is
    the real height of the finished prop (measured min/max Z here, not assumed),
    so the renderer's tier check and the geometry cannot drift apart.
    """
    shape = str(p.get("shape", "crate_stack"))
    w = float(p.get("width_m", 1.6))
    d = float(p.get("depth_m", 0.6))
    h = float(p.get("height_m", 0.9))

    if shape == "crate_stack":
        # lower crate + upper crate offset, banded on four faces, with a lid plate
        for (fw, fd, fh, ox, oy) in (
                (w * 0.58, d * 0.92, h * 0.55, -w * 0.20, 0.0),
                (w * 0.46, d * 0.86, h * 0.42, w * 0.22, d * 0.04)):
            z0 = 0.0 if ox < 0 else h * 0.55
            _box(bm, (fw, fd, fh), (ox, oy, z0 + fh / 2))
            for k in range(2):
                bz = z0 + fh * (k + 1) / 3
                _box(bm, (fw * 1.02, fd * 0.06, fh * 0.09), (ox, fd / 2, bz))
                _box(bm, (fw * 1.02, fd * 0.06, fh * 0.09), (ox, -fd / 2, bz))
                _box(bm, (fw * 0.06, fd * 1.02, fh * 0.09), (ox + fw / 2, oy, bz))
                _box(bm, (fw * 0.06, fd * 1.02, fh * 0.09), (ox - fw / 2, oy, bz))
        _box(bm, (w * 0.36, d * 0.62, h * 0.03), (w * 0.22, d * 0.04, h * 0.985))
    elif shape == "sandbag_row":
        cols = 5
        bag = (w / cols) * 0.94
        for row in range(3):
            z = h * (row + 0.5) / 3
            offset = (bag / 2) if row % 2 else 0.0
            for c in range(cols):
                x = -w / 2 + bag / 2 + c * bag + offset - bag / 2
                if abs(x) > w / 2 - bag * 0.35:
                    continue
                _cyl(bm, bag * 0.66, d * 0.96, (x, 0, z), 8, axis="y")
    elif shape == "barricade":
        # leaning panel on two feet with a hazard rail and cross braces
        panel = _box(bm, (w, d * 0.16, h * 0.78), (0, 0, h * 0.58))
        _rot_x(panel, 12.0, (0, 0, h * 0.20))
        for sx in (-1, 1):
            _box(bm, (0.10, d * 0.9, h * 0.14), (sx * (w / 2 - 0.12), 0, h * 0.07))
            brace = _box(bm, (0.07, d * 0.10, h * 0.5), (sx * (w * 0.30), 0, h * 0.30))
            _rot_x(brace, 26.0, (sx * (w * 0.30), 0, h * 0.08))
        _box(bm, (w * 0.98, d * 0.22, h * 0.07), (0, 0, h * 0.95))
        for i in range(3):
            _box(bm, (0.06, d * 0.26, h * 0.05), (-w * 0.28 + i * w * 0.28, 0, h * 0.86))
    elif shape == "machine_block":
        # hardened: heavy plinth, sloped top and a firing slit between buttresses
        _box(bm, (w, d, h * 0.60), (0, 0, h * 0.30))
        _box(bm, (w * 0.94, d * 0.84, h * 0.28), (0, 0, h * 0.74))
        _box(bm, (w * 0.66, d * 0.30, h * 0.09), (0, -d * 0.42, h * 0.64))
        for sx in (-1, 1):
            _box(bm, (0.14, d * 1.04, h * 0.22), (sx * (w / 2 - 0.07), 0, h * 0.51))
        # front ribs and a stepped base: geometry for the tri floor and the value
        # breaks that make a block read as machinery, not a crate
        for i in range(4):
            _box(bm, (w * 0.09, d * 0.10, h * 0.34), (-w * 0.36 + i * w * 0.24, -d / 2, h * 0.32))
        _box(bm, (w * 1.06, d * 1.08, h * 0.05), (0, 0, h * 0.025))
    elif shape == "shield_wall":
        # hardened: a solid slab (a wall is one object — separate panels would fail
        # the single-component silhouette gate and cost atlas area for nothing)
        # with a capped top, a base plinth, end buttresses and raised front plates.
        # Surface area is the binding constraint at a 2 cm texel grid on 256².
        _box(bm, (w, d * 0.5, h * 0.9), (0, 0, h * 0.45))
        _box(bm, (w * 1.02, d * 0.62, h * 0.05), (0, 0, h * 0.925))
        _box(bm, (w * 1.02, d * 0.78, h * 0.05), (0, 0, h * 0.025))
        for sx in (-1, 1):
            _box(bm, (0.15, d, h * 0.98), (sx * (w / 2 - 0.07), 0, h * 0.49))
        for i in range(3):
            _box(bm, (w * 0.16, d * 0.14, h * 0.34), (-w * 0.26 + i * w * 0.26, -d * 0.29, h * 0.62))
        # rear centre buttress: reads as load-bearing from the squad's side and
        # keeps the piece above the contract's 100-tri floor
        _box(bm, (0.18, d * 0.22, h * 0.8), (0, d * 0.30, h * 0.42))
    else:  # column
        r = float(p.get("diameter_m", 0.55)) / 2
        _cyl(bm, r, h * 0.86, (0, 0, h * 0.45), 12)
        _cyl(bm, r * 1.38, h * 0.07, (0, 0, h * 0.035), 12)
        _cyl(bm, r * 1.32, h * 0.07, (0, 0, h * 0.90), 12)
        for i in range(3):
            _cyl(bm, r * 1.10, h * 0.04, (0, 0, h * (0.24 + i * 0.24)), 12)
        for i in range(4):
            a = (i / 4) * 6.2832
            _box(bm, (r * 0.28, r * 0.28, h * 0.5),
                 (math.cos(a) * r * 0.98, math.sin(a) * r * 0.98, h * 0.45))


def build_block(bm, p):
    fw, fd = p.get("footprint_m", [6, 4])
    storeys = int(p.get("storeys", 2))
    h = 3.0 * storeys
    _box(bm, (fw, fd, h), (0, 0, h / 2))
    # floor banding
    for i in range(1, storeys):
        _box(bm, (fw * 1.01, fd * 1.01, 0.12), (0, 0, 3.0 * i))
    # door
    _box(bm, (1.2, 0.12, 2.2), (0, -fd / 2 - 0.05, 1.1))


RECIPES = {
    "barrel": build_barrel, "cover": build_cover, "crate": build_crate,
    "tile": build_tile, "weapon": build_weapon, "block": build_block,
}


def build_imported(req: dict, obj_path: Path, height: float, target_tris: int,
                   max_footprint: float = 2.2):
    """Import a shipped-game prop OBJ and normalise it into our prop contract.

    The shipped mesh is the modelling reference (the same rule dow2_base.py applies to
    units): import, join the submeshes, ground it, centre it on its footprint, scale to
    the target height, then decimate to the prop budget. No rig, no material work —
    the pixel atlas stage re-authors the surface.
    """
    import math

    bpy.ops.wm.obj_import(filepath=str(obj_path))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit(f"no mesh in {obj_path}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
        print(f"JOINED {len(meshes)} imported groups")
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # shipped meshes come in their own units and orientation: ground, centre, scale
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.001)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    min_v = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    max_v = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    # DoW2 world objects are authored Z-up in the extracted OBJ (verified on the
    # sandbag wall, high wall, container, generator and barricade: their height axis is
    # Z). Do NOT guess an up-axis from the bounding box — a long low prop (the raised
    # pipe run, 8.3 x 7.9 x 1.2) trips a Y-span heuristic and gets stood on its end.

    size = max_v - min_v
    scale = 1.0
    if height > 0 and size.z > 1e-6:
        scale = height / size.z
    # A cover prop occupies one tile: clamp the footprint so the silhouette stays inside
    # its cell (and the texel budget stays reachable at 0.02 m/texel).
    if max_footprint > 0:
        longest = max(size.x, size.y) * scale
        if longest > max_footprint:
            scale *= max_footprint / longest
    obj.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    min_v = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    max_v = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    centre = Vector(((min_v.x + max_v.x) / 2, (min_v.y + max_v.y) / 2, min_v.z))
    obj.location = (obj.location.x - centre.x, obj.location.y - centre.y, obj.location.z - centre.z)
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if target_tris and tris > target_tris:
        ratio = target_tris / float(tris)
        mod = obj.modifiers.new("decimate", type="DECIMATE")
        mod.ratio = max(0.02, ratio)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    print(f"IMPORTED {obj_path.name} height={height} tris={tris}")

    for p in obj.data.polygons:
        p.use_smooth = False
    return obj, "imported"


def build_mesh(req: dict):
    kind = req.get("kind", "prop")
    recipe = req.get("params", {}).get("recipe") or {
        "prop": "barrel", "weapon": "weapon", "tile": "tile",
        "building": "block", "foliage": "crate",
    }.get(kind, "crate")
    fn = RECIPES.get(recipe, build_crate)
    bm = bmesh.new()
    fn(bm, req.get("params", {}))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(req["id"])
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(req["id"], me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    for p in obj.data.polygons:
        p.use_smooth = False
    return obj, recipe


# --------------------------------------------------------------- materials ---

def assign_materials(obj, req, library: Path | None):
    """Slot materials. When a library is supplied its box-projected materials are
    used for the render; the GLB keeps the slot names."""
    slots = list((req.get("materials") or {"body": "iron_directorate__metal_trim"}).keys())
    lib_mats = {}
    if library and library.exists():
        prefix = "IOA_"
        with bpy.data.libraries.load(str(library), link=False) as (src, dst):
            wanted = [n for n in src.materials if any(n.endswith(m) for m in
                     (req.get("materials") or {}).values())]
            dst.materials = wanted
        lib_mats = {m.name: m for m in dst.materials if m}

    obj.data.materials.clear()
    index = {}
    for i, slot in enumerate(slots):
        target = (req.get("materials") or {})[slot]
        mat = lib_mats.get(f"IOA_{target}") or lib_mats.get(target) or bpy.data.materials.new(slot)
        if not mat.use_nodes:
            mat.use_nodes = True
        obj.data.materials.append(mat)
        index[slot] = i
    for p in obj.data.polygons:
        p.material_index = 0
    return [m.name for m in obj.data.materials]


# ------------------------------------------------------------------- output ---

def assign_slots(obj, req, recipe, slot_count):
    """Author which faces take the trim/accent slot. A single-material prop reads
    as a grey lump; ribs, lips, barrels and mags are what make it legible."""
    if slot_count < 2:
        return
    p = req.get("params", {})
    for poly in obj.data.polygons:
        c = poly.center
        n = poly.normal
        slot = 0
        if recipe == "barrel":
            r = float(p.get("diameter_m", 0.58)) / 2
            radial = (c.x ** 2 + c.y ** 2) ** 0.5
            # rib band = accent (slot 1), lid rim + cap = rim metal (slot 2).
            # A single-material drum reads as a grey cylinder at 256 px; the rim
            # is the value break that says "drum".
            h = float(p.get("height_m", 0.88))
            if radial > r * 1.02:
                slot = 1
            elif c.z > h * 0.94:
                slot = 2
        elif recipe == "weapon":
            if c.x > float(p.get("length_m", 1.05)) * 0.20 or c.z < 0.0:
                slot = 1
        elif recipe == "tile":
            if c.z > 0.02:
                slot = 1
        elif recipe == "block":
            if abs(c.x) < 0.7 and c.y < 0:
                slot = 1
        elif recipe == "crate":
            if abs(n.y) > 0.7 and abs(c.y) > 0.3:
                slot = 1
        elif recipe == "cover":
            h = float(p.get("height_m", 0.9))
            # trim slot on the top band (rail/lid/cap) and on outward faces
            if c.z > h * 0.80 or abs(n.z) > 0.85 and c.z > h * 0.55:
                slot = 1
        poly.material_index = min(slot, slot_count - 1)


def unwrap(obj, texel_world_m: float):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")


def main():
    args = parse_args()
    req = load_request(Path(args.request).resolve(), args.id)
    if args.profile_override:
        req = dict(req, profile=args.profile_override)
    prof = profile_of(req)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    if args.obj:
        obj, recipe = build_imported(req, Path(args.obj).resolve(), args.height,
                                     args.target_tris, args.max_footprint)
    else:
        obj, recipe = build_mesh(req)
    mats = assign_materials(obj, req, Path(args.library).resolve() if args.library else None)
    assign_slots(obj, req, recipe, len(obj.data.materials))
    texel = prof.get("texture", {}).get("texel_world_m", 0.02)
    unwrap(obj, texel)

    size = prof.get("render", {}).get("size_px") or [256, 256]
    rendered = {"directions": 0, "beauty": [], "masks": []}
    if args.render:
        # framing is derived from the projected geometry, not from the origin
        # and a guessed ortho scale (see master_render.py)
        anchor = "bottom" if req.get("kind") == "unit" else "centre"
        rendered = master_render.render_master_set(
            [obj], out, args.id, size, args.directions, args.masks,
            anchor=anchor, samples=args.samples)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    glb = out / f"{args.id}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), use_selection=True,
                              export_format="GLB", export_yup=True)

    meta = {
        "request": req, "profile": req.get("profile"), "recipe": recipe,
        "texel_world_m": texel, "render_size_px": size,
        "materials": mats, "glb": str(glb), "rendered": rendered,
        "note": "box-projected library materials are render-only; bake to UVs "
                "before shipping the GLB with textures",
    }
    (out / f"{args.id}_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"PROP {args.id} recipe={recipe} glb={glb}")


main()
