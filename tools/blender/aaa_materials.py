#!/usr/bin/env python3
"""aaa_materials.py — swap an AAA game mesh onto the real PBR library.

Why: the first AAA bake inherited the pixel tier's 256-px palette atlas as its
albedo. The geometry and the baked normal were right; the colour was mush, and
that — not the mesh — is what still read as "old console". For comparison, the
commercial generators ship 4096-px textures (TRELLIS.2's own example export uses
decimation_target = 1,000,000 with 4096 textures), so a 256 atlas is ~256x short.

What this does, per material slot:
  1. find the matching `IOA_<faction>__<slot>` material in the PBR library
  2. replace the slot's material with it (real albedo/roughness/metallic at 1K,
     tiling — so effective texel density is high across the body)
  3. carry the baked normal map from the old material into the new one, so the
     sculpt's surface detail survives the swap
  4. export

No bake, no GPU: this is a material relink and takes seconds.

Usage:
  tools/blender_run.sh --job script -- -b -P tools/blender/aaa_materials.py -- \
      --glb output/aaa/line_infantry/line_infantry_aaa.glb \
      --library assets/materials/grimdark_scifi/grimdark_scifi.blend \
      --faction iron_directorate --out output/aaa/line_infantry/line_infantry_pbr.glb
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

_ap = argparse.ArgumentParser()
_ap.add_argument('--glb', required=True)
_ap.add_argument('--library', required=True)
_ap.add_argument('--faction', required=True)
_ap.add_argument('--out', required=True)
_ap.add_argument('--tex-scale', type=float, default=6.0,
                help='box-projection tiling for a character (library authored at 2.0 for props)')
_ap.add_argument('--tex-blend', type=float, default=0.12,
                help='box-projection blend; high values read as blotches on a small figure')
A = _ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])


def log(m: str) -> None:
    print(f'[aaa_materials] {m}', flush=True)


def find_normal_image(mat) -> bpy.types.Image | None:
    """The baked normal map already wired into this material, if any."""
    if not mat or not mat.use_nodes:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'NORMAL_MAP' and node.inputs['Color'].is_linked:
            src = node.inputs['Color'].links[0].from_node
            if src.type == 'TEX_IMAGE' and src.image:
                return src.image
    return None


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))

    # append the library materials we need (only these; the file holds hundreds)
    body = max((o for o in bpy.data.objects if o.type == 'MESH'),
               key=lambda o: len(o.data.polygons))
    wanted = set()
    for slot in body.material_slots:
        if slot.material:
            base = slot.material.name.split('.')[0].replace('_baked', '')
            wanted.add(f'IOA_{A.faction}__{base}')
    log(f'slots on the mesh: {sorted(s.name for s in body.material_slots)}')
    log(f'looking for: {sorted(wanted)}')

    with bpy.data.libraries.load(str(Path(A.library).resolve()), link=False) as (src, dst):
        dst.materials = [n for n in src.materials if n in wanted]
    loaded = {m.name: m for m in dst.materials if m}
    log(f'loaded from library: {sorted(loaded)}')

    replaced = 0
    for slot in body.material_slots:
        old = slot.material
        if not old:
            continue
        base = old.name.split('.')[0].replace('_baked', '')
        new = loaded.get(f'IOA_{A.faction}__{base}')
        if not new:
            log(f'no library material for slot "{base}" — kept {old.name}')
            continue
        baked = find_normal_image(old)
        slot.material = new
        replaced += 1
        # retune the projection for a ~1.9 m character: the library ships 2.0/0.35
        # for walls and props, which tiles too coarsely and blends into blotches
        for node in new.node_tree.nodes:
            if node.type == 'MAPPING':
                node.inputs['Scale'].default_value = (A.tex_scale,) * 3
            elif node.type == 'TEX_IMAGE' and getattr(node, 'projection', '') == 'BOX':
                node.projection_blend = A.tex_blend
        if baked:
            # A normal map re-imported from PNG is treated as sRGB unless told
            # otherwise; read as sRGB it produces exactly the mottled, washed-out
            # shading seen in the first library swap (2026-11-23).
            try:
                baked.colorspace_settings.name = 'Non-Color'
            except Exception:
                pass
            nt = new.node_tree
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                tex = nt.nodes.new('ShaderNodeTexImage')
                tex.image = baked
                tex.interpolation = 'Smart'
                nmap = nt.nodes.new('ShaderNodeNormalMap')
                nmap.inputs['Strength'].default_value = 1.0
                nt.links.new(tex.outputs['Color'], nmap.inputs['Color'])
                nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
                log(f'{base}: library material + baked normal')
        else:
            log(f'{base}: library material (no baked normal found)')

    out = Path(A.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    for o in bpy.data.objects:
        o.select_set(o.type in {'MESH', 'ARMATURE'})
    bpy.ops.export_scene.gltf(filepath=str(out), export_format='GLB', use_selection=True,
                              export_apply=False, export_image_format='AUTO')
    log(f'replaced {replaced} material(s); wrote {out} ({out.stat().st_size / 1e6:.1f} MB)')


main()
