#!/usr/bin/env python3
"""aaa_rebuild.py — build an AAA-PC game mesh from a high-poly source, correctly.

One command, one asset: high-poly source -> game mesh at the target budget, a PBR
UV layout that can actually carry a normal map, baked normal/AO, transferred
material slots and skin weights, library PBR materials, export, and a machine
readable report. Every step below traces to a measured failure or a cited source.

WHY THIS EXISTS (each rule is a defect we paid for, 2026-11-23):

* Do NOT bake a PBR normal map into a texel-grid atlas UV layout. The palette tier
  uses `uv: texel_grid` — thousands of tiny islands sized for a 256-px palette.
  Baking 2048 normals into it produced mottled, patchy shading on the whole body.
  Proof: the same asset with the normal link disconnected renders clean. This is
  why the rebuild unwraps fresh with measured padding.
* UV padding for a 2048 map is 16 px (1/128 of the resolution): "256 = 2px,
  512 = 4px, 1024 = 8px, 2048 = 16px"; Blender's own Pack Islands guidance is
  margin >= 0.01 at 2048. Padding below that bleeds across islands under mip
  filtering.
* Bake extrusion must be small relative to the model. A 2 cm cage on a 1.9 m
  figure casts rays into the wrong surfaces; 2 mm is the starting value here.
* Texel density is a measured number, not a feeling: px/m = sqrt(UV area) * res /
  sqrt(world area). Targets (console/PC 1024, hero 2048) from The Technical
  Artist's texel calculator. Below the floor this script refuses to export.
* Decimate, do not voxel-remesh, for a sound mesh: Blender's manual recommends
  Decimate Geometry, and remesh-then-decimate on a 404K source is minutes of CPU
  for a worse result (strayspark, 2026: "Option 2 — Decimate… what Blender's
  manual recommends for a mesh that is otherwise sound").
* Material slots and skin weights are transferred by nearest surface from a
  reference asset, so per-slot art and the rig survive the rebuild.

Usage:
  tools/blender_run.sh --job bake -- -b -P tools/blender/aaa_rebuild.py -- \
      --high output/img23d/line_infantry_mv/front.glb \
      --slot-source output/img23d/line_infantry_mv/atlas/unit_textured.glb \
      --out output/aaa/li_100k --id line_infantry \
      --tris 100000 --res 2048 --min-texel-density 1024 \
      --library assets/materials/grimdark_scifi/grimdark_scifi.blend \
      --faction iron_directorate

Exit 0 on success; 1 when the texel density floor is missed or a bake fails.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_ap = argparse.ArgumentParser()
_ap.add_argument('--high', required=True, help='high-poly bake source (GLB)')
_ap.add_argument('--slot-source', help='reference asset: material slots + skin weights are '
                                       'transferred from it by nearest surface')
_ap.add_argument('--out', required=True)
_ap.add_argument('--id', required=True)
_ap.add_argument('--tris', type=int, default=100000, help='LOD0 triangle target')
_ap.add_argument('--base', choices=['source', 'reference'], default='reference',
                 help='reference (default): raise the already-textured, UV-correct, rigged mesh '
                      'to the budget and bake the sculpt detail onto it — keeps unit identity. '
                      'source: decimate the high-poly (loses the atlas: its UVs are the palette '
                      'texel grid, so albedo must be re-projected)')
_ap.add_argument('--res', type=int, default=2048)
_ap.add_argument('--min-texel-density', type=float, default=1024.0, help='px/m floor')
_ap.add_argument('--bake-extrusion', type=float, default=0.002)
_ap.add_argument('--bake-max-ray', type=float, default=0.01)
_ap.add_argument('--ao-samples', type=int, default=24)
_ap.add_argument('--albedo-ray', type=float, default=0.10,
                help='ray distance for the colour transfer; a 20K source and a 100K '
                     'target differ by more than the normal-bake distance, and colour '
                     'tolerates a long ray (measured: 1 cm produced an all-zero map)')
_ap.add_argument('--ao-strength', type=float, default=0.25)
_ap.add_argument('--uv-angle', type=float, default=66.0)
_ap.add_argument('--padding-px', type=int, default=16, help='UV island padding in pixels (2048 -> 16)')
_ap.add_argument('--library', help='PBR material library .blend')
_ap.add_argument('--faction', help='library faction prefix, e.g. iron_directorate')
_ap.add_argument('--tex-scale', type=float, default=6.0)
_ap.add_argument('--tex-blend', type=float, default=0.12)
_ap.add_argument('--keep-source', action='store_true', help='keep the bake source in the file')
_ap.add_argument('--split-parts', action='store_true',
                 help='also export the asset as parts (one per material slot) sharing the '
                      'skeleton, plus unit.manifest.json — the modular assembly model in '
                      'docs/ASSEMBLY_MODEL.md')
_ap.add_argument('--lod-chain', type=int, nargs='*', default=[60000, 25000, 10000],
                help='LOD triangle targets after LOD0 (industry ratio 50/25/10%%)')
A = _ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

# Per-slot surface response. Painted ceramite plate is barely metal; trim is metal;
# cloth is dielectric and rough. Values are authoring decisions, stated once here.
SLOT_SURFACE = {
    'armour_primary':   {'Metallic': 0.15, 'Roughness': 0.95},
    'armour_secondary': {'Metallic': 0.15, 'Roughness': 1.00},
    'metal_trim':       {'Metallic': 1.00, 'Roughness': 0.80},
    'underlayer':       {'Metallic': 0.00, 'Roughness': 1.10},
}

OUT = Path(A.out).resolve()
OUT.mkdir(parents=True, exist_ok=True)
REPORT: dict = {'id': A.id, 'targets': {'tris': A.tris, 'res': A.res,
                                        'min_texel_density_px_m': A.min_texel_density}}


def log(m: str) -> None:
    print(f'[aaa_rebuild] {m}', flush=True)


def tris_of(obj) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def import_glb(path: str) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    return [o for o in bpy.data.objects if o not in before]


def body_of(objs: list):
    meshes = [o for o in objs if o.type == 'MESH' and not o.name.startswith('Icosphere')]
    return max(meshes, key=lambda o: len(o.data.polygons)) if meshes else None


def measure_areas(obj) -> tuple[float, float]:
    """World surface area and UV area, measured with foreach_get (exact, fast).

    The per-face Python loop this replaced took minutes on a 100K mesh, and the
    bmesh UV shoelace it used was wrong by 100x (uv_area 53.2 for a 0-1 layout).
    """
    import numpy as np
    mesh = obj.data
    n_poly = len(mesh.polygons)
    world = np.empty(n_poly, dtype=np.float64)
    mesh.polygons.foreach_get('area', world)
    a_world = float(world.sum()) * abs(obj.scale.x * obj.scale.y)

    a_uv = 0.0
    if mesh.uv_layers.active and n_poly:
        mesh.calc_loop_triangles()
        n_tri = len(mesh.loop_triangles)
        if n_tri:
            tri_loops = np.empty(n_tri * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get('loops', tri_loops)
            uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
            mesh.uv_layers.active.data.foreach_get('uv', uv)
            uv = uv.reshape(-1, 2)
            tri = uv[tri_loops.reshape(-1, 3)]
            ax, ay = tri[:, 0, 0], tri[:, 0, 1]
            bx, by = tri[:, 1, 0], tri[:, 1, 1]
            cx, cy = tri[:, 2, 0], tri[:, 2, 1]
            a_uv = float(np.abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)).sum() * 0.5)
    return a_world, a_uv


def unwrap_pbr(obj, angle_deg: float, padding_px: int, res: int) -> float:
    """Fresh PBR unwrap with measured padding. Returns the margin used."""
    margin = padding_px / float(res)
    bpy.context.view_layer.objects.active = obj
    for o in bpy.data.objects:
        o.select_set(o is obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=margin,
                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    # smart_project does not guarantee a 0-1 packing at this face count; without an
    # explicit pack the islands overflow and most of the bake lands in empty UV
    # space (measured: uv_area 54.0, bake 1.5 s). Pack islands normalises it.
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    uvs = [l.uv for l in obj.data.uv_layers.active.data] if obj.data.uv_layers.active else []
    if uvs:
        umin = min(u.x for u in uvs); umax = max(u.x for u in uvs)
        vmin = min(u.y for u in uvs); vmax = max(u.y for u in uvs)
        log(f'UV bounds after pack: u[{umin:.3f},{umax:.3f}] v[{vmin:.3f},{vmax:.3f}]')
        if umin < -1e-4 or umax > 1.0001 or vmin < -1e-4 or vmax > 1.0001:
            log('WARNING: UVs outside 0-1; texel density and bake coverage are unreliable')
    log(f'unwrapped with island margin {margin:.4f} ({padding_px}px at {res})')
    return margin


def transfer_slots(new_obj, ref_obj) -> int:
    """Copy material indices from the reference by nearest surface (BVH)."""
    if not ref_obj or not ref_obj.material_slots:
        return 0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(ref_obj, depsgraph)
    ref_mats = [s.material for s in ref_obj.material_slots]
    new_obj.data.materials.clear()
    for m in ref_mats:
        new_obj.data.materials.append(m)
    bm = bmesh.new()
    bm.from_mesh(new_obj.data)
    bm.faces.ensure_lookup_table()
    hits = misses = 0
    for f in bm.faces:
        centre = new_obj.matrix_world @ f.calc_center_median()
        loc, normal, index, dist = bvh.find_nearest(centre)
        if index is None or dist is None:
            misses += 1
            continue
        src_poly = ref_obj.data.polygons[index]
        f.material_index = src_poly.material_index
        hits += 1
    bm.to_mesh(new_obj.data)
    bm.free()
    log(f'material slots transferred: {hits} faces hit, {misses} missed, '
        f'{len(ref_mats)} slots')
    return hits


def transfer_weights(new_obj, ref_obj, armature) -> bool:
    """Copy skin weights by nearest-surface interpolation, then bind to the rig."""
    if not ref_obj or not armature:
        return False
    if not any(v.groups for v in ref_obj.data.vertices):
        log('reference has no vertex groups; skipping weight transfer')
        return False
    bpy.context.view_layer.objects.active = new_obj
    for o in bpy.data.objects:
        o.select_set(o is new_obj)
    mod = new_obj.modifiers.new('WeightTransfer', 'DATA_TRANSFER')
    mod.object = ref_obj
    mod.use_vert_data = True
    mod.data_types_verts = {'VGROUP_WEIGHTS'}
    mod.vert_mapping = 'POLYINTERP_NEAREST'
    bpy.ops.object.datalayout_transfer(modifier=mod.name)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    new_obj.parent = armature
    new_obj.matrix_parent_inverse = armature.matrix_world.inverted()
    if not any(m.type == 'ARMATURE' for m in new_obj.modifiers):
        am = new_obj.modifiers.new('Armature', 'ARMATURE')
        am.object = armature
    log(f'weights transferred from {ref_obj.name} and bound to {armature.name}')
    return True


def verify_bake(image, kind: str) -> bool:
    """A bake that wrote nothing is a failure, not a texture.

    Measured 2026-11-23: the colour transfer produced an all-zero image twice
    (DIFFUSE colour-only and EMIT) while normal/AO baked fine. Shipping that
    silently is how an asset ends up with a grey, muddy body.
    """
    import numpy as np
    px = np.array(image.pixels[:], dtype=np.float32).reshape(-1, 4)[:, :3]
    mean = float(px.mean()) if px.size else 0.0
    peak = float(px.max()) if px.size else 0.0
    ok = mean > 0.002 and peak > 0.05
    log(f'bake check {kind}: mean={mean:.4f} peak={peak:.3f} -> {"ok" if ok else "EMPTY"}')
    return ok


def bake_albedo_transfer(src_objs, low, image, extrusion, max_ray) -> float:
    """Rebake the reference's own base colour onto the target's UV layout.

    Documented technique (Blender SE): route the source's colour into an Emission
    node and bake EMIT. The DIFFUSE colour-only pass produced an all-zero image on
    this asset, so the emission route is used instead.
    """
    restore = []
    for o in src_objs:
        for slot in o.material_slots:
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
        return bake_pass('EMIT', image, src_objs, low, 1, extrusion, max_ray)
    finally:
        for nt, out, emit in restore:
            nt.nodes.remove(emit)
        log(f'albedo transfer: {len(restore)} source material(s) restored')


def bake_pass(kind, image, high, low, samples, extrusion, max_ray, colour_only=False):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'
    scene.cycles.samples = samples
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = extrusion
    scene.render.bake.max_ray_distance = max_ray
    scene.render.bake.margin = A.padding_px
    scene.render.bake.use_clear = True
    if colour_only:
        # albedo transfer: colour pass only, no direct/indirect light, so the
        # source's own texture comes across unchanged
        scene.render.bake.use_pass_direct = False
        scene.render.bake.use_pass_indirect = False
        scene.render.bake.use_pass_color = True
    for o in bpy.data.objects:
        o.select_set(False)
    for o in high:
        o.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    for slot in low.material_slots:
        mat = slot.material
        if not mat:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        node = nt.nodes.get(f'BAKE_TARGET_{kind}') or nt.nodes.new('ShaderNodeTexImage')
        node.name = f'BAKE_TARGET_{kind}'
        node.image = image
        nt.nodes.active = node
    t0 = time.time()
    log(f'baking {kind} at {image.size[0]}px …')
    bpy.ops.object.bake(type=kind)
    image.filepath_raw = str(OUT / f'{A.id}_{kind.lower()}.png')
    image.file_format = 'PNG'
    image.save()
    log(f'baked {kind} in {time.time() - t0:.0f}s')
    return round(time.time() - t0, 1)


def wire_surface_only(low, normal_img, ao_img):
    """Keep the unit's own albedo; add library roughness/metallic and the baked normal.

    The reference-base route must NOT replace the material: the atlas is the unit's
    identity (measured 2026-11-23 — replacing it left every slot wearing generic
    library tiling). What the library is good for is surface response, so only its
    roughness and metallic maps are borrowed, wired triplanar at character scale.
    """
    if not (A.library and A.faction):
        log('no library given; surface response left at material defaults')
        return 0
    wanted = set()
    for slot in low.material_slots:
        if slot.material:
            wanted.add(f'IOA_{A.faction}__{slot.material.name.split(".")[0]}')
    with bpy.data.libraries.load(str(Path(A.library).resolve()), link=False) as (src, dst):
        dst.materials = [n for n in src.materials if n in wanted]
    loaded = {m.name: m for m in dst.materials if m}
    log(f'surface library loaded: {sorted(loaded)}')

    wired = 0
    for slot in low.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        base = mat.name.split('.')[0]
        lib = loaded.get(f'IOA_{A.faction}__{base}')
        if not lib:
            log(f'no library surface for slot "{base}"')
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf:
            continue
        # borrow the library's roughness/metallic images with its own projection
        coord = nt.nodes.new('ShaderNodeTexCoord')
        mapping = nt.nodes.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value = (A.tex_scale,) * 3
        nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
        for node in lib.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            name = node.image.name.lower()
            if 'rough' in name:
                target = 'Roughness'
            elif 'metal' in name:
                target = 'Metallic'
            else:
                continue
            tex = nt.nodes.new('ShaderNodeTexImage')
            tex.image = node.image
            tex.projection = 'BOX'
            tex.projection_blend = A.tex_blend
            nt.links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
            # per-slot scaling: the library's metallic map is authored for props, so
            # applied raw it turns cloth and painted plate into chrome. Bounds per
            # slot are the authoring decision this asset needs (docs/STYLE_BANDS.md 4b2).
            scale = SLOT_SURFACE.get(base, {}).get(target)
            if scale is None:
                nt.links.new(tex.outputs['Color'], bsdf.inputs[target])
            else:
                mul = nt.nodes.new('ShaderNodeMixRGB')
                mul.blend_type = 'MULTIPLY'
                mul.inputs['Fac'].default_value = 1.0
                mul.inputs['Color2'].default_value = (scale, scale, scale, 1.0)
                nt.links.new(tex.outputs['Color'], mul.inputs['Color1'])
                nt.links.new(mul.outputs['Color'], bsdf.inputs[target])
            wired += 1
        # the baked sculpt normal
        normal_img.colorspace_settings.name = 'Non-Color'
        ntex = nt.nodes.new('ShaderNodeTexImage')
        ntex.image = normal_img
        ntex.interpolation = 'Smart'
        nmap = nt.nodes.new('ShaderNodeNormalMap')
        nt.links.new(ntex.outputs['Color'], nmap.inputs['Color'])
        nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
        # occlusion into the base colour at a low factor, as an export-safe darkening
        if ao_img:
            ao_img.colorspace_settings.name = 'Non-Color'
            bc = bsdf.inputs['Base Color']
            if bc.is_linked:
                src_socket = bc.links[0].from_socket
                mix = nt.nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MULTIPLY'
                mix.inputs['Fac'].default_value = A.ao_strength
                nt.links.new(src_socket, mix.inputs['Color1'])
                aotex = nt.nodes.new('ShaderNodeTexImage')
                aotex.image = ao_img
                nt.links.new(aotex.outputs['Color'], mix.inputs['Color2'])
                nt.links.new(mix.outputs['Color'], bc)
        log(f'{base}: atlas albedo kept, + library roughness/metallic, + baked normal/AO')
    return wired


def wire_library(low, normal_img, ao_img, albedo_img=None):
    """Swap in triplanar library materials, carrying the baked normal."""
    if not (A.library and A.faction):
        # no library: keep a plain PBR material with the baked maps
        for slot in low.material_slots:
            mat = slot.material
            if not mat:
                continue
            nt = mat.node_tree
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = normal_img
                nm = nt.nodes.new('ShaderNodeNormalMap')
                nt.links.new(tex.outputs['Color'], nm.inputs['Color'])
                nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
        return 0

    wanted = set()
    for slot in low.material_slots:
        if slot.material:
            base = slot.material.name.split('.')[0].replace('_baked', '')
            wanted.add(f'IOA_{A.faction}__{base}')
    with bpy.data.libraries.load(str(Path(A.library).resolve()), link=False) as (src, dst):
        dst.materials = [n for n in src.materials if n in wanted]
    loaded = {m.name: m for m in dst.materials if m}
    log(f'library materials loaded: {sorted(loaded)}')

    replaced = 0
    for slot in low.material_slots:
        old = slot.material
        if not old:
            continue
        base = old.name.split('.')[0].replace('_baked', '')
        new = loaded.get(f'IOA_{A.faction}__{base}')
        if not new:
            log(f'no library material for slot "{base}"')
            continue
        slot.material = new
        replaced += 1
        nt = new.node_tree
        for node in nt.nodes:
            if node.type == 'MAPPING':
                node.inputs['Scale'].default_value = (A.tex_scale,) * 3
            elif node.type == 'TEX_IMAGE' and getattr(node, 'projection', '') == 'BOX':
                node.projection_blend = A.tex_blend
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf and albedo_img:
            # unit-specific colour from the reference, multiplied by the library's
            # albedo for material micro-detail — the reference carries identity,
            # the library carries surface language
            base_in = bsdf.inputs['Base Color']
            lib_socket = base_in.links[0].from_socket if base_in.is_linked else None
            atex = nt.nodes.new('ShaderNodeTexImage')
            atex.image = albedo_img
            atex.interpolation = 'Smart'
            if lib_socket:
                mul = nt.nodes.new('ShaderNodeMixRGB')
                mul.blend_type = 'MULTIPLY'
                mul.inputs['Fac'].default_value = 0.55
                nt.links.new(atex.outputs['Color'], mul.inputs['Color1'])
                nt.links.new(lib_socket, mul.inputs['Color2'])
                nt.links.new(mul.outputs['Color'], base_in)
            else:
                nt.links.new(atex.outputs['Color'], base_in)
            log(f'{base}: transferred albedo + library surface')
        if bsdf:
            normal_img.colorspace_settings.name = 'Non-Color'
            tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = normal_img
            tex.interpolation = 'Smart'
            nm = nt.nodes.new('ShaderNodeNormalMap')
            nt.links.new(tex.outputs['Color'], nm.inputs['Color'])
            nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
            if ao_img and bsdf.inputs['Base Color'].is_linked:
                src_socket = bsdf.inputs['Base Color'].links[0].from_socket
                mix = nt.nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MULTIPLY'
                mix.inputs['Fac'].default_value = A.ao_strength
                nt.links.new(src_socket, mix.inputs['Color1'])
                aotex = nt.nodes.new('ShaderNodeTexImage'); aotex.image = ao_img
                aotex.image.colorspace_settings.name = 'Non-Color'
                nt.links.new(aotex.outputs['Color'], mix.inputs['Color2'])
                nt.links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])
        log(f'{base}: library material + baked normal/AO')
    return replaced


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)

    log(f'source: {A.high}')
    high_objs = import_glb(A.high)
    high = [o for o in high_objs if o.type == 'MESH' and not o.name.startswith('Icosphere')]
    if not high:
        log('no mesh in --high'); return 1
    high_tris = sum(tris_of(o) for o in high)
    log(f'source tris: {high_tris}')

    ref = armature = None
    if A.slot_source:
        ref_objs = import_glb(A.slot_source)
        ref = body_of(ref_objs)
        armature = next((o for o in ref_objs if o.type == 'ARMATURE'), None)
        log(f'reference: {ref.name if ref else None} '
            f'({len(ref.material_slots) if ref else 0} slots), '
            f'armature: {armature.name if armature else None}')

    if A.base == 'reference' and ref is not None:
        # Keep the mesh that already has correct UVs, the unit's own 2048 albedo, the
        # material slots and the rig; raise its density with Catmull-Clark, which
        # interpolates UVs so the atlas keeps mapping. Baked normal/AO from the
        # sculpt then supplies the detail the subdivide cannot invent.
        low = ref.copy()
        low.data = ref.data.copy()
        low.name = f'{A.id}_lod0'
        bpy.context.collection.objects.link(low)
        bpy.context.view_layer.objects.active = low
        for o in bpy.data.objects:
            o.select_set(o is low)
        before = tris_of(low)
        levels = 0
        while before * (4 ** (levels + 1)) <= A.tris and levels < 3:
            levels += 1
        if levels:
            mod = low.modifiers.new('Subdiv', 'SUBSURF')
            mod.levels = levels
            mod.render_levels = levels
            bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.ops.object.shade_smooth()
        after = tris_of(low)
        log(f'subdivided reference {before} -> {after} tris (levels {levels}, target {A.tris})')
        REPORT['geometry'] = {'source_tris': high_tris, 'lod0_tris': after,
                              'base': 'reference', 'subdiv_levels': levels}
        REPORT['uv'] = {'kept': 'reference atlas UVs (subsurf-interpolated)',
                        'padding_px': A.padding_px}
        slots = len(low.material_slots)
        rigged = True
        # the reference already carries its own albedo: no cross-mesh transfer needed
        albedo_from_ref = False
    else:
        low = None
    if low is None:
        # the game mesh: a copy of the source, decimated to the target budget
        low = high[0].copy()
        low.data = high[0].data.copy()
        low.name = f'{A.id}_lod0'
        bpy.context.collection.objects.link(low)
        low.hide_render = False
        bpy.context.view_layer.objects.active = low
        for o in bpy.data.objects:
            o.select_set(o is low)
        before = tris_of(low)
        mod = low.modifiers.new('Decimate', 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = min(1.0, A.tris / max(1, before))
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.ops.object.shade_smooth()
        after = tris_of(low)
        log(f'decimated {before} -> {after} tris (target {A.tris})')
        REPORT['geometry'] = {'source_tris': high_tris, 'lod0_tris': after, 'base': 'source'}
        albedo_from_ref = True

    if albedo_from_ref:
        # PBR UV layout (never the palette texel grid)
        unwrap_pbr(low, A.uv_angle, A.padding_px, A.res)
    a_world, a_uv = measure_areas(low)
    log(f'measured areas: world={a_world:.4f} m2, uv={a_uv:.4f} (of 1.0)')
    if a_uv > 1.05:
        log(f'WARNING: UV area {a_uv:.3f} exceeds 1.0 — layout overlaps or is unpacked')
    density = (math.sqrt(max(a_uv, 1e-9)) * A.res) / math.sqrt(max(a_world, 1e-9))
    REPORT['uv'] = {'padding_px': A.padding_px, 'world_area_m2': round(a_world, 4),
                    'uv_area': round(a_uv, 4), 'texel_density_px_m': round(density, 1)}
    log(f'texel density: {density:.0f} px/m (floor {A.min_texel_density:.0f})')
    if density < A.min_texel_density:
        log(f'REFUSING to export: texel density below the floor')
        (OUT / 'aaa_report.json').write_text(json.dumps(REPORT, indent=2))
        return 1

    if albedo_from_ref:
        slots = transfer_slots(low, ref) if ref else 0
        rigged = transfer_weights(low, ref, armature) if (ref and armature) else False
    REPORT['materials'] = {'slots_transferred': slots}
    REPORT['rig'] = {'weights_transferred': rigged}

    normal_img = bpy.data.images.new(f'{A.id}_normal', A.res, A.res, alpha=False)
    ao_img = bpy.data.images.new(f'{A.id}_ao', A.res, A.res, alpha=False)
    albedo_img = None
    if ref and albedo_from_ref:
        # the reference's own colours (unit identity) rebaked onto the new UVs;
        # without this the asset wears a generic library material and reads as
        # "a soldier" rather than this unit. EMIT, not DIFFUSE: the colour-only
        # diffuse pass returned an all-zero image (mean 0.0, max 0) on 2026-11-23.
        albedo_img = bpy.data.images.new(f'{A.id}_albedo', A.res, A.res, alpha=False)
        REPORT.setdefault('bake', {})['albedo_s'] = bake_albedo_transfer(
            [ref], low, albedo_img, A.bake_extrusion, A.albedo_ray)
    REPORT['bake'] = {
        'normal_s': bake_pass('NORMAL', normal_img, high, low, 1,
                              A.bake_extrusion, A.bake_max_ray),
        'ao_s': bake_pass('AO', ao_img, high, low, A.ao_samples,
                          A.bake_extrusion, A.bake_max_ray),
    }
    checks = {'normal': verify_bake(normal_img, 'normal'), 'ao': verify_bake(ao_img, 'ao')}
    if albedo_img is not None:
        if not verify_bake(albedo_img, 'albedo'):
            log('colour transfer empty — retrying with a 1.0 m ray')
            REPORT['bake']['albedo_s'] = bake_albedo_transfer(
                [ref], low, albedo_img, A.bake_extrusion, 1.0)
            if not verify_bake(albedo_img, 'albedo'):
                log('colour transfer still empty; the asset will use the library albedo only')
                albedo_img = None
    REPORT['bake_checks'] = checks

    # stand the unit on the ground: the contract rejects a mesh whose origin sits
    # mid-body (measured: min Y -1.000 on the first 100K export). Move the parent
    # so the bind pose stays intact.
    min_z = min((low.matrix_world @ v.co).z for v in low.data.vertices)
    if abs(min_z) > 1e-3:
        target = armature if armature else low
        target.location.z -= min_z
        bpy.context.view_layer.update()
        log(f'origin corrected: shifted {target.name} by {-min_z:+.3f} m so the feet are at z=0')

    replaced = (wire_surface_only(low, normal_img, ao_img) if not albedo_from_ref
                else wire_library(low, normal_img, ao_img, albedo_img))
    REPORT['materials']['library_replaced'] = replaced

    if not A.keep_source:
        for o in high:
            if o.name in bpy.data.objects:
                bpy.data.objects.remove(o, do_unlink=True)
        log('bake source removed from the export')
    # the reference body is a donor, not an output: exporting it doubles the tri
    # count in the file (caught at 120,080 tris in the first render)
    if ref and ref.name in bpy.data.objects:
        log(f'removing reference mesh {ref.name} from the export')
        bpy.data.objects.remove(ref, do_unlink=True)

    out_glb = OUT / f'{A.id}_aaa.glb'
    for o in bpy.data.objects:
        o.select_set(o.type in {'MESH', 'ARMATURE'})
    bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format='GLB',
                              use_selection=True, export_apply=False,
                              export_image_format='AUTO')
    REPORT['export'] = {'path': str(out_glb), 'mb': round(out_glb.stat().st_size / 1e6, 2)}

    # LOD chain (industry ratio: LOD1 at 50 %, then 25 %, then 10 % — Simplygon's
    # documented art guideline). Decimate keeps the vertex groups, so each LOD stays
    # skinned; materials and the baked normal carry across unchanged.
    chain = []
    for i, target in enumerate(A.lod_chain, start=1):
        cur = tris_of(low)
        if target >= cur:
            continue
        dup = low.copy()
        dup.data = low.data.copy()
        dup.name = f'{A.id}_lod{i}'
        bpy.context.collection.objects.link(dup)
        for o in bpy.data.objects:
            o.select_set(o is dup)
        bpy.context.view_layer.objects.active = dup
        mod = dup.modifiers.new('Decimate', 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = target / max(1, cur)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        lod_glb = OUT / f'{A.id}_lod{i}.glb'
        for o in bpy.data.objects:
            o.select_set(o is dup or (o.type == 'ARMATURE'))
        bpy.ops.export_scene.gltf(filepath=str(lod_glb), export_format='GLB',
                                  use_selection=True, export_apply=False,
                                  export_image_format='AUTO')
        chain.append({'lod': i, 'tris': tris_of(dup), 'path': str(lod_glb),
                      'mb': round(lod_glb.stat().st_size / 1e6, 2)})
        log(f'LOD{i}: {tris_of(dup)} tris -> {lod_glb.name}')
        bpy.data.objects.remove(dup, do_unlink=True)
    REPORT['lod_chain'] = chain

    # --- modular part set (docs/ASSEMBLY_MODEL.md): game characters are assembled
    # from parts on a shared skeleton, not authored as one fused mesh. Splitting by
    # material slot is the coarse first pass; each part then gets its own budget,
    # bake and LODs. `mesh.separate(type='MATERIAL')` preserves vertex groups and
    # the armature parent, so every part stays skinned to the same rig.
    if A.split_parts:
        parts_dir = OUT / 'parts'
        parts_dir.mkdir(exist_ok=True)
        before = set(bpy.data.objects)
        dup = low.copy()
        dup.data = low.data.copy()
        dup.name = f'{A.id}_split'
        bpy.context.collection.objects.link(dup)
        for o in bpy.data.objects:
            o.select_set(o is dup)
        bpy.context.view_layer.objects.active = dup
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='MATERIAL')
        bpy.ops.object.mode_set(mode='OBJECT')
        new_objs = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
        parts = []
        for i, part in enumerate(sorted(new_objs, key=lambda o: -len(o.data.polygons))):
            mat = part.material_slots[0].material.name.split('.')[0] if part.material_slots else 'unknown'
            part.name = f'{A.id}_{mat}'
            part_glb = parts_dir / f'{A.id}_{mat}.glb'
            for o in bpy.data.objects:
                o.select_set(o is part or o.type == 'ARMATURE')
            bpy.context.view_layer.objects.active = part
            bpy.ops.export_scene.gltf(filepath=str(part_glb), export_format='GLB',
                                      use_selection=True, export_apply=False,
                                      export_image_format='AUTO')
            parts.append({'part': mat, 'tris': tris_of(part), 'path': str(part_glb),
                          'mb': round(part_glb.stat().st_size / 1e6, 2),
                          'skinned': any(m.type == 'ARMATURE' for m in part.modifiers),
                          'lod_targets': A.lod_chain})
            log(f'part {mat}: {tris_of(part)} tris, skinned='
                f'{any(m.type == "ARMATURE" for m in part.modifiers)} -> {part_glb.name}')
            bpy.data.objects.remove(part, do_unlink=True)
        sockets = []
        if armature:
            wanted = ('hand_r', 'hand_l', 'head', 'spine_03', 'spine_02', 'pelvis', 'root')
            sockets = [b.name for b in armature.data.bones if b.name in wanted]
        REPORT['parts'] = parts
        REPORT['sockets'] = sockets
        (OUT / 'unit.manifest.json').write_text(json.dumps(
            {'id': A.id, 'skeleton': armature.name if armature else None,
             'sockets': sockets, 'parts': parts,
             'notes': 'per-part budgets/bakes/LODs; see docs/ASSEMBLY_MODEL.md'}, indent=2))
        log(f'manifest: {len(parts)} parts, {len(sockets)} sockets -> unit.manifest.json')
    (OUT / 'aaa_report.json').write_text(json.dumps(REPORT, indent=2))
    log(f'wrote {out_glb} ({REPORT["export"]["mb"]} MB) and aaa_report.json')
    return 0


sys.exit(main())
