#!/usr/bin/env python3
"""
bake_normal_maps.py — Blender Python script for normal map baking.

Takes a rendered unit's .blend file, duplicates the model, applies subsurf
(level 4) on the duplicate for high-poly detail, bakes a normal map from the
high-poly duplicate onto the original low-poly hard-surface model, saves as
PNG, and applies it in the material shader.

Two-phase bake to avoid circular dependency (baking to an image that is also
connected as a material input).

Usage:
    blender --background --python bake_normal_maps.py -- --blend path/to/unit.blend
    blender --background --python bake_normal_maps.py -- --blend path/to/unit.blend --size 1024
    blender --background --python bake_normal_maps.py -- --batch assets/units/*/model/*.blend

Output:
    - Normal map saved alongside the .blend file as <unit_name>_normal.png
    - Modified .blend saved with normal map applied to all materials
"""

import bpy
import os
import sys
import json
import math
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

BAKE_SIZE = 1024
BAKE_SAMPLES = 64
BAKE_MARGIN = 8
SUBSURF_LEVELS = 4


def log(msg: str):
    print(f"[bake_normal_maps] {msg}")


def ensure_uv_map(obj):
    """Ensure the object has at least one UV map."""
    if not obj.data.uv_layers:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.select_set(False)
        log(f"  Created UV map for {obj.name}")


