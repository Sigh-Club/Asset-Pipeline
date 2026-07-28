#!/usr/bin/env python3
"""
validate_uv.py — Pre-render UV validation gate (Phase 3.5.5).

Runs headlessly AFTER the Island-Footprint Manifest is written and BEFORE the
meshes are joined / AO baked / rendered. Fails fast to protect Cycles + render
compute. Operates on the live per-part objects (pre-join) + build/island_manifest.json.

Hard gates (FAIL -> abort pipeline):
  - UV bounds sanity       : all UVs in [0,1], no NaN/Inf.
  - Unintended UV overlap  : non-mirror island_uv rects collide (silent texture bleed).
  - Tile-boundary margin   : island within its tile +/- safety margin (LANCZOS bleed).
  - Atlas tile occupancy    : every expected TILE_LAYOUT tile has >=1 non-mirror part.
  - Cylinder anisotropy     : per-face UV/3D area scale ratio > 1.5 (FILL/stretch regression).
  - Cylinder seam integrity : back-seam verts pinned to tile left AND right UV edges.

Soft gates (WARN):
  - Island coverage        : CONTAIN < 30%, ALIGN_BOTTOM < 15% (layout drift).
  - Texel-density outlier   : a part > 5x the median density (a greeble filling a tile).

Note on texel density: cross-part density naturally differs (torso surface >> shin
surface) under fixed-size tiles, matching DoW1. So density is only checked for gross
outliers, not cross-part parity. See docs/DEVELOPMENT.md §16.4 Phase 3.5.5.

Usage (standalone, on a pre-join blend):
    blender --background --python validate_uv.py -- --blend path/to/unit.blend
Called in-process by parametric_unit_generator.py before the join step:
    from validate_uv import validate_uv
    validate_uv(all_parts, manifest, expected_tiles)
"""

import json
import math
import os

try:
    import bpy
    import bmesh
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "build", "island_manifest.json")
ATLAS_SIZE = 1024
TILE_MARGIN_PX = 8.0          # safety band inside each tile (LANCZOS bleed guard)
ANISOTROPY_MAX = 1.5
COVERAGE_CONTAIN_MIN = 0.30
COVERAGE_ALIGN_MIN = 0.15
TEXEL_OUTLIER_FACTOR = 5.0

# Cylindrical limb tile keys (anisotropy + seam checks apply only to these).
_CYLINDER_TILES = {"upper_arm", "forearm", "thigh", "shin"}


def _uv_bounds(obj):
    """Return (min_u,min_v,max_u,max_v, sane) over the object's active UV layer."""
    mesh = obj.data
    if not mesh.uv_layers or not mesh.polygons:
        return None
    uv_layer = mesh.uv_layers.active
    us, vs = [], []
    sane = True
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            uv = uv_layer.data[li].uv
            if math.isnan(uv.x) or math.isnan(uv.y) or math.isinf(uv.x) or math.isinf(uv.y):
                sane = False
            if not (0.0 <= uv.x <= 1.0 and 0.0 <= uv.y <= 1.0):
                sane = False
            us.append(uv.x)
            vs.append(uv.y)
    if not us:
        return None
    return (min(us), min(vs), max(us), max(vs), sane)


def _face_areas(obj):
    """Return list of (uv_area, area3d, is_quad) per face for anisotropy/coverage math."""
    mesh = obj.data
    if not mesh.uv_layers:
        return []
    uv_layer = mesh.uv_layers.active
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_l = bm.loops.layers.uv.verify()
    out = []
    for face in bm.faces:
        a3d = face.calc_area()
        uv_verts = [l[uv_l].uv for l in face.loops]
        a_uv = 0.0
        if len(uv_verts) >= 3:
            a_uv = 0.5 * abs(sum(
                uv_verts[i].x * (uv_verts[(i + 1) % len(uv_verts)].y - uv_verts[i - 1].y)
                for i in range(len(uv_verts))
            ))
        out.append((a_uv, a3d, len(face.loops) == 4))
    bm.free()
    return out


