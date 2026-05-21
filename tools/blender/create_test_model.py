#!/usr/bin/env python3
"""
create_test_model.py — Generate a minimal Blender test scene
Creates a visible Imperial-style crate (.blend) centered at origin for isometric rendering.
"""

import bpy
import os

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Crate body — centered at origin, visible in 128-unit orthographic view
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
crate = bpy.context.active_object
crate.name = "TestCrate"
crate.scale = (30, 30, 30)  # 60 units tall/wide/deep, fills ~47% of 128px frame

# Material: Gunmetal Dark (#1E1E1E ≈ 0.117, 0.117, 0.117)
mat = bpy.data.materials.new(name="PAL_GunmetalDark")
mat.use_nodes = True
nodes = mat.node_tree.nodes
nodes.clear()
bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
bsdf.inputs['Base Color'].default_value = (0.117, 0.117, 0.117, 1.0)
bsdf.inputs['Roughness'].default_value = 0.9
output = nodes.new(type='ShaderNodeOutputMaterial')
mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

crate.data.materials.append(mat)

# Lid — slightly offset, gold accent, sits on top of crate
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 31))
lid = bpy.context.active_object
lid.name = "TestLid"
lid.scale = (31, 31, 2)

mat2 = bpy.data.materials.new(name="PAL_ImperialGold")
mat2.use_nodes = True
nodes2 = mat2.node_tree.nodes
nodes2.clear()
bsd2 = nodes2.new(type='ShaderNodeBsdfPrincipled')
bsd2.inputs['Base Color'].default_value = (0.831, 0.627, 0.141, 1.0)  # #D4A024
bsd2.inputs['Roughness'].default_value = 0.6
out2 = nodes2.new(type='ShaderNodeOutputMaterial')
mat2.node_tree.links.new(bsd2.outputs['BSDF'], out2.inputs['Surface'])
lid.data.materials.append(mat2)

# Save
out_path = "/home/talzanar/Documents/Projects/asset-pipeline/assets/characters/test_model/model/test_model.blend"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"Test model saved: {out_path}")
