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


def _tri_area_3d(a, b, c) -> float:
    return _world_area([a, b, c])


def _world_area(coords) -> float:
    if len(coords) < 3:
        return 0.0
    a = Vector(coords[0])
    area = 0.0
    for i in range(1, len(coords) - 1):
        area += (Vector(coords[i]) - a).cross(Vector(coords[i + 1]) - a).length * 0.5
    return area


def _islands(me) -> list[list[int]]:
    """Union faces that share a mesh edge *and* coincident UVs along it.

    BMesh traversal, not RNA walks: the previous implementation scanned polygons
    through RNA for every edge-face pair and took 543 s on a 53k-tri unit.
    """
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        n = len(me.polygons)
        bm.free()
        return [list(range(n))]

    def loop_uv(face, vert):
        for loop in face.loops:
            if loop.vert == vert:
                return loop[uv_layer].uv
        return None

    def same_uv(a, b):
        return a is not None and b is not None and (
            abs(a[0] - b[0]) + abs(a[1] - b[1]) < 1e-6)

    seen = [False] * len(bm.faces)
    islands = []
    for face in bm.faces:
        if seen[face.index]:
            continue
        seen[face.index] = True
        stack = [face]
        comp = []
        while stack:
            cf = stack.pop()
            comp.append(cf.index)
            for edge in cf.edges:
                for nf in edge.link_faces:
                    if nf is cf or seen[nf.index]:
                        continue
                    ok = True
                    for v in edge.verts:
                        if not same_uv(loop_uv(cf, v), loop_uv(nf, v)):
                            ok = False
                            break
                    if ok:
                        seen[nf.index] = True
                        stack.append(nf)
        islands.append(comp)
    bm.free()
    return islands


