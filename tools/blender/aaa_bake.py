#!/usr/bin/env python3
"""aaa_bake.py — turn a high-poly source into a game mesh that reads as AAA.

This is the industry technique the commercial generators sell as "build high poly
and bake it down" (Tripo's own guide), and the one thing our chain was missing:
`palette_3d` sets `normal_map: false` and `build_unit.sh` never calls the bake
tools. Without a baked normal the game mesh can only ever look faceted.

What it does, in order:
  1. import the high-poly source (the raw generative shape) as the bake source
  2. import the game mesh (low-poly, already UV'd + skinned + textured)
  3. bake NORMAL from high to low, through the low mesh's existing UVs
  4. bake AMBIENT OCCLUSION from the high source
  5. multiply the AO into the albedo (export-safe: no reliance on glTF occlusion
     wiring, which is easy to lose on export)
  6. wire the normal map into every material
  7. export a GLB that carries albedo + normal

No retopo here: the low mesh already exists and its UVs are the contract. The
bake transfers surface detail, not topology. Raising the low mesh's triangle
budget is a separate, independent change.

Usage (via the guarded launcher, one GPU job at a time):
  tools/blender_run.sh --job bake -- -b -P tools/blender/aaa_bake.py -- \
      --high output/img23d/line_infantry_mv/front.glb \
      --low  output/img23d/line_infantry_mv/atlas/unit_textured.glb \
      --out  output/aaa/line_infantry --id line_infantry --res 2048
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

_ap = argparse.ArgumentParser()
_ap.add_argument('--high', required=True, help='high-poly bake source (GLB)')
_ap.add_argument('--low', required=True, help='game mesh to receive the bake (GLB)')
_ap.add_argument('--out', required=True)
_ap.add_argument('--id', required=True)
_ap.add_argument('--res', type=int, default=2048, help='bake texture resolution')
_ap.add_argument('--ao-samples', type=int, default=32)
_ap.add_argument('--cage', type=float, default=0.02, help='bake ray extrusion, metres')
_ap.add_argument('--ao-strength', type=float, default=0.35,
                help='AO multiply into albedo (0-1); above ~0.5 it crushes the colour')
A = _ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

OUT = Path(A.out).resolve()
OUT.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f'[aaa_bake] {msg}', flush=True)


def clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: str) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    return [o for o in bpy.data.objects if o not in before and o.type == 'MESH']


def tri_count(objs: list) -> int:
    return sum(len(o.data.loop_triangles) if o.data.loop_triangles else
               sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)


def bake_pass(kind: str, image: bpy.types.Image, high: list, low: list,
              samples: int, cage: float) -> None:
    """Bake one pass from `high` onto `low`'s active UV via selected-to-active."""
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'
    scene.cycles.samples = samples
    # BOTH passes are high->low transfers: the source has no UVs of its own,
    # so a plain AO bake would try to use them and fail.
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = cage
    scene.render.bake.margin = 16
    scene.render.bake.use_clear = True

    for o in bpy.data.objects:
        o.select_set(False)
    for o in high:
        o.select_set(True)
    for o in low:
        o.select_set(True)
    bpy.context.view_layer.objects.active = low[0]

    for mat_slot in low[0].material_slots:
        mat = mat_slot.material
        if not mat:
            continue
        mat.use_nodes = True
        nt = mat.node_tree
        node = nt.nodes.get(f'BAKE_TARGET_{kind}') or nt.nodes.new('ShaderNodeTexImage')
        node.name = f'BAKE_TARGET_{kind}'
        node.image = image
        nt.nodes.active = node

    log(f'baking {kind} at {image.size[0]}px …')
    bpy.ops.object.bake(type=kind)
    image.filepath_raw = str(OUT / f'{A.id}_{kind.lower()}.png')
    image.file_format = 'PNG'
    image.save()
    log(f'baked {kind} -> {image.filepath_raw}')


