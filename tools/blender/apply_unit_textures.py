#!/usr/bin/env python3
"""
apply_unit_textures.py — Apply a per-unit painted diffuse atlas to a generated .blend.

DoW1-style material setup: Base Color = painted diffuse atlas (CLAMP, no repeat so
detail doesn't bleed across tiles), Metallic + Roughness from per-material constants.
DoW1 has no normal maps — surface micro-detail is carried by the painted diffuse.
The team-colour mask is generated alongside but not wired into the static shader (it is
saved for the game engine's runtime player-colour tinting).

Usage:
    blender --background --python apply_unit_textures.py -- --blend path/to/unit.blend
    blender --background --python apply_unit_textures.py -- --batch 'assets/units/*/model/*.blend'

Prerequisite: the per-unit <unit>_diffuse.png must exist in the .blend's directory
(generate with tools/pbr/paint_unit_diffuse.py).
"""

import bpy
import os
import sys
import glob

# Per-material PBR constants (DoW1: constants, not tiled maps).
MATERIAL_CONSTANTS = {
    "MAT_GrimdarkMetal":   {"metallic": 0.90, "roughness": 0.42},
    "MAT_ImperialGold":    {"metallic": 1.00, "roughness": 0.30},
    "MAT_GrimdarkLeather": {"metallic": 0.00, "roughness": 0.65},
    "MAT_GrimdarkFabric":  {"metallic": 0.00, "roughness": 0.78},
    "MAT_ChaosRust":       {"metallic": 0.40, "roughness": 0.75},
    "MAT_BioFlesh":        {"metallic": 0.00, "roughness": 0.55},
    "MAT_ChromeWhite":     {"metallic": 0.95, "roughness": 0.18},
    "MAT_CyanBone":        {"metallic": 0.00, "roughness": 0.55},
    "MAT_RedRust":         {"metallic": 0.50, "roughness": 0.70},
    "MAT_BlackSilver":     {"metallic": 0.80, "roughness": 0.40},
}
DEFAULT_CONSTANTS = {"metallic": 0.0, "roughness": 0.5}


def log(msg):
    print(f"[apply_unit_textures] {msg}")


def find_diffuse(blend_dir, unit_name):
    """Locate the per-unit diffuse atlas next to the .blend."""
    cand = os.path.join(blend_dir, f"{unit_name}_diffuse.png")
    if os.path.exists(cand):
        return cand
    # Fallback: any *_diffuse.png in the dir
    for f in glob.glob(os.path.join(blend_dir, "*_diffuse.png")):
        return f
    return None


def rewire_material(mat, diffuse_img):
    """Set Base Color = diffuse atlas (CLAMP), Metallic/Roughness from constants."""
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Find or create Principled BSDF + Output
    principled = None
    output = None
    for n in nodes:
        if n.type == 'BSDF_PRINCIPLED':
            principled = n
        elif n.type == 'OUTPUT_MATERIAL':
            output = n
    if not principled:
        principled = nodes.new('ShaderNodeBsdfPrincipled')
        principled.location = (300, 0)
    if not output:
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (600, 0)

    # Remove existing texture/normal/mapping nodes (we replace the base-colour chain)
    for n in list(nodes):
        if n in (principled, output):
            continue
        nodes.remove(n)

    # Image Texture (diffuse atlas), CLAMP extension so it doesn't repeat across tiles
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = diffuse_img
    tex.location = (-400, 0)
    tex.interpolation = 'Cubic'
    tex.extension = 'EXTEND'        # clamp outside 0-1 (no repeat)
    tex.image.colorspace_settings.name = 'sRGB'

    # Constants
    consts = MATERIAL_CONSTANTS.get(mat.name, DEFAULT_CONSTANTS)
    principled.inputs['Metallic'].default_value = consts['metallic']
    principled.inputs['Roughness'].default_value = consts['roughness']

    # Wire: diffuse -> Base Color, BSDF -> Output
    links.new(tex.outputs['Color'], principled.inputs['Base Color'])
    # Use the image alpha (opaque atlas, but keep correct if any) for the alpha socket
    if 'Alpha' in principled.inputs:
        links.new(tex.outputs['Alpha'], principled.inputs['Alpha'])
    links.new(principled.outputs['BSDF'], output.inputs['Surface'])


def process_blend(blend_path):
    log(f"Processing: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    blend_dir = os.path.dirname(blend_path)
    # Unit name = largest mesh object name
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        log("  ERROR: no mesh")
        return False
    meshes.sort(key=lambda o: len(o.data.vertices), reverse=True)
    unit_name = meshes[0].name

    diffuse_path = find_diffuse(blend_dir, unit_name)
    if not diffuse_path:
        log(f"  ERROR: no *_diffuse.png found in {blend_dir}")
        return False
    diffuse_img = bpy.data.images.load(diffuse_path, check_existing=True)
    diffuse_img.colorspace_settings.name = 'sRGB'
    log(f"  Diffuse: {diffuse_path} ({diffuse_img.size[0]}x{diffuse_img.size[1]})")

    for mat in bpy.data.materials:
        rewire_material(mat, diffuse_img)
        log(f"  Rewired: {mat.name}")

    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    log(f"  Saved: {blend_path}")
    return True


def parse_args():
    args = []
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
    blend = None
    batch = None
    i = 0
    while i < len(args):
        if args[i] == "--blend" and i + 1 < len(args):
            blend = args[i + 1]; i += 2
        elif args[i] == "--batch" and i + 1 < len(args):
            batch = args[i + 1]; i += 2
        else:
            i += 1
    return blend, batch


def main():
    blend, batch = parse_args()
    if batch:
        for bf in sorted(glob.glob(batch)):
            process_blend(bf)
    elif blend:
        if not os.path.exists(blend):
            log(f"ERROR: {blend} not found"); sys.exit(1)
        process_blend(blend)
    else:
        log("Usage: --blend <path> | --batch 'glob'"); sys.exit(1)
    log("Done.")


if __name__ == "__main__":
    main()