def unwrap_and_grid(obj, texel_world_m: float, atlas_px: int,
                    margin_texels: int = 1) -> dict:
    """Apply the texel grid to `obj`; returns a measurement report.

    All per-loop work runs on foreach_get buffers: RNA access per loop made the
    per-island rescale take 750 s on a 53k-tri unit (measured).
    """
    import array

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

    def fetch():
        nv, npo, nl = len(me.vertices), len(me.polygons), len(me.loops)
        co = array.array("f", bytes(4 * 3 * nv)); me.vertices.foreach_get("co", co)
        ls = array.array("i", bytes(4 * npo)); me.polygons.foreach_get("loop_start", ls)
        lt = array.array("i", bytes(4 * npo)); me.polygons.foreach_get("loop_total", lt)
        lv = array.array("i", bytes(4 * nl)); me.loops.foreach_get("vertex_index", lv)
        uv = array.array("f", bytes(4 * 2 * nl)); me.uv_layers.active.data.foreach_get("uv", uv)
        return co, ls, lt, lv, uv

    def face_world_area(i, co, ls, lt, lv):
        idx = [lv[k] for k in range(ls[i], ls[i] + lt[i])]
        pts = [(co[3 * v], co[3 * v + 1], co[3 * v + 2]) for v in idx]
        a = 0.0
        for k in range(1, len(pts) - 1):
            a += _tri_area_3d(pts[0], pts[k], pts[k + 1])
        return a

    def face_uv_area(i, ls, lt, uv):
        idx = [ls[i] + k for k in range(lt[i])]
        pts = [(uv[2 * li], uv[2 * li + 1]) for li in idx]
        a = 0.0
        for k in range(1, len(pts) - 1):
            a += _tri_area_uv(pts[0], pts[k], pts[k + 1])
        return a

    co, ls, lt, lv, uv = fetch()
    world_area = sum(face_world_area(i, co, ls, lt, lv) for i in range(len(me.polygons)))
    needed_frac = world_area / (texel_world_m ** 2 * atlas_px ** 2)
    if needed_frac > 0.75:
        raise SystemExit(
            f"texel grid does not fit: {world_area:.3f} m2 needs {needed_frac:.1%} of a "
            f"{atlas_px}px atlas at {texel_world_m} m/texel; packing will not fit. "
            f"Increase atlas_px or texel_world_m.")

    islands = _islands(me)
    scaled = 0
    target_frac = texel_world_m ** 2 * atlas_px ** 2
    for faces in islands:
        loops = [ls[f] + k for f in faces for k in range(lt[f])]
        if not loops:
            continue
        uv_area = sum(face_uv_area(f, ls, lt, uv) for f in faces)
        w_area = sum(face_world_area(f, co, ls, lt, lv) for f in faces)
        target = w_area / target_frac
        if uv_area <= 1e-12 or target <= 0:
            continue
        s = math.sqrt(target / uv_area)
        cx = sum(uv[2 * li] for li in loops) / len(loops)
        cy = sum(uv[2 * li + 1] for li in loops) / len(loops)
        for li in loops:
            uv[2 * li] = (uv[2 * li] - cx) * s + cx
            uv[2 * li + 1] = (uv[2 * li + 1] - cy) * s + cy
        scaled += 1

    inv = 1.0 / atlas_px
    for i in range(len(uv) // 2):
        u = min(max(uv[2 * i], 0.0), 1.0 - inv)
        v = min(max(uv[2 * i + 1], 0.0), 1.0 - inv)
        uv[2 * i] = round(u * atlas_px) / atlas_px
        uv[2 * i + 1] = round(v * atlas_px) / atlas_px
    me.uv_layers.active.data.foreach_set("uv", uv)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    margin = margin_texels * inv
    try:
        bpy.ops.uv.pack_islands(rotate=False, scale=False, margin=margin,
                                margin_method="ADD")
    except TypeError:  # Blender <4.2 has no margin_method
        bpy.ops.uv.pack_islands(rotate=False, scale=False, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Re-lattice after packing: pack_islands translates islands by arbitrary
    # offsets, which undoes the snapping above.
    co, ls, lt, lv, uv = fetch()
    relattices = 0
    for faces in _islands(me):
        loops = [ls[f] + k for f in faces for k in range(lt[f])]
        if not loops:
            continue
        du = sum(uv[2 * li] * atlas_px - round(uv[2 * li] * atlas_px) for li in loops) / len(loops)
        dv = sum(uv[2 * li + 1] * atlas_px - round(uv[2 * li + 1] * atlas_px) for li in loops) / len(loops)
        if abs(du) > 1e-6 or abs(dv) > 1e-6:
            relattices += 1
        su, sv = -du / atlas_px, -dv / atlas_px
        for li in loops:
            uv[2 * li] = min(max(uv[2 * li] + su, 0.0), 1.0 - inv)
            uv[2 * li + 1] = min(max(uv[2 * li + 1] + sv, 0.0), 1.0 - inv)
    me.uv_layers.active.data.foreach_set("uv", uv)

    out_of_bounds = int(sum(1 for i in range(len(uv) // 2)
                            if not (-1e-6 <= uv[2 * i] <= 1 + 1e-6)
                            or not (-1e-6 <= uv[2 * i + 1] <= 1 + 1e-6)))
    if out_of_bounds:
        raise SystemExit(f"packing left {out_of_bounds} UV coords outside [0,1]; "
                         f"lower the texel density or raise atlas_px")

    used_uv = sum(face_uv_area(i, ls, lt, uv) for i in range(len(me.polygons)))
    texels_used = used_uv * atlas_px ** 2
    implied = (world_area / texels_used) if texels_used else 0.0
    target = texel_world_m ** 2
    if not texels_used or not (0.75 * target <= implied <= 1.25 * target):
        raise SystemExit(
            f"texel density contract not met: implied {implied:.6f} m2/texel vs "
            f"profile {target:.6f} m2/texel (world area {world_area:.3f} m2, "
            f"texels {texels_used:.1f})")
    return {
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