def main() -> None:
    clear()
    log(f'high: {A.high}')
    high = import_glb(A.high)
    if not high:
        raise SystemExit('no mesh in --high')
    log(f'high tris: {tri_count(high)}')

    log(f'low: {A.low}')
    low_all = import_glb(A.low)
    if not low_all:
        raise SystemExit('no mesh in --low')
    # the export carries a small reference mesh (Icosphere) alongside the body;
    # baking into that is the classic silent failure, so drop it explicitly
    for o in list(low_all):
        if o.name.startswith('Icosphere'):
            log(f'dropping reference mesh {o.name} ({len(o.data.polygons)} faces)')
            low_all.remove(o)
            bpy.data.objects.remove(o, do_unlink=True)
    if not low_all:
        raise SystemExit('only reference meshes in --low')
    # the bake target is the body: most triangles, and it must carry UVs
    low = [max(low_all, key=lambda o: len(o.data.polygons))]
    if not low[0].data.uv_layers:
        raise SystemExit('the game mesh has no UVs — bake needs a UV target')
    if not low[0].material_slots:
        mat = bpy.data.materials.new(f'{A.id}_baked')
        mat.use_nodes = True
        low[0].data.materials.append(mat)
        log('game mesh had no materials; created one')
    log(f'low target: {low[0].name} tris={tri_count(low)} '
        f'materials={len(low[0].material_slots)} uvs={len(low[0].data.uv_layers)}')

    normal_img = bpy.data.images.new(f'{A.id}_normal', A.res, A.res,
                                     alpha=False, float_buffer=False)
    normal_img.colorspace_settings.name = 'Non-Color'
    ao_img = bpy.data.images.new(f'{A.id}_ao', A.res, A.res, alpha=False,
                                 float_buffer=False)
    ao_img.colorspace_settings.name = 'Non-Color'

    bake_pass('NORMAL', normal_img, high, low, samples=1, cage=A.cage)
    bake_pass('AO', ao_img, high, low, samples=A.ao_samples, cage=A.cage)

    # wire normal into every material; multiply AO into the albedo image
    for slot in low[0].material_slots:
        mat = slot.material
        if not mat:
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            continue
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = normal_img
        tex.interpolation = 'Smart'
        nmap = nt.nodes.new('ShaderNodeNormalMap')
        nmap.inputs['Strength'].default_value = 1.0
        nt.links.new(tex.outputs['Color'], nmap.inputs['Color'])
        nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
        # AO into the base colour, via a multiply against whatever feeds it
        base = bsdf.inputs['Base Color']
        if base.is_linked:
            src = base.links[0].from_socket
            mix = nt.nodes.new('ShaderNodeMixRGB')
            mix.blend_type = 'MULTIPLY'
            mix.inputs['Fac'].default_value = A.ao_strength
            nt.links.new(src, mix.inputs['Color1'])
            aotex = nt.nodes.new('ShaderNodeTexImage')
            aotex.image = ao_img
            aotex.image.colorspace_settings.name = 'Non-Color'
            nt.links.new(aotex.outputs['Color'], mix.inputs['Color2'])
            nt.links.new(mix.outputs['Color'], base)
        log(f'material wired: {mat.name}')

    # the bake source must NOT ship: exporting every mesh puts the 400K sculpt in
    # the game file next to the 20K body (caught in the first A/B render)
    for o in list(high):
        if o.name in bpy.data.objects:
            log(f'removing bake source {o.name} from the export')
            bpy.data.objects.remove(o, do_unlink=True)

    out_glb = OUT / f'{A.id}_aaa.glb'
    for o in bpy.data.objects:
        o.select_set(o.type in {'MESH', 'ARMATURE'})  # armature carries the skin + clips
    bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format='GLB',
                              use_selection=True, export_apply=False,
                              export_image_format='AUTO')
    log(f'wrote {out_glb} ({out_glb.stat().st_size / 1e6:.1f} MB)')


main()