def _rects_overlap(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def validate_uv(all_parts, manifest, expected_tiles):
    """Run the validation matrix. Returns True if all hard gates pass."""
    if not _HAS_BPY:
        print("[validate_uv] bpy unavailable — cannot run mesh-level checks")
        return False

    by_name = {o.name: o for o in all_parts if o.type == 'MESH'}
    overall_pass = True
    warnings = []
    densities = {}
    active_islands = {}        # name -> island_uv rect (non-mirror only, for overlap)
    occupied_tiles = set()

    for part_name, meta in manifest.items():
        if meta.get("mirror_of"):
            continue                       # mirrors share the source's footprint
        obj = by_name.get(part_name)
        if obj is None:
            # Manual-UV parts (aquila) may already be joined in some flows; skip gracefully.
            continue
        tile_id = meta["tile_id"]
        tile_grid = meta["tile_grid"]
        island_uv = meta["island_uv"]
        occupied_tiles.add(tile_id)
        active_islands[part_name] = island_uv

        # --- UV bounds sanity ---
        b = _uv_bounds(obj)
        if b is None:
            print(f"[FAIL] {part_name}: no UV data")
            overall_pass = False
            continue
        min_u, min_v, max_u, max_v, sane = b
        if not sane:
            print(f"[FAIL] {part_name}: UV coords out of [0,1] or NaN/Inf (failed unwrap)")
            overall_pass = False

        # --- Tile-boundary margin: island must stay within its allowed tile region
        # (tile_grid is already inset 0.02 from the raw tile edge, so an island filling
        # tile_grid is safe from LANCZOS bleed into adjacent tiles). Box-projected parts
        # fill tile_grid exactly; cylinder islands are smaller and centred.
        tu0, tv0, tu1, tv1 = tile_grid
        iu0, iv0, iu1, iv1 = island_uv
        eps = 1e-4
        if iu0 < tu0 - eps or iv0 < tv0 - eps or iu1 > tu1 + eps or iv1 > tv1 + eps:
            print(f"[FAIL] {part_name}: island exceeds its tile region (bleed into adjacent tile)")
            overall_pass = False

        # --- Island coverage ---
        tile_area = max((tu1 - tu0) * (tv1 - tv0), 1e-9)
        island_area = (iu1 - iu0) * (iv1 - iv0)
        coverage = island_area / tile_area
        policy = meta.get("policy", "CONTAIN")
        if tile_id in _CYLINDER_TILES:
            # Narrow cylinders legitimately cover ~5% of a square tile (circumference <
            # tile width). Only flag a total-unwrap failure (< 2%).
            if coverage < 0.02:
                print(f"[FAIL] {part_name}: cylinder coverage {coverage*100:.2f}% < 2% (unwrap failed)")
                overall_pass = False
        elif policy == "ALIGN_BOTTOM" and coverage < COVERAGE_ALIGN_MIN:
            warnings.append(f"{part_name}: low coverage {coverage*100:.1f}% (ALIGN_BOTTOM)")
        elif policy == "CONTAIN" and coverage < COVERAGE_CONTAIN_MIN:
            print(f"[FAIL] {part_name}: CONTAIN coverage {coverage*100:.1f}% < {COVERAGE_CONTAIN_MIN*100:.0f}%")
            overall_pass = False

        # --- Cylinder anisotropy + seam + texel density ---
        areas = _face_areas(obj)
        quad_scales = [a_uv / max(a3d, 1e-9) for a_uv, a3d, is_quad in areas if is_quad and a3d > 1e-9 and a_uv > 1e-9]

        if tile_id in _CYLINDER_TILES and meta.get("primary", False):
            # Anisotropy: max/min per-face UV/3D scale (uniform stretch => ~1).
            if quad_scales:
                aniso = max(quad_scales) / max(min(quad_scales), 1e-9)
                if aniso > ANISOTROPY_MAX:
                    print(f"[FAIL] {part_name}: cylinder anisotropy {aniso:.2f}:1 > {ANISOTROPY_MAX} (stretch/FILL regression)")
                    overall_pass = False
            # Seam integrity: back-seam verts pinned to tile left AND right UV edges.
            if not _check_seam(obj, iu0, iu1):
                print(f"[FAIL] {part_name}: cylinder back-seam not pinned to tile L/R edges (orientation fault)")
                overall_pass = False

        if meta.get("primary", False):
            total_3d = sum(a3d for _, a3d, _ in areas)
            if total_3d > 1e-9:
                densities[part_name] = island_area / total_3d

    # --- Unintended UV overlap (non-mirror islands) ---
    names = list(active_islands.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if _rects_overlap(active_islands[names[i]], active_islands[names[j]]):
                # Overlap is only OK if both share the same tile_id (greeble inheriting parent tile).
                tid_i = manifest[names[i]]["tile_id"]
                tid_j = manifest[names[j]]["tile_id"]
                if tid_i != tid_j:
                    print(f"[FAIL] unintended overlap: {names[i]} ({tid_i}) x {names[j]} ({tid_j})")
                    overall_pass = False

    # --- Atlas tile occupancy ---
    missing = set(expected_tiles) - occupied_tiles
    if missing:
        for t in sorted(missing):
            print(f"[FAIL] atlas tile '{t}' unoccupied (would render atlas background)")
        overall_pass = False

    # --- Texel-density outlier (soft) ---
    if densities:
        vals = sorted(densities.values())
        median = vals[len(vals) // 2]
        for n, d in densities.items():
            if d > median * TEXEL_OUTLIER_FACTOR and median > 1e-9:
                warnings.append(f"{n}: texel density {d:.1f} > {TEXEL_OUTLIER_FACTOR}x median (greeble filling tile?)")

    for w in warnings:
        print(f"[WARN] {w}")

    if overall_pass:
        print(f"[validate_uv] PASS — {len(active_islands)} parts validated", flush=True)
    else:
        print(f"[validate_uv] FAIL — see failures above", flush=True)
    return overall_pass


def _check_seam(obj, u0, u1, tolerance=0.02):
    """Confirm verts exist at both the left and right UV edges of the island
    (the cylinder back-seam, which becomes both edges after the cut+unwrap)."""
    mesh = obj.data
    if not mesh.uv_layers:
        return False
    uv_layer = mesh.uv_layers.active
    left = right = False
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            ux = uv_layer.data[li].uv.x
            if abs(ux - u0) < tolerance:
                left = True
            if abs(ux - u1) < tolerance:
                right = True
            if left and right:
                return True
    return left and right


def _main():
    import sys
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    blend = None
    i = 0
    while i < len(args):
        if args[i] == "--blend" and i + 1 < len(args):
            blend = args[i + 1]
        i += 1
    if not blend:
        print("Usage: --blend <path.blend>")
        os._exit(1)
    bpy.ops.wm.open_mainfile(filepath=blend)
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)
    # Standalone mode: expects an unjoined blend (per-part objects present).
    try:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "pbr"))
        from atlas_layout import TILE_LAYOUT
        expected = set(TILE_LAYOUT.keys())
    except ImportError:
        expected = set()
    ok = validate_uv([o for o in bpy.context.scene.objects if o.type == 'MESH'], manifest, expected)
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    _main()