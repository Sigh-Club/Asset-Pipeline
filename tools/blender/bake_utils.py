#!/usr/bin/env python3
"""bake_utils.py — bake passes, bake verification and texel arithmetic, shared.

Extracted so `aaa_rebuild.py` (whole-body bake) and `aaa_assemble.py` (per-part bake)
use one implementation. Every rule here traces to a measured failure:

* a bake that wrote nothing must fail, not ship (two all-zero albedo maps were shipped
  silently on 2026-11-23 before this check existed);
* UV area must be measured with foreach_get — a per-face Python loop took minutes on a
  100K mesh and its bmesh shoelace was 100x wrong;
* texel density is computed, never assumed: px/m = sqrt(UV area) * res / sqrt(world area),
  and the PC band floor is 1024 px/m (docs/STYLE_BANDS.md).
"""
from __future__ import annotations

import math

import bpy


def log(m: str) -> None:
    print(f'[bake_utils] {m}', flush=True)


def measure_areas(obj) -> tuple[float, float]:
    """World surface area and UV area (exact, vectorised)."""
    import numpy as np
    mesh = obj.data
    n_poly = len(mesh.polygons)
    if not n_poly:
        return 0.0, 0.0
    world = np.empty(n_poly, dtype=np.float64)
    mesh.polygons.foreach_get('area', world)
    a_world = float(world.sum()) * abs(obj.scale.x * obj.scale.y)
    a_uv = 0.0
    if mesh.uv_layers.active:
        mesh.calc_loop_triangles()
        n_tri = len(mesh.loop_triangles)
        if n_tri:
            tri_loops = np.empty(n_tri * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get('loops', tri_loops)
            uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
            mesh.uv_layers.active.data.foreach_get('uv', uv)
            tri = uv.reshape(-1, 2)[tri_loops.reshape(-1, 3)]
            ax, ay = tri[:, 0, 0], tri[:, 0, 1]
            bx, by = tri[:, 1, 0], tri[:, 1, 1]
            cx, cy = tri[:, 2, 0], tri[:, 2, 1]
            a_uv = float(np.abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)).sum() * 0.5)
    return a_world, a_uv


def density_px_m(a_world: float, a_uv: float, res: int) -> float:
    if a_world <= 0 or a_uv <= 0:
        return 0.0
    return math.sqrt(a_uv) * res / math.sqrt(a_world)


def pick_resolution(a_world: float, a_uv: float, target_density: float,
                    lo: int = 512, hi: int = 2048) -> int:
    """Smallest power of two that meets the target px/m for this part's area.

    Per-part resolution is the point of per-part bakes: a pauldron should not share
    the torso's texel budget. A part whose area needs more than `hi` gets `hi`.
    """
    if a_world <= 0 or a_uv <= 0:
        return lo
    needed = target_density * math.sqrt(a_world / a_uv)
    res = 1 << max(9, min(12, math.ceil(math.log2(max(needed, 1)))))
    return max(lo, min(hi, res))


def unwrap(obj, angle_deg: float = 66.0, padding_px: int = 32, res: int = 2048) -> float:
    """Fresh 0-1 layout with measured padding. Returns the margin used."""
    margin = padding_px / float(res)
    bpy.context.view_layer.objects.active = obj
    for o in bpy.data.objects:
        o.select_set(o is obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin,
                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    # smart_project does not guarantee a 0-1 packing at high face counts; without an
    # explicit pack the islands overflow and the bake lands in empty UV space
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    return margin


def verify_bake(image, kind: str) -> bool:
    """A bake that wrote nothing is a failure, not a texture."""
    import numpy as np
    px = np.array(image.pixels[:], dtype=np.float32).reshape(-1, 4)[:, :3]
    mean = float(px.mean()) if px.size else 0.0
    peak = float(px.max()) if px.size else 0.0
    ok = mean > 0.002 and peak > 0.05
    log(f'bake check {kind} {image.size[0]}px: mean={mean:.4f} peak={peak:.3f} '
        f'-> {"ok" if ok else "EMPTY"}')
    return ok


def bake_pass(kind: str, image, sources: list, target, samples: int, extrusion: float,
              max_ray: float, margin: int = 16) -> bool:
    """Bake `kind` from `sources` onto `target`'s active UV. Returns success."""
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'
    scene.cycles.samples = samples
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = extrusion
    scene.render.bake.max_ray_distance = max_ray
    scene.render.bake.margin = margin
    scene.render.bake.use_clear = True

    for o in bpy.data.objects:
        o.select_set(False)
    for o in sources:
        o.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    for slot in target.material_slots:
        mat = slot.material
        if not mat:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        node = nt.nodes.get(f'BAKE_TARGET_{kind}') or nt.nodes.new('ShaderNodeTexImage')
        node.name = f'BAKE_TARGET_{kind}'
        node.image = image
        nt.nodes.active = node

    try:
        bpy.ops.object.bake(type=kind)
    except Exception as e:
        log(f'bake {kind} failed: {type(e).__name__}: {str(e)[:160]}')
        return False
    return verify_bake(image, kind)


def bake_albedo_transfer(src_obj, dst_obj, image, extrusion: float, max_ray: float) -> bool:
    """Rebake a mesh's own base colour onto a fresh layout (same geometry: exact).

    Uses an Emission route because the DIFFUSE colour-only pass returned an all-zero
    image on this asset (measured 2026-11-23).
    """
    restore = []
    for slot in src_obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        nt = mat.node_tree
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not (out and bsdf):
            continue
        emit = nt.nodes.new('ShaderNodeEmission')
        base = bsdf.inputs['Base Color']
        if base.is_linked:
            nt.links.new(base.links[0].from_socket, emit.inputs['Color'])
        else:
            emit.inputs['Color'].default_value = base.default_value
        restore.append((nt, out, emit))
        nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    try:
        return bake_pass('EMIT', image, [src_obj], dst_obj, 1, extrusion, max_ray)
    finally:
        for nt, out, emit in restore:
            nt.nodes.remove(emit)
