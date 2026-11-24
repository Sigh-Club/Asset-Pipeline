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
from pathlib import Path

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


def capture_uv(obj) -> "object":
    """Snapshot the active UV layout as an array (per loop), before it is overwritten."""
    import numpy as np
    mesh = obj.data
    if not mesh.uv_layers.active:
        return None
    buf = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers.active.data.foreach_get('uv', buf)
    return buf.reshape(-1, 2)


def transfer_uv_texture(obj, src_uv, dst_uv, src_image, out_res: int,
                        dilate_px: int = 4):
    """Resample a texture from one UV layout to another on the SAME mesh.

    Ray-cast bakes are unreliable for this case: the source and target are coincident,
    and on open shells the ray misses (measured: 2 of 4 parts returned ~0.1% coverage
    even at zero extrusion). This is a UV-space rasteriser instead — exact, no rays.

    For every triangle: rasterise its destination-UV triangle into pixels, compute the
    barycentric coordinate of each covered pixel, sample the source image at the
    corresponding point of the triangle's source-UV coordinates.
    """
    import numpy as np
    mesh = obj.data
    # src_uv may be a captured array (preferred) or a layer name
    if isinstance(src_uv, str):
        uvs = {uv.name for uv in mesh.uv_layers}
        if src_uv not in uvs or dst_uv not in uvs:
            log(f'transfer skipped: have {sorted(uvs)}, need {src_uv!r} and {dst_uv!r}')
            return False
        old_uv = None
    else:
        old_uv = src_uv

    src_px = np.array(src_image.pixels[:], dtype=np.float32).reshape(
        src_image.size[1], src_image.size[0], 4)
    sh, sw = src_px.shape[:2]

    mesh.calc_loop_triangles()
    tri_loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get('loops', tri_loops)
    tri_loops = tri_loops.reshape(-1, 3)

    def uv_array(name: str) -> np.ndarray:
        layer = mesh.uv_layers[name]
        buf = np.empty(len(mesh.loops) * 2, dtype=np.float64)
        layer.data.foreach_get('uv', buf)
        return buf.reshape(-1, 2)

    if old_uv is None:
        old_uv = uv_array(src_uv)
    new_uv = uv_array(dst_uv)

    out = np.zeros((out_res, out_res, 4), dtype=np.float32)
    filled = np.zeros((out_res, out_res), dtype=bool)

    for tri in tri_loops:
        d = new_uv[tri] * out_res            # destination pixel coords
        s = old_uv[tri]
        x0, y0 = np.floor(d.min(axis=0)).astype(int)
        x1, y1 = np.ceil(d.max(axis=0)).astype(int)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(out_res - 1, x1), min(out_res - 1, y1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        px, py = xs.ravel(), ys.ravel()
        # barycentric test in destination space
        ax, ay = d[0]; bx, by = d[1]; cx, cy = d[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            # degenerate in destination space: splat its vertices so the island is
            # still covered (holes here showed up as white patches on the render)
            for vi in range(3):
                sxv = int(np.clip(s[vi][0] * sw, 0, sw - 1))
                syv = int(np.clip(s[vi][1] * sh, 0, sh - 1))
                oxv = int(np.clip(d[vi][0], 0, out_res - 1))
                oyv = int(np.clip(d[vi][1], 0, out_res - 1))
                out[oyv, oxv] = src_px[syv, sxv]
                filled[oyv, oxv] = True
            continue
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        w0, w1, w2 = w0[inside], w1[inside], w2[inside]
        # corresponding source UV
        su = w0 * s[0][0] + w1 * s[1][0] + w2 * s[2][0]
        sv = w0 * s[0][1] + w1 * s[1][1] + w2 * s[2][1]
        sx = np.clip((su * sw).astype(int), 0, sw - 1)
        sy = np.clip((sv * sh).astype(int), 0, sh - 1)
        ox = px[inside].astype(int)
        oy = py[inside].astype(int)
        out[oy, ox] = src_px[sy, sx]
        filled[oy, ox] = True

    # bleed: expand the filled region so mip filtering does not sample black
    for _ in range(max(dilate_px, 12)):
        grown = filled.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            shifted_fill = np.roll(filled, (dy, dx), axis=(0, 1))
            shifted_val = np.roll(out, (dy, dx), axis=(0, 1))
            take = shifted_fill & ~grown
            out[take] = shifted_val[take]
            grown |= take
        filled = grown

    sampled_mean = float(out[filled][:, :3].mean()) if filled.any() else 0.0
    log(f'resample sampled-source mean={sampled_mean:.3f} (atlas mean='
        f'{float(src_px[:, :, :3].mean()):.3f})')
    coverage = float(filled.mean())
    target = bpy.data.images.new(f'{obj.name}_resampled', out_res, out_res, alpha=False)
    target.pixels = out.ravel().tolist()
    log(f'uv transfer {src_uv}->{dst_uv} at {out_res}px: coverage {coverage:.1%}')
    return target


def project_reference_texture(obj, views: dict, out_res: int, dilate_px: int = 12,
                              bounds=None):
    """Project reference images onto the mesh as albedo (multiview projection texturing).

    This is what a reference-driven texturing pipeline does, and it is the only way to get
    an albedo that actually matches the concept: the shipped palette atlas is a 2048
    texture authored for the pixel tier, and compositing library detail over it cannot
    invent the design's own colours.

    views: {'front'|'back'|'left'|'right': image_path}. Each texel is filled from the view
    whose axis best matches that triangle's normal, using an orthographic mapping of the
    mesh's bounding box onto the image. Faces pointing away from every view stay unfilled
    and are bled from their neighbours.
    """
    import numpy as np

    mesh = obj.data
    if not mesh.uv_layers.active:
        log('projection skipped: no UV layer')
        return None

    imgs = {}
    for name, path in views.items():
        if not path or not Path(path).exists():
            continue
        # PIL is not reliably importable inside Blender (libtiff soname clash), so use
        # Blender's own loader. Its pixel buffer is bottom-up, which matches UV space, so
        # no vertical flip is applied below.
        bi = bpy.data.images.load(str(path))
        w, h = bi.size
        buf = np.array(bi.pixels[:], dtype=np.float32).reshape(h, w, 4)
        imgs[name] = buf[:, :, :3]
        bpy.data.images.remove(bi)
    if not imgs:
        log('projection skipped: no readable reference views')
        return None
    log(f'projecting {sorted(imgs)} onto {obj.name} at {out_res}px')

    co = np.array([obj.matrix_world @ v.co for v in mesh.vertices], dtype=np.float64)
    # The projection must map the WHOLE CHARACTER onto the reference, not this part.
    # Using the part's own bbox stretched a small part (trousers) across the entire
    # image, so every texel sampled the dark torso (measured 2026-11-23).
    if bounds is not None:
        lo = np.asarray(bounds[0], dtype=np.float64)
        hi = np.asarray(bounds[1], dtype=np.float64)
    else:
        lo, hi = co.min(axis=0), co.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)

    mesh.calc_loop_triangles()
    tri_loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get('loops', tri_loops)
    tri_loops = tri_loops.reshape(-1, 3)
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)

    # per-vertex normals for view selection
    nrm = np.array([v.normal for v in mesh.vertices], dtype=np.float64)
    loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_verts)

    # axis/sign per view: front looks along -Y, back +Y, left -X, right +X
    # Each view needs TWO axes: which axis its surface normal must point along, and which
    # axis is HORIZONTAL in the image. Conflating them was the bug — the front view's
    # horizontal was taken as Y (depth), so every island sampled one line of the image and
    # the result was dark vertical striping (measured 2026-11-23).
    VIEWS = {
        'front': {'n_axis': 1, 'n_sign': -1.0, 'h_axis': 0, 'mirror': False},
        'back':  {'n_axis': 1, 'n_sign': 1.0,  'h_axis': 0, 'mirror': True},
        'left':  {'n_axis': 0, 'n_sign': -1.0, 'h_axis': 1, 'mirror': False},
        'right': {'n_axis': 0, 'n_sign': 1.0,  'h_axis': 1, 'mirror': True},
    }

    out = np.zeros((out_res, out_res, 4), dtype=np.float32)
    out[:, :, 3] = 1.0
    filled = np.zeros((out_res, out_res), dtype=bool)

    for tri in tri_loops:
        d = uv[tri] * out_res
        x0, y0 = np.floor(d.min(axis=0)).astype(int)
        x1, y1 = np.ceil(d.max(axis=0)).astype(int)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(out_res - 1, x1), min(out_res - 1, y1)
        if x1 < x0 or y1 < y0:
            continue
        # view selection from the triangle normal
        n = nrm[loop_verts[tri]].mean(axis=0)
        best, best_dot = None, 0.0
        for name, cfg in VIEWS.items():
            if name not in imgs:
                continue
            vec = np.zeros(3)
            vec[cfg['n_axis']] = cfg['n_sign']
            dot = float(np.dot(n, vec))
            if dot > best_dot:
                best, best_dot = name, dot
        if best is None or best_dot <= 0.15:
            continue
        img = imgs[best]
        cfg = VIEWS[best]
        ih, iw = img.shape[:2]
        p3 = co[loop_verts[tri]]                      # triangle in world space

        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        px, py = xs.ravel(), ys.ravel()
        ax, ay = d[0]; bx, by = d[1]; cx, cy = d[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        w0, w1, w2 = w0[inside], w1[inside], w2[inside]
        pos = (w0[:, None] * p3[0] + w1[:, None] * p3[1] + w2[:, None] * p3[2])
        # orthographic projection of the mesh bbox onto the reference image
        h_axis = cfg['h_axis']
        u = (pos[:, h_axis] - lo[h_axis]) / span[h_axis]
        if cfg['mirror']:
            u = 1.0 - u
        v = (pos[:, 2] - lo[2]) / span[2]
        sx = np.clip((u * (iw - 1)).astype(int), 0, iw - 1)
        # Blender's pixel buffer for a loaded image is top-down in this build: sampling
        # it with v up gives an upside-down projection (measured 2026-11-23 — the helmet
        # took the boots' colour and the legs took the torso's). Flip to fix.
        sy = np.clip(((1.0 - v) * (ih - 1)).astype(int), 0, ih - 1)
        ox = np.clip(px[inside].astype(int), 0, out_res - 1)
        oy = np.clip(py[inside].astype(int), 0, out_res - 1)
        out[oy, ox, :3] = img[sy, sx]
        filled[oy, ox] = True

    for _ in range(max(dilate_px, 12)):
        grown = filled.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sf = np.roll(filled, (dy, dx), axis=(0, 1))
            sv = np.roll(out, (dy, dx), axis=(0, 1))
            take = sf & ~grown
            out[take] = sv[take]
            grown |= take
        filled = grown

    log(f'projection coverage {float(filled.mean()):.1%}')
    tex = bpy.data.images.new(f'{obj.name}_projected', out_res, out_res, alpha=False)
    tex.pixels = out.ravel().tolist()
    return tex


def flatten_albedo(image, sigma_px: int = 24, strength: float = 0.85):
    """Remove large-scale luminance variation (baked lighting) from an albedo.

    The library albedos were derived from photographed material sheets, so they carry the
    original lighting: bright patches that read as specular highlights when re-lit in 3D.
    Our own docs call this "a geometry lie" (gemini-image skill). A high-pass normalisation
    keeps the detail and removes the lighting, which is what an authored albedo looks like.
    """
    import numpy as np
    w, h = image.size
    px = np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)
    rgb = px[:, :, :3]
    # Blur LUMINANCE only. Blurring each channel separately and dividing by it normalises
    # every channel to the same mean, which wipes the colour out (measured: the gate read
    # the result as "entirely grayscale").
    lum = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2])[:, :, None]
    acc = lum.copy()
    k = max(3, int(sigma_px))
    for _ in range(3):
        pad = np.pad(acc, ((k // 2, k // 2), (0, 0), (0, 0)), mode='edge')
        acc = sum(pad[i:i + h] for i in range(k)) / k
        pad = np.pad(acc, ((0, 0), (k // 2, k // 2), (0, 0)), mode='edge')
        acc = sum(pad[:, i:i + w] for i in range(k)) / k
    low = np.maximum(acc, 1e-3)
    flat = rgb / low * float(low.mean())     # same luminance field for all channels
    flat = rgb * (1.0 - strength) + flat * strength
    out = px.copy()
    out[:, :, :3] = np.clip(flat, 0.0, 1.0)
    tex = bpy.data.images.new(f'{image.name}_flat', w, h, alpha=False)
    tex.pixels = out.ravel().tolist()
    log(f'flattened albedo {image.name} (sigma={sigma_px}, strength={strength})')
    return tex
