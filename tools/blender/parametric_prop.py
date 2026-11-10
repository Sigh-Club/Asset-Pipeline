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
    "barrel": build_barrel, "crate": build_crate, "tile": build_tile,
    "weapon": build_weapon, "block": build_block,
}


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
    prof = profile_of(req)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
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
