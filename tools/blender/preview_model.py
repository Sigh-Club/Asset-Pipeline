#!/usr/bin/env python3
"""
preview_model.py — Blender script for interactive 3D model preview.

Launched by `pipeline_cli.py preview --unit <name>`.
Opens Blender with the unit's .blend file and configures a clean
viewport for orbit/zoom/pan inspection of the model.

Usage (via CLI):
    python3 tools/pipeline_cli.py preview --unit iron_directorate_line_infantry
"""

import os
import sys
import bpy


def remove_render_objects():
    """Remove cameras and lights from the render scene — not needed for preview.
    Keeps all mesh objects (the model) intact."""
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.data.objects:
        if obj.type in {"CAMERA", "LIGHT"}:
            obj.select_set(True)
    bpy.ops.object.delete(use_global=False)


def setup_viewport(shading_mode="material"):
    """Configure the 3D viewport for clean model preview."""
    shading_types = {"solid": "SOLID", "material": "MATERIAL", "rendered": "RENDERED"}
    shading_type = shading_types.get(shading_mode, "MATERIAL")

    # Find the 3D viewport area and configure it
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.type = shading_type
                space.region_3d.view_perspective = "PERSP"
                # Use temp_override context manager for view_all
                for region in area.regions:
                    if region.type == "WINDOW":
                        with bpy.context.temp_override(
                            window=window, area=area, region=region
                        ):
                            bpy.ops.view3d.view_all(center=True)
                break


def setup_preview_lighting():
    """Add a simple 3-point preview lighting setup."""
    # Clear existing lights
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)

    # Key light — warm, from upper-right-front
    key_data = bpy.data.lights.new("Preview_Key", type="AREA")
    key_data.energy = 200
    key_data.color = (1.0, 0.9, 0.7)  # Warm
    key_obj = bpy.data.objects.new("Preview_Key", key_data)
    bpy.context.collection.objects.link(key_obj)
    key_obj.location = (5, -4, 6)
    key_obj.rotation_euler = (0.8, 0.2, 0.6)

    # Fill light — cool, from lower-left
    fill_data = bpy.data.lights.new("Preview_Fill", type="AREA")
    fill_data.energy = 100
    fill_data.color = (0.6, 0.7, 1.0)  # Cool blue
    fill_obj = bpy.data.objects.new("Preview_Fill", fill_data)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-4, 3, 3)
    fill_obj.rotation_euler = (0.4, 0.1, -0.8)

    # Rim light — from behind
    rim_data = bpy.data.lights.new("Preview_Rim", type="AREA")
    rim_data.energy = 80
    rim_data.color = (1.0, 0.8, 0.9)  # Slight warm tint
    rim_obj = bpy.data.objects.new("Preview_Rim", rim_data)
    bpy.context.collection.objects.link(rim_obj)
    rim_obj.location = (-3, -5, 4)
    rim_obj.rotation_euler = (0.3, 0.0, 2.4)


def add_preview_background():
    """Add a simple ground plane and subtle backdrop."""
    # Ground plane
    bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, -1.5))
    ground = bpy.context.active_object
    ground.name = "Preview_Ground"
    # Create a simple matte material
    mat = bpy.data.materials.new("Preview_Ground_Mat")
    # New materials have nodes enabled by default in Blender 5.x
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.15, 0.15, 0.15, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.8
    # Assign material — plane is new, so slot may not exist
    if ground.data.materials:
        ground.data.materials[0] = mat
    else:
        ground.data.materials.append(mat)


def main():
    # Parse arguments passed after "--"
    unit_name = "model"
    shading_mode = "material"

    if "--" in sys.argv:
        idx = sys.argv.index("--")
        args = sys.argv[idx + 1:]
        for arg in args:
            if arg.startswith("--shading="):
                shading_mode = arg.split("=", 1)[1]
            elif not arg.startswith("--"):
                unit_name = arg

    # Remove render-specific cameras and lights (keep the model)
    remove_render_objects()

    # Add preview lighting and background
    setup_preview_lighting()
    add_preview_background()

    # Configure viewport
    setup_viewport(shading_mode)

    print(f"[preview] Loaded model: {bpy.data.filepath}")
    print(f"[preview] Unit: {unit_name}")
    print(f"[preview] Shading: {shading_mode}")
    print(f"[preview] Controls: Middle-mouse orbit | Scroll zoom | Shift+MMB pan")


if __name__ == "__main__":
    main()
