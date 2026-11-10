"""pixel_uv.py — texel-grid UV stage for the `pixel_3d` profile.

The profile's `texture.texel_world_m` is a contract: one texture pixel covers a
fixed world area on every face of every asset. Without it, texels stretch across
large and small parts and the pixel grid swims as the camera moves.

What this does, on an existing mesh, in this order:

  1. unwrap (smart project) to get non-overlapping islands
  2. measure each island's 3D area and UV area, and scale each island so that
     `uv_area / atlas_px**2 == world_area / texel_world_m**2`
     — i.e. an exact, uniform texel density across the whole asset
  3. snap every UV vertex to the integer texel lattice
  4. re-pack islands without scaling (packing must not undo step 2)
  5. assert the result still fits inside [0,1] and report the measured density

If the asset's total surface area needs more texels than the atlas holds, this
raises: silently lowering the density would break the contract.

Used by `tools/blender/bake_pixel_atlas.py` (props/tiles) and the unit pixel
stage; importing from two scripts is why it is a module.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def _tri_area_uv(a, b, c) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5


def _world_area(coords) -> float:
    if len(coords) < 3:
        return 0.0
    a = Vector(coords[0])
    area = 0.0
    for i in range(1, len(coords) - 1):
        area += (Vector(coords[i]) - a).cross(Vector(coords[i + 1]) - a).length * 0.5
    return area


def _islands(me) -> list[list[int]]:
    """Union faces that share a mesh edge *and* coincident UVs along it."""
    uv = me.uv_layers.active.data
    parent = list(range(len(me.polygons)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edge_faces = {}
    for poly in me.polygons:
        for ek in poly.edge_keys:
            edge_faces.setdefault(ek, []).append(poly.index)

    def uv_of(poly_index, vid):
        poly = me.polygons[poly_index]
        for li in poly.loop_indices:
            if me.loops[li].vertex_index == vid:
                return (uv[li].uv.x, uv[li].uv.y)
        return None

    for ek, faces in edge_faces.items():
        if len(faces) < 2:
            continue
        v0, v1 = ek
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                a0, a1 = uv_of(faces[i], v0), uv_of(faces[i], v1)
                b0, b1 = uv_of(faces[j], v0), uv_of(faces[j], v1)
                if None in (a0, a1, b0, b1):
                    continue
                if max(abs(a0[0] - b0[0]) + abs(a0[1] - b0[1]),
                       abs(a1[0] - b1[0]) + abs(a1[1] - b1[1])) < 1e-6:
                    union(faces[i], faces[j])
    groups = {}
    for f in range(len(me.polygons)):
        groups.setdefault(find(f), []).append(f)
    return list(groups.values())


def unwrap_and_grid(obj, texel_world_m: float, atlas_px: int,
                    margin_texels: int = 1) -> dict:
    """Apply the texel grid to `obj`; returns a measurement report."""
    if texel_world_m <= 0:
        raise SystemExit("texel_world_m must be > 0")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    me = obj.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002)
    bpy.ops.uv.pack_islands(rotate=False, scale=True, margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")
    # re-fetch: every UV operator can reallocate the layer; a stale reference
    # reads freed memory and reports nonsense densities (observed 1e56 m2/texel)
    uv = me.uv_layers.active.data

    world_area = sum(_world_area([me.vertices[v].co for v in p.vertices])
                     for p in me.polygons)
    needed_frac = world_area / (texel_world_m ** 2 * atlas_px ** 2)
    if needed_frac > 0.75:
        raise SystemExit(
            f"texel grid does not fit: {world_area:.3f} m2 needs {needed_frac:.1%} of a "
            f"{atlas_px}px atlas at {texel_world_m} m/texel; packing will not fit. "
            f"Increase atlas_px or texel_world_m.")

    islands = _islands(me)
    scaled = 0
    for faces in islands:
        loops = [li for f in faces for li in me.polygons[f].loop_indices]
        uv_by_loop = {li: (uv[li].uv.x, uv[li].uv.y) for li in loops}
        uvs = [uv_by_loop[li] for li in loops]
        uv_area = 0.0
        for f in faces:
            li = list(me.polygons[f].loop_indices)
            for k in range(1, len(li) - 1):
                uv_area += _tri_area_uv(uv_by_loop[li[0]], uv_by_loop[li[k]],
                                        uv_by_loop[li[k + 1]])
        w_area = sum(_world_area([me.vertices[v].co for v in me.polygons[f].vertices])
                     for f in faces)
        target = w_area / (texel_world_m ** 2 * atlas_px ** 2)
        if uv_area <= 1e-12 or target <= 0:
            continue
        s = math.sqrt(target / uv_area)
        cx = sum(p[0] for p in uvs) / len(uvs)
        cy = sum(p[1] for p in uvs) / len(uvs)
        for li, p in zip(loops, uvs):
            uv[li].uv = ((p[0] - cx) * s + cx, (p[1] - cy) * s + cy)
        scaled += 1

    # snap to the texel lattice and keep the result inside the atlas
    inv = 1.0 / atlas_px
    for i in range(len(uv)):
        u = min(max(uv[i].uv.x, 0.0), 1.0 - inv)
        v = min(max(uv[i].uv.y, 0.0), 1.0 - inv)
        uv[i].uv = (round(u * atlas_px) / atlas_px, round(v * atlas_px) / atlas_px)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    margin = margin_texels * inv
    try:
        bpy.ops.uv.pack_islands(rotate=False, scale=False, margin=margin,
                                margin_method="ADD")
    except TypeError:  # Blender <4.2 has no margin_method
        bpy.ops.uv.pack_islands(rotate=False, scale=False, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = me.uv_layers.active.data

    # Re-lattice after packing. `pack_islands` TRANSLATES islands by arbitrary
    # offsets, so a fractional-texel translation silently undoes the snapping
    # above and every UV ends up off-lattice (observed: a 108-island column,
    # 100 % off-lattice, atlas therefore filtered). Translating each island by
    # the rounded offset keeps its shape and restores integer texel coordinates.
    islands_after = _islands(me)
    relattices = 0
    for faces in islands_after:
        loops = [li for f in faces for li in me.polygons[f].loop_indices]
        pts = [(uv[li].uv.x, uv[li].uv.y) for li in loops]
        du = sum(p[0] * atlas_px - round(p[0] * atlas_px) for p in pts) / len(pts)
        dv = sum(p[1] * atlas_px - round(p[1] * atlas_px) for p in pts) / len(pts)
        # remove the fractional part itself: each island shares one offset after a
        # translation, so subtracting the mean fraction restores integer texels
        # without distorting the island (rounding the mean would leave any
        # fractional drift below half a texel uncorrected — the original bug).
        su = -du / atlas_px
        sv = -dv / atlas_px
        if abs(du) > 1e-6 or abs(dv) > 1e-6:
            relattices += 1
        for li in loops:
            u, v = uv[li].uv.x + su, uv[li].uv.y + sv
            uv[li].uv = (min(max(u, 0.0), 1.0 - inv), min(max(v, 0.0), 1.0 - inv))

    us = [d.uv.x for d in uv]
    vs = [d.uv.y for d in uv]
    out_of_bounds = int(sum(1 for u in us if u < -1e-6 or u > 1 + 1e-6)
                        + sum(1 for v in vs if v < -1e-6 or v > 1 + 1e-6))
    if out_of_bounds:
        raise SystemExit(f"packing left {out_of_bounds} UV coords outside [0,1]; "
                         f"lower the texel density or raise atlas_px")

    # measured density: world area per texel actually assigned
    used_uv = 0.0
    for f in me.polygons:
        li = list(f.loop_indices)
        uvs = [(uv[i].uv.x, uv[i].uv.y) for i in li]
        for k in range(1, len(li) - 1):
            used_uv += _tri_area_uv(uvs[0], uvs[k], uvs[k + 1])
    texels_used = used_uv * atlas_px ** 2
    implied = (world_area / texels_used) if texels_used else 0.0
    target = texel_world_m ** 2
    if not texels_used or not (0.75 * target <= implied <= 1.25 * target):
        raise SystemExit(
            f"texel density contract not met: implied {implied:.6f} m2/texel vs "
            f"profile {target:.6f} m2/texel (world area {world_area:.3f} m2, "
            f"texels {texels_used:.1f})")
    report = {
        "atlas_px": atlas_px,
        "texel_world_m": texel_world_m,
        "world_area_m2": round(world_area, 4),
        "texels_used": round(texels_used, 1),
        "utilisation": round(texels_used / (atlas_px ** 2), 4),
        "implied_world_area_per_texel": round(implied, 6),
        "contract_world_area_per_texel": target,
        "islands": len(islands),
        "islands_rescaled": scaled,
        "uv_out_of_bounds": out_of_bounds,
        "uv_lattice_snapped": True,
        "islands_relattices": relattices,
    }
    return report


def report_path(out: Path) -> Path:
    return out / "texel_uv_report.json"


def write_report(out: Path, report: dict, extra: dict | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = report_path(out)
    payload = dict(report)
    if extra:
        payload.update(extra)
    p.write_text(json.dumps(payload, indent=2) + "\n")
    return p
