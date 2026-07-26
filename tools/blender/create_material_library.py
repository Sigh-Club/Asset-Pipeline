#!/usr/bin/env python3
"""
create_material_library.py — Build a Blender material library .blend
with Principled BSDF materials using our procedurally-generated PBR textures.

Run: blender --background --python create_material_library.py
Output: assets/materials/grimdark_materials.blend

Each material uses:
- Principled BSDF with albedo, normal, roughness, metallic maps
- UV-based texture mapping (trilinear repeat)
- Proper color space assignment (sRGB for albedo, Non-Color for data maps)

Materials created:
- MAT_GrimdarkMetal    (dark gunmetal, rust spots, pitting)
- MAT_GrimdarkLeather  (worn brown leather, creases)
- MAT_GrimdarkFabric    (military green fabric, weave)
- MAT_ImperialGold     (warm gold, tarnish)
- MAT_ChaosRust        (heavy corrosion, blood stains)
"""

import bpy
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PBR_DIR = os.path.join(PROJECT_ROOT, "assets", "pbr_textures")
OUTPUT_BLEND = os.path.join(PROJECT_ROOT, "assets", "materials", "grimdark_materials.blend")

sys.path.insert(0, PROJECT_ROOT)


def clear_scene():
    """Remove all objects, materials, meshes."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)


def load_image(path, name, colorspace="sRGB"):
    """Load an image into Blender with the correct color space."""
    img = bpy.data.images.load(path, check_existing=True)
    img.name = name
    if colorspace == "Non-Color":
        img.colorspace_settings.name = "Non-Color"
    else:
        img.colorspace_settings.name = "sRGB"
    return img


def create_pbr_material(name, tex_dir):
    """Create a Principled BSDF material with PBR maps from tex_dir."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Nodes
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)
    
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    
    # Texture coordinate and mapping for UV
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-800, 0)
    
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-600, 0)
    mapping.inputs['Scale'].default_value = (1, 1, 1)
    
    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])
    
    # Load maps
    albedo_path = os.path.join(tex_dir, "albedo.png")
    normal_path = os.path.join(tex_dir, "normal.png")
    rough_path = os.path.join(tex_dir, "roughness.png")
    metal_path = os.path.join(tex_dir, "metallic.png")
    
    offset_x = -400
    spacing = 180
    
    # Albedo
    if os.path.exists(albedo_path):
        albedo_tex = nodes.new("ShaderNodeTexImage")
        albedo_tex.location = (offset_x, 200)
        albedo_tex.label = "Albedo"
        albedo_img = load_image(albedo_path, f"{name}_albedo", "sRGB")
        albedo_tex.image = albedo_img
        links.new(mapping.outputs["Vector"], albedo_tex.inputs["Vector"])
        links.new(albedo_tex.outputs["Color"], bsdf.inputs["Base Color"])
    
    # Normal
    if os.path.exists(normal_path):
        normal_tex = nodes.new("ShaderNodeTexImage")
        normal_tex.location = (offset_x, 0)
        normal_tex.label = "Normal"
        normal_img = load_image(normal_path, f"{name}_normal", "Non-Color")
        normal_tex.image = normal_img
        links.new(mapping.outputs["Vector"], normal_tex.inputs["Vector"])
        
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (offset_x + spacing, 0)
        normal_map.inputs["Strength"].default_value = 1.0
        links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    
    # Roughness
    if os.path.exists(rough_path):
        rough_tex = nodes.new("ShaderNodeTexImage")
        rough_tex.location = (offset_x, -150)
        rough_tex.label = "Roughness"
        rough_img = load_image(rough_path, f"{name}_rough", "Non-Color")
        rough_tex.image = rough_img
        links.new(mapping.outputs["Vector"], rough_tex.inputs["Vector"])
        links.new(rough_tex.outputs["Color"], bsdf.inputs["Roughness"])
    
    # Metallic
    if os.path.exists(metal_path):
        metal_tex = nodes.new("ShaderNodeTexImage")
        metal_tex.location = (offset_x, -300)
        metal_tex.label = "Metallic"
        metal_img = load_image(metal_path, f"{name}_metal", "Non-Color")
        metal_tex.image = metal_img
        links.new(mapping.outputs["Vector"], metal_tex.inputs["Vector"])
        links.new(metal_tex.outputs["Color"], bsdf.inputs["Metallic"])
    
    # Link BSDF to output
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    
    # Set defaults for Principled BSDF
    bsdf.inputs["Specular IOR Level"].default_value = 0.5 if "Specular IOR Level" in bsdf.inputs else 0.5
    if "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.5
    
    print(f"  Created material: {name}")
    return mat


def main():
    clear_scene()
    
    # Add a dummy mesh so the .blend has something
    bpy.ops.mesh.primitive_cube_add(size=0.01, location=(100, 100, 100))
    bpy.context.active_object.name = "_DELETE_ME"
    
    materials = {
        "MAT_GrimdarkMetal": "grimdark_metal",
        "MAT_GrimdarkLeather": "grimdark_leather",
        "MAT_GrimdarkFabric": "grimdark_fabric",
        "MAT_ImperialGold": "imperial_gold",
        "MAT_ChaosRust": "chaos_rust",
        "MAT_BioFlesh": "bio_flesh",
        "MAT_ChromeWhite": "chrome_white",
        "MAT_CyanBone": "cyan_bone",
        "MAT_RedRust": "red_rust",
        "MAT_BlackSilver": "black_silver",
    }
    
    print(f"Building material library from {PBR_DIR}")
    
    for mat_name, tex_subdir in materials.items():
        tex_dir = os.path.join(PBR_DIR, tex_subdir)
        if not os.path.exists(tex_dir):
            print(f"  WARNING: {tex_dir} not found, skipping {mat_name}")
            continue
        mat = create_pbr_material(mat_name, tex_dir)
        mat.use_fake_user = True  # Prevent purge on save (no object users)
    
    # Remove the dummy mesh
    bpy.data.objects.remove(bpy.data.objects["_DELETE_ME"], do_unlink=True)
    
    # Save
    os.makedirs(os.path.dirname(OUTPUT_BLEND), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_BLEND)
    print(f"\nMaterial library saved: {OUTPUT_BLEND}")
    print(f"Materials: {list(bpy.data.materials.keys())}")


if __name__ == "__main__":
    main()