def create_bake_image(name, size=BAKE_SIZE):
    """Create an image texture for normal map baking, return it."""
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)
    img = bpy.data.images.new(name=name, width=size, height=size, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    return img


def save_bake_image(img, filepath):
    """Save a baked image to disk and return the filepath."""
    img.filepath_raw = filepath
    img.save()
    log(f"  Saved image: {filepath}")


def create_highpoly_duplicate(low_obj):
    """Duplicate the low-poly object and apply subsurf for high-poly detail."""
    bpy.ops.object.select_all(action='DESELECT')
    low_obj.select_set(True)
    bpy.context.view_layer.objects.active = low_obj
    bpy.ops.object.duplicate()
    high_obj = bpy.context.active_object
    high_obj.name = f"{low_obj.name}_highpoly"
    high_obj.data.name = f"{low_obj.data.name}_highpoly"
    high_obj.modifiers.clear()
    mod = high_obj.modifiers.new(name="Subsurf_HighPoly", type='SUBSURF')
    mod.levels = SUBSURF_LEVELS
    mod.render_levels = SUBSURF_LEVELS
    high_obj.location = low_obj.location
    high_obj.rotation_euler = low_obj.rotation_euler
    high_obj.scale = low_obj.scale
    log(f"  Created high-poly: {high_obj.name} (subsurf level {SUBSURF_LEVELS})")
    return high_obj


def add_bake_target_node(mat, image):
    """Add an Image Texture node as bake target to a material. No Normal Map wiring."""
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    # Remove any existing bake target nodes
    for node in list(nodes):
        if node.label == "BAKE_TARGET":
            nodes.remove(node)
    tex = nodes.new(type='ShaderNodeTexImage')
    tex.label = "BAKE_TARGET"
    tex.name = "BakeTarget"
    tex.image = image
    tex.location = (-800, 300)
    return tex


def add_normal_map_nodes(mat, image):
    """Add Image Texture + Normal Map nodes wired to Principled BSDF."""
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Remove previous bake target nodes
    for node in list(nodes):
        if node.label in ("BAKE_TARGET", "NORMAL_TEX", "NORMAL_MAP"):
            nodes.remove(node)

    # Find Principled BSDF
    principled = None
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            principled = node
            break
    if not principled:
        log(f"  WARNING: No Principled BSDF in {mat.name}, skipping")
        return

    # Image Texture
    tex = nodes.new(type='ShaderNodeTexImage')
    tex.label = "NORMAL_TEX"
    tex.name = "NormalTex"
    tex.image = image
    tex.location = (-600, 300)

    # Normal Map node
    nm = nodes.new(type='ShaderNodeNormalMap')
    nm.label = "NORMAL_MAP"
    nm.name = "NormalMap"
    nm.location = (-400, 300)
    nm.space = 'TANGENT'
    nm.inputs['Strength'].default_value = 1.0

    # Wire: Tex -> Normal Map -> Principled Normal
    links.new(tex.outputs['Color'], nm.inputs['Color'])
    links.new(nm.outputs['Normal'], principled.inputs['Normal'])
    log(f"  Connected normal map to {mat.name}")


def run_bake(low_obj, high_obj, image, size=BAKE_SIZE):
    """Execute the Cycles normal map bake."""
    scene = bpy.context.scene
    original_engine = scene.render.engine

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = BAKE_SAMPLES
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = 0.02
    scene.render.bake.max_ray_distance = 0.5
    scene.render.bake.target = 'IMAGE_TEXTURES'
    scene.render.bake.margin = BAKE_MARGIN
    scene.render.bake.use_clear = True

    bpy.ops.object.select_all(action='DESELECT')
    low_obj.select_set(True)
    high_obj.select_set(True)
    bpy.context.view_layer.objects.active = low_obj

    # Mark the image as active bake target in all material slots
    for mat in low_obj.data.materials:
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image == image:
                    mat.node_tree.nodes.active = node

    log(f"  Baking normal map ({size}x{size})...")
    try:
        bpy.ops.object.bake(type='NORMAL', pass_filter={'EMIT', 'DIRECT', 'INDIRECT'})
        log("  Bake succeeded")
    except Exception as e:
        log(f"  Bake error (first attempt): {e}")
        scene.render.bake.use_selected_to_active = False
        bpy.ops.object.bake(type='NORMAL', pass_filter={'EMIT', 'DIRECT', 'INDIRECT'})
        log("  Bake succeeded (fallback)")

    scene.render.engine = original_engine

    # Clean up high-poly
    bpy.ops.object.select_all(action='DESELECT')
    high_obj.select_set(True)
    bpy.data.objects.remove(high_obj, do_unlink=True)


def process_blend_file(blend_path, size=BAKE_SIZE):
    """Full pipeline: load -> bake -> connect -> save."""
    log(f"\n{'='*60}")
    log(f"Processing: {blend_path}")
    log(f"{'='*60}")

    bpy.ops.wm.open_mainfile(filepath=blend_path)
    log(f"  Loaded blend")

    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        log("  ERROR: No mesh objects")
        return None
    meshes.sort(key=lambda o: len(o.data.vertices), reverse=True)
    main_mesh = meshes[0]
    log(f"  Main mesh: {main_mesh.name} ({len(main_mesh.data.vertices)} verts, "
        f"{len(main_mesh.data.materials)} materials)")

    output_dir = os.path.dirname(blend_path)
    normal_name = f"{main_mesh.name}_normal"

    # Ensure UVs
    ensure_uv_map(main_mesh)

    # PHASE 1: Bake
    bake_img = create_bake_image(f"{normal_name}_bake", size)
    for mat in main_mesh.data.materials:
        if mat:
            add_bake_target_node(mat, bake_img)

    highpoly = create_highpoly_duplicate(main_mesh)
    run_bake(main_mesh, highpoly, bake_img, size)

    # Save baked image to disk
    png_path = os.path.join(output_dir, f"{normal_name}.png")
    save_bake_image(bake_img, png_path)

    # Remove the temporary bake image
    bpy.data.images.remove(bake_img)

    # PHASE 2: Connect normal map to materials
    loaded_img = bpy.data.images.load(png_path)
    loaded_img.colorspace_settings.name = 'Non-Color'
    for mat in main_mesh.data.materials:
        if mat:
            add_normal_map_nodes(mat, loaded_img)

    # Save modified .blend
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    log(f"  Saved blend with normal maps: {blend_path}")
    log(f"  Normal map: {png_path}")

    return png_path


def parse_args():
    args = []
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]

    blend_path = None
    batch_pattern = None
    bake_size = BAKE_SIZE

    i = 0
    while i < len(args):
        if args[i] == "--blend" and i + 1 < len(args):
            blend_path = args[i + 1]
            i += 2
        elif args[i] == "--size" and i + 1 < len(args):
            bake_size = int(args[i + 1])
            i += 2
        elif args[i] == "--batch" and i + 1 < len(args):
            batch_pattern = args[i + 1]
            i += 2
        else:
            i += 1

    return blend_path, bake_size, batch_pattern


def main():
    blend_path, bake_size, batch_pattern = parse_args()

    if batch_pattern:
        blend_files = sorted(glob.glob(batch_pattern))
        if not blend_files:
            log(f"ERROR: No .blend files matching '{batch_pattern}'")
            sys.exit(1)
        log(f"Batch mode: {len(blend_files)} files")
        for bf in blend_files:
            process_blend_file(bf, bake_size)
    elif blend_path:
        if not os.path.exists(blend_path):
            log(f"ERROR: File not found: {blend_path}")
            sys.exit(1)
        process_blend_file(blend_path, bake_size)
    else:
        log("Usage:")
        log("  blender --background --python bake_normal_maps.py -- --blend path/to/unit.blend")
        log("  blender --background --python bake_normal_maps.py -- --blend path/to/unit.blend --size 2048")
        log("  blender --background --python bake_normal_maps.py -- --batch 'assets/units/*/model/*.blend'")
        sys.exit(1)

    log("Done.")


if __name__ == "__main__":
    main()
