#!/usr/bin/env python3
"""
bake_ao_maps.py — Headless Ambient Occlusion bake for the DoW1 texture-driven pipeline.

Bakes geometry-aware AO into the per-unit atlas UV layout (the UVs that
parametric_unit_generator.py + remap_uvs_to_atlas wrote). Runs on the saved .blend
AFTER generation and BEFORE apply_unit_textures.py rewires materials to the painted
diffuse (the bake needs the original PBR material graph; it adds a temporary active
Image Texture node per material, bakes, then removes it).

The output <unit>_ao.png is consumed by paint_unit_diffuse.py, which multiplies it
into the diffuse (Final = Base x AO + edge/panel overlay) — darkening pauldron
undersides, under-armour folds, and visor crevices for isometric depth.

Usage:
    blender --background --python bake_ao_maps.py -- --blend path/to/unit.blend
    blender --background --python bake_ao_maps.py -- --blend path/to/unit.blend --samples 64
"""

import bpy
import os
import sys

BAKE_SIZE = 1024
DEFAULT_SAMPLES = 64


def log(msg):
    print(f"[bake_ao] {msg}")


def enable_gpu(scene):
    """Prefer OptiX/CUDA, fall back to CPU."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for ctype in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
            try:
                prefs.compute_device_type = ctype
                prefs.get_devices()
                if any(d.type in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL') for d in prefs.devices):
                    break
            except Exception:
                continue
        has_gpu = False
        for d in prefs.devices:
            if d.type in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
                d.use = True
                has_gpu = True
            else:
                d.use = False
        scene.cycles.device = 'GPU' if has_gpu else 'CPU'
        log(f"Compute device: {scene.cycles.device} ({prefs.compute_device_type})")
    except Exception:
        scene.cycles.device = 'CPU'
        log("Compute device: CPU (fallback)")


def bake_ao(blend_path, size=BAKE_SIZE, samples=DEFAULT_SAMPLES):
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    enable_gpu(scene)

    # Single shared AO image; Cycles writes each face's AO at its UV coords. Atlas UVs
    # are non-overlapping across tile types, so this composites cleanly. L/R mirrored
    # tiles overlap, but mirrored geometry yields symmetric AO (last-write-wins is fine).
    ao_img = bpy.data.images.new("AO_Bake", width=size, height=size, alpha=False, float_buffer=True)
    ao_img.colorspace_settings.name = 'Non-Color'

    # Inject a temporary active Image Texture node into every material on every mesh
    # (Cycles bakes into the material's ACTIVE image-texture node).
    added = []
    mesh_objs = [o for o in scene.objects if o.type == 'MESH']
    for obj in mesh_objs:
        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            node = nodes.new(type='ShaderNodeTexImage')
            node.name = "AO_Bake_Target"
            node.image = ao_img
            nodes.active = node
            added.append((mat, node))

    bpy.ops.object.select_all(action='DESELECT')
    for obj in mesh_objs:
        obj.select_set(True)
    if mesh_objs:
        bpy.context.view_layer.objects.active = mesh_objs[0]

    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.target = 'IMAGE_TEXTURES'
    scene.render.bake.margin = 4
    scene.render.bake.use_clear = True
    log(f"Baking AO ({size}x{size}, {samples} samples)...")
    bpy.ops.object.bake(type='AO')

    # Save the AO image next to the .blend, named by the unit (mesh) name so it matches
    # the <unit_name>_diffuse.png that paint_unit_diffuse.py expects to find.
    if mesh_objs:
        mesh_objs.sort(key=lambda o: len(o.data.vertices), reverse=True)
        unit_name = mesh_objs[0].name
    else:
        unit_name = os.path.splitext(os.path.basename(blend_path))[0]
    blend_dir = os.path.dirname(blend_path)
    out_path = os.path.join(blend_dir, f"{unit_name}_ao.png")
    ao_img.filepath_raw = out_path
    ao_img.file_format = 'PNG'
    ao_img.save()
    log(f"Saved AO map: {out_path}")

    # Remove temporary bake nodes; save the .blend unchanged otherwise.
    for mat, node in added:
        try:
            mat.node_tree.nodes.remove(node)
        except Exception:
            pass
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    return out_path


def parse_args():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    blend = None
    samples = DEFAULT_SAMPLES
    i = 0
    while i < len(args):
        if args[i] == "--blend" and i + 1 < len(args):
            blend = args[i + 1]
        elif args[i] == "--samples" and i + 1 < len(args):
            samples = int(args[i + 1])
        i += 1
    return blend, samples


def main():
    blend, samples = parse_args()
    if not blend or not os.path.exists(blend):
        log("Usage: --blend <path.blend> [--samples N]")
        sys.exit(1)
    bake_ao(blend, samples=samples)
    log("Done.")


if __name__ == "__main__":
    main()