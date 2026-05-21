#!/usr/bin/env python3
"""
debug_render.py — Quick single-frame render to diagnose visibility issues.
"""

import bpy
import os

# Clear and create simple visible object
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
obj = bpy.context.active_object
obj.name = "DebugCube"

# Simple bright material
mat = bpy.data.materials.new(name="DebugRed")
mat.use_nodes = True
nodes = mat.node_tree.nodes
nodes.clear()
bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
bsdf.inputs['Base Color'].default_value = (1.0, 0.2, 0.2, 1.0)
out = nodes.new(type='ShaderNodeOutputMaterial')
mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
obj.data.materials.append(mat)

# Camera
bpy.ops.object.camera_add(location=(10, -10, 10))
cam = bpy.context.active_object
cam.rotation_euler = (0.9, 0.0, 0.78)  # Point at origin
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 4.0
bpy.context.scene.camera = cam

# Light
bpy.ops.object.light_add(type='SUN', location=(5, 5, 10))

# Render settings
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 96
scene.render.resolution_y = 128
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'

out_file = "/home/talzanar/Documents/Projects/asset-pipeline/assets/characters/test_model/render/debug_frame.png"
os.makedirs(os.path.dirname(out_file), exist_ok=True)
scene.render.filepath = out_file

bpy.ops.render.render(write_still=True)
print(f"Debug render saved: {out_file}")
