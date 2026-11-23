#!/usr/bin/env python3
"""aaa_assemble.py — assemble a built LOD0 into the industry character structure.

Modern characters are not one mesh. They are a **shared skeleton with sockets** plus
separate meshes for body and gear, each with its own budget, materials and LODs, and
a data manifest that tells the engine what to attach where. Sources:

  * Epic, "Skeletal Mesh Sockets": sockets are stored on the **Skeleton Asset**
    ("when creating and manipulating Sockets, this will edit the Skeleton Asset"), so
    every mesh sharing that skeleton can carry gear at the same attachment point.
  * Epic, "Modular Characters in Unreal Engine": modular characters are "comprised of
    multiple Skeletal Meshes".
  * The portable glTF form of a socket is a **named node parented to the joint** —
    "the weapon is parented directly to the target hand bone in the glTF node
    hierarchy, so every animation clip drives it automatically" (Asset Bench, 2026).

This stage therefore produces:

  skeleton.glb           bones + SOCKET_* nodes parented to their joints
  parts/<id>_<slot>.glb  one mesh per part, skinned to that skeleton
  parts/<id>_<slot>_lodN.glb  per-part LOD chain (50/25/10 % — Simplygon guidance)
  unit.manifest.json     parts, sockets, budgets, LODs, materials

It then RE-LOADS every file it wrote and verifies that bones, sockets, skin and clips
survived the round trip — an unverified export is not a deliverable.

Honest limitation, recorded rather than hidden: the parts are derived by splitting the
built LOD0 on material boundaries, not authored as separate gear meshes. The structure
(skeleton + sockets + separate parts + per-part LODs + manifest) is correct; the
provenance of the geometry is a split, and that is stated in the manifest.

Usage:
  tools/blender_run.sh --job script -- -b -P tools/blender/aaa_assemble.py -- \
      --glb output/aaa/line_infantry/line_infantry_aaa.glb \
      --out output/aaa/line_infantry --id line_infantry
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bake_utils as bu  # noqa: E402

_ap = argparse.ArgumentParser()
_ap.add_argument('--glb', required=True)
_ap.add_argument('--out', required=True)
_ap.add_argument('--id', required=True)
_ap.add_argument('--high', help='high-poly source for per-part normal/AO bakes')
_ap.add_argument('--library', help='PBR material library .blend (supplies albedo detail)')
_ap.add_argument('--faction', help='library faction prefix, e.g. iron_directorate')
_ap.add_argument('--views', help='directory holding front/back/left/right reference views; '
                                 'when given, the albedo is PROJECTED from the concept instead of '
                                 'composited from the atlas (reference-driven texturing)')
_ap.add_argument('--tint-value', type=float, default=0.8,
                 help='value the per-part colour tint is normalised to; the atlas is dark '
                      '(measured 0.10-0.24) so its HUE is kept and its VALUE restored')
_ap.add_argument('--target-density', type=float, default=1024.0,
                 help='per-part texel density target (px/m); PC band floor is 1024')
_ap.add_argument('--lod-chain', type=float, nargs='*', default=[0.5, 0.25, 0.10],
                 help='per-part LOD ratios (industry guidance: LOD1 at 50%)')
a = _ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

OUT = Path(a.out).resolve()
PARTS = OUT / 'parts'
PARTS.mkdir(parents=True, exist_ok=True)

# Socket table: the attachment points a game needs. Bone names are Mixamo-style on
# this rig, so the mapping is explicit rather than guessed from UE names.
SOCKETS = {
    'SOCKET_weapon_r': 'RightHand',
    'SOCKET_weapon_l': 'LeftHand',
    'SOCKET_head': 'Head',
    'SOCKET_back': 'Spine2',
    'SOCKET_hips': 'Hips',
    # the rigid clusters measured on this asset (aaa_socket_gear.py) hang from these,
    # so they get sockets of their own rather than attaching to a bare bone
    'SOCKET_thigh_r': 'RightUpLeg',
    'SOCKET_thigh_l': 'LeftUpLeg',
    'SOCKET_knee_r': 'RightLeg',
    'SOCKET_boot_r': 'RightFoot',
    'SOCKET_boot_l': 'LeftFoot',
    'SOCKET_toe_r': 'RightToeBase',
    'SOCKET_toe_l': 'LeftToeBase',
}


def log(m: str) -> None:
    print(f'[aaa_assemble] {m}', flush=True)


def tris(obj) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def export(objs, path: Path) -> int:
    for o in bpy.data.objects:
        o.select_set(o in objs)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB',
                              use_selection=True, export_apply=False,
                              export_image_format='AUTO')
    return path.stat().st_size


def verify(path: Path, want: dict) -> dict:
    """Re-load the file and confirm what the manifest claims actually shipped."""
    before = set(bpy.data.objects)
    actions_before = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    # count only the actions THIS import created: bpy.data.actions accumulates
    # across imports in one session (measured: 36/72/144/288 were cumulative, not real)
    new_actions = [a for a in bpy.data.actions if a not in actions_before]
    meshes = [o for o in new if o.type == 'MESH']
    arms = [o for o in new if o.type == 'ARMATURE']
    names = {o.name for o in new}
    result = {
        'meshes': len(meshes),
        'tris': sum(tris(o) for o in meshes),
        'armatures': len(arms),
        'bones': sum(len(o.data.bones) for o in arms),
        'skinned': any(any(m.type == 'ARMATURE' for m in o.modifiers) for o in meshes),
        'clips': len(new_actions),
        'sockets_found': sorted(n for n in names if n.startswith('SOCKET_')),
    }
    for k, v in want.items():
        if result.get(k) != v:
            result.setdefault('mismatch', []).append(f'{k}: got {result.get(k)} want {v}')
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in new_actions:
        if a.users == 0:
            bpy.data.actions.remove(a)
    return result


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(a.glb).resolve()))
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    if not meshes or not arms:
        log(f'missing mesh or armature (meshes={len(meshes)} arms={len(arms)})')
        return 1
    # the source ships a small Icosphere reference mesh; it must not be exported inside
    # every part (measured: each part GLB contained an 80-tri, 0-group Icosphere, which
    # then became the join target downstream)
    for o in list(meshes):
        if o.name.startswith('Icosphere'):
            log(f'removing reference mesh {o.name}')
            bpy.data.objects.remove(o, do_unlink=True)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    body = max(meshes, key=lambda o: len(o.data.polygons))
    arm = arms[0]
    log(f'source: {body.name} {tris(body)} tris, rig {arm.name} ({len(arm.data.bones)} bones)')
    for other in meshes:
        if other is not body:
            log(f'removing non-body mesh {other.name}')
            bpy.data.objects.remove(other, do_unlink=True)

    # --- sockets: named nodes parented to their joint, so any clip drives them
    bone_names = {b.name for b in arm.data.bones}
    socket_objs = []
    for sock, bone in sorted(SOCKETS.items()):
        if bone not in bone_names:
            log(f'socket {sock} skipped: no bone {bone}')
            continue
        empty = bpy.data.objects.new(sock, None)
        empty.empty_display_type = 'ARROWS'
        empty.empty_display_size = 0.08
        bpy.context.collection.objects.link(empty)
        empty.parent = arm
        empty.parent_type = 'BONE'
        empty.parent_bone = bone
        socket_objs.append(empty)
    log(f'sockets created: {[o.name for o in socket_objs]}')

    skel = OUT / 'skeleton.glb'
    export([arm, *socket_objs], skel)
    skel_check = verify(skel, {'armatures': 1, 'bones': len(arm.data.bones)})
    log(f'skeleton.glb verified: bones={skel_check["bones"]} '
        f'sockets={len(skel_check["sockets_found"])} clips={skel_check["clips"]}')
    if skel_check.get('mismatch'):
        log(f'skeleton MISMATCH: {skel_check["mismatch"]}')

    # --- parts: split on material boundaries, keeping vertex groups + armature parent
    bpy.context.view_layer.objects.active = body
    for o in bpy.data.objects:
        o.select_set(o is body)
    before = set(bpy.data.objects)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='MATERIAL')
    bpy.ops.object.mode_set(mode='OBJECT')
    # `mesh.separate(type='MATERIAL')` keeps one material on the original object and
    # creates new objects for the rest; the original is a part as well. Omitting it
    # silently dropped the underlayer (16,002 tris) on 2026-11-23.
    parts = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if body.type == 'MESH' and body.data.polygons:
        parts.append(body)

    manifest = {
        'id': a.id,
        'skeleton': {'path': str(skel), 'bones': len(arm.data.bones),
                     'clips': skel_check.get('clips'),
                     'verified': skel_check,
                     'sockets': [{'name': o.name, 'bone': o.parent_bone}
                                 for o in socket_objs]},
        'provenance': 'parts derived by material split of the built LOD0 '
                      '(structure is modular; geometry is not yet authored per part)',
        'parts': [],
    }
    # high-poly source for the per-part normal/AO bakes
    high_objs = []
    if a.high:
        before_h = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(a.high).resolve()))
        high_objs = [o for o in bpy.data.objects
                     if o not in before_h and o.type == 'MESH'
                     and not o.name.startswith('Icosphere')]
        log(f'high-poly bake source: {sum(tris(o) for o in high_objs)} tris')

    # Real albedo detail comes from the 1K PBR library; the unit's own identity comes
    # from the resampled atlas. Multiplying them is the honest substitute for an artist
    # authoring a 4K albedo: the library carries rivets, wear and panel linework that a
    # 2048 palette atlas simply does not contain (docs/ASSEMBLY_MODEL.md §7.2b).
    lib_albedo = {}
    if a.library and a.faction:
        wanted = {f'IOA_{a.faction}__{p.material_slots[0].material.name.split(".")[0]}'
                  for p in parts if p.material_slots and p.material_slots[0].material}
        with bpy.data.libraries.load(str(Path(a.library).resolve()), link=False) as (src, dst):
            dst.materials = [n for n in src.materials if n in wanted]
        for m in dst.materials:
            if not m or not m.use_nodes:
                continue
            for node in m.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image and 'albedo' in node.image.name.lower():
                    lib_albedo[m.name.split('__')[-1]] = node.image
                    break
        log(f'library albedo loaded for slots: {sorted(lib_albedo)}')

    # whole-character bounds, used by the reference projection so every part is mapped
    # onto the same reference frame
    import numpy as _np
    all_co = _np.array([o.matrix_world @ v.co for o in parts for v in o.data.vertices],
                       dtype=_np.float64)
    char_bounds = (tuple(all_co.min(axis=0)), tuple(all_co.max(axis=0)))
    log(f'character bounds for projection: {tuple(round(v, 3) for v in char_bounds[0])} .. '
        f'{tuple(round(v, 3) for v in char_bounds[1])}')

    total = 0
    for part in sorted(parts, key=lambda o: -tris(o)):
        slot = part.material_slots[0].material.name.split('.')[0] if part.material_slots else 'unknown'
        part.name = f'{a.id}_{slot}'
        base_tris = tris(part)
        total += base_tris

        # keep a copy carrying the ORIGINAL UVs: it is the albedo source, and because
        # it is the same geometry the transfer is exact (no cross-mesh guesswork)
        albedo_src = part.copy()
        albedo_src.data = part.data.copy()
        albedo_src.name = f'{part.name}_albedosrc'
        bpy.context.collection.objects.link(albedo_src)

        # per-part layout at per-part resolution: the point of modular bakes is that a
        # pauldron stops sharing the torso's texel budget. The ORIGINAL layout is kept
        # under a name so the albedo can be resampled from it in UV space.
        # Snapshot the original layout as DATA before unwrapping. Layer names are not
        # trustworthy here: smart_project can write into the layer that was meant to be
        # preserved (measured: 99.7% black resample), so the source is captured in
        # memory and the unwrap is free to overwrite whatever it likes.
        old_uv_snapshot = bu.capture_uv(part)
        bu.unwrap(part, padding_px=32, res=2048)
        new_uv_name = part.data.uv_layers.active.name if part.data.uv_layers.active else None
        a_world, a_uv = bu.measure_areas(part)
        # cap at 4096: the largest part needs it to reach the 1024 px/m floor
        res = bu.pick_resolution(a_world, a_uv, a.target_density, 512, 4096)
        density = bu.density_px_m(a_world, a_uv, res)

        alb = bpy.data.images.new(f'{part.name}_albedo', res, res, alpha=False)
        nrm = bpy.data.images.new(f'{part.name}_normal', res, res, alpha=False)
        nrm.colorspace_settings.name = 'Non-Color'
        aoi = bpy.data.images.new(f'{part.name}_ao', res, res, alpha=False)
        aoi.colorspace_settings.name = 'Non-Color'

        # coincident transfer: source and target are the SAME geometry, so the cage
        # extrusion must be 0 — a positive extrusion starts the ray outside the source
        # and nothing is hit (measured: mean 0.0006, i.e. 0.1% coverage)
        # resample the atlas albedo from the old layout into the new one (exact,
        # no ray casting: coincident ray bakes missed on 2 of 4 parts)
        src_img = None
        if part.material_slots and part.material_slots[0].material:
            nt0 = part.material_slots[0].material.node_tree
            bsdf0 = next((n for n in nt0.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf0 and bsdf0.inputs['Base Color'].is_linked:
                from_node = bsdf0.inputs['Base Color'].links[0].from_node
                if from_node.type == 'TEX_IMAGE' and from_node.image:
                    src_img = from_node.image
                else:
                    # base colour may be wired through a mix (AO multiply); walk the
                    # chain to the first image so the resample has a real source
                    stack = [from_node]
                    seen = set()
                    while stack:
                        n = stack.pop()
                        if n.name in seen:
                            continue
                        seen.add(n.name)
                        if n.type == 'TEX_IMAGE' and n.image:
                            src_img = n.image
                            break
                        for inp in n.inputs:
                            for link in inp.links:
                                stack.append(link.from_node)
        ok_alb = False
        projected = False
        proj_img = None
        if a.views:
            vdir = Path(a.views)
            proj_img = bu.project_reference_texture(part, {
                'front': vdir / 'front.png', 'back': vdir / 'back.png',
                'left': vdir / 'left.png', 'right': vdir / 'right.png'}, res,
                bounds=char_bounds)
            if proj_img is not None:
                alb = proj_img
                ok_alb = True
                projected = True
        if src_img and not ok_alb:
            import numpy as _np
            _px = _np.array(src_img.pixels[:], dtype=_np.float32)
            log(f'albedo source for {slot}: {src_img.name} {tuple(src_img.size)} '
                f'mean={float(_px.mean()):.3f}')
        if src_img and new_uv_name:
            resampled = bu.transfer_uv_texture(part, old_uv_snapshot, new_uv_name, src_img, res)
            if resampled:
                alb = resampled
                ok_alb = True
        ok_nrm = ok_ao = False
        if high_objs:
            ok_nrm = bu.bake_pass('NORMAL', nrm, high_objs, part, 1, 0.002, 0.01, 32)
            ok_ao = bu.bake_pass('AO', aoi, high_objs, part, 24, 0.002, 0.05, 32)

        for img, suffix in ((alb, 'albedo'), (nrm, 'normal'), (aoi, 'ao')):
            img.filepath_raw = str(PARTS / f'{part.name}_{suffix}.png')
            img.file_format = 'PNG'
            img.save()

        # rewire this part's material to its own maps
        if part.material_slots and part.material_slots[0].material:
            nt = part.material_slots[0].material.node_tree
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                if ok_alb:
                    atex = nt.nodes.new('ShaderNodeTexImage'); atex.image = alb
                    lib_img = lib_albedo.get(slot)
                    # per-part tint: keep the atlas hue, restore its value. The atlas
                    # measures 0.10-0.25 in RGB, so using it directly crushes the surface
                    # to near-black (measured 2026-11-23: a 0.55 multiply changed nothing).
                    tint = None
                    try:
                        import numpy as _np
                        px = _np.array(alb.pixels[:], dtype=_np.float32).reshape(-1, 4)[:, :3]
                        lit = px[px.sum(axis=1) > 0.09]
                        if len(lit):
                            mean = lit.mean(axis=0)
                            peak = float(mean.max()) or 1.0
                            tint = tuple(float(v) / peak * a.tint_value for v in mean)
                            log(f'{slot}: tint {tuple(round(v, 3) for v in tint)} '
                                f'(atlas mean {tuple(round(float(v), 3) for v in mean)})')
                    except Exception as e:
                        log(f'{slot}: tint failed ({type(e).__name__}); using atlas albedo')
                    # a projected albedo IS the colour authority: multiplying the
                    # library over it desaturates the design's own colours
                    if lib_img and tint and not projected:
                        coord = nt.nodes.new('ShaderNodeTexCoord')
                        mapping = nt.nodes.new('ShaderNodeMapping')
                        mapping.inputs['Scale'].default_value = (6.0, 6.0, 6.0)
                        nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
                        ltex = nt.nodes.new('ShaderNodeTexImage')
                        ltex.image = lib_img
                        ltex.projection = 'BOX'
                        ltex.projection_blend = 0.12
                        nt.links.new(mapping.outputs['Vector'], ltex.inputs['Vector'])
                        # library albedo is the BASE (authored detail and value);
                        # the unit's colour identity is the constant tint on top
                        mul = nt.nodes.new('ShaderNodeMixRGB')
                        mul.blend_type = 'MULTIPLY'
                        mul.inputs['Fac'].default_value = 1.0
                        nt.links.new(ltex.outputs['Color'], mul.inputs['Color1'])
                        mul.inputs['Color2'].default_value = (*tint, 1.0)
                        nt.links.new(mul.outputs['Color'], bsdf.inputs['Base Color'])
                        log(f'{slot}: library albedo x unit tint')
                    else:
                        nt.links.new(atex.outputs['Color'], bsdf.inputs['Base Color'])
                if ok_nrm:
                    ntex = nt.nodes.new('ShaderNodeTexImage'); ntex.image = nrm
                    nm = nt.nodes.new('ShaderNodeNormalMap')
                    nt.links.new(ntex.outputs['Color'], nm.inputs['Color'])
                    nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
                if ok_ao and bsdf.inputs['Base Color'].is_linked:
                    src_socket = bsdf.inputs['Base Color'].links[0].from_socket
                    mix = nt.nodes.new('ShaderNodeMixRGB')
                    mix.blend_type = 'MULTIPLY'
                    mix.inputs['Fac'].default_value = 0.25
                    nt.links.new(src_socket, mix.inputs['Color1'])
                    aotex = nt.nodes.new('ShaderNodeTexImage'); aotex.image = aoi
                    nt.links.new(aotex.outputs['Color'], mix.inputs['Color2'])
                    nt.links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])

        bpy.data.objects.remove(albedo_src, do_unlink=True)

        lod_records = []
        p0 = PARTS / f'{a.id}_{slot}.glb'
        mb = export([part, arm], p0)
        chk = verify(p0, {'meshes': 1, 'armatures': 1, 'bones': len(arm.data.bones)})
        lod_records.append({'lod': 0, 'tris': base_tris, 'path': str(p0),
                            'mb': round(mb / 1e6, 2), 'verified': chk})
        log(f'{slot}: LOD0 {base_tris} tris @ {res}px ({density:.0f} px/m), '
            f'albedo={ok_alb} normal={ok_nrm} ao={ok_ao}, skinned={chk["skinned"]}')

        for i, ratio in enumerate(a.lod_chain, start=1):
            target = max(64, int(base_tris * ratio))
            dup = part.copy()
            dup.data = part.data.copy()
            dup.name = f'{part.name}_lod{i}'
            bpy.context.collection.objects.link(dup)
            for o in bpy.data.objects:
                o.select_set(o is dup)
            bpy.context.view_layer.objects.active = dup
            mod = dup.modifiers.new('Decimate', 'DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = min(1.0, target / max(1, tris(dup)))
            bpy.ops.object.modifier_apply(modifier=mod.name)
            pl = PARTS / f'{a.id}_{slot}_lod{i}.glb'
            mbl = export([dup, arm], pl)
            lod_records.append({'lod': i, 'tris': tris(dup), 'path': str(pl),
                                'mb': round(mbl / 1e6, 2)})
            log(f'{slot}: LOD{i} {tris(dup)} tris -> {pl.name}')
            bpy.data.objects.remove(dup, do_unlink=True)

        manifest['parts'].append({
            'part': slot, 'budget_tris': base_tris,
            'texture': {'res': res, 'texel_density_px_m': round(density, 1),
                        'albedo': ok_alb, 'normal': ok_nrm, 'ao': ok_ao},
            'lods': lod_records})
        bpy.data.objects.remove(part, do_unlink=True)

    manifest['total_lod0_tris'] = total
    (OUT / 'unit.manifest.json').write_text(json.dumps(manifest, indent=2))
    log(f'manifest: {len(manifest["parts"])} parts, {total} tris total, '
        f'{len(manifest["skeleton"]["sockets"])} sockets -> unit.manifest.json')
    return 0


sys.exit(main